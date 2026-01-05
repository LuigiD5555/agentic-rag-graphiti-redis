"""RAG pipeline orchestrator - combines retrieval and generation."""
from typing import List, Dict, Any, Optional
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.multilingual import LanguageDetector
from src.rag.audit import get_logger
from src.rag.temporal.retriever import MultiTenantRetriever
from src.rag.web_search import SearXNGClient
from src.rag.intent import IntentClassifier

log = get_logger(__name__)


class RAGOrchestrator:
    """Orchestrates the full RAG pipeline: retrieve -> generate."""

    DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant that answers questions based on the "
        "provided context and conversation history.\n\n"
        "Guidelines:\n"
        "- Answer questions using the information from the provided context.\n"
        "- Remember and reference previous messages when relevant.\n"
        "- If asked to repeat or translate previous responses, use the history.\n"
        "- If the context doesn't contain enough information, say so clearly.\n"
        "- Be concise but complete in your answers.\n"
        "- Cite sources when relevant (mention document names/paths).\n"
        "- If multiple sources provide conflicting information, acknowledge this.\n"
    )

    CONVERSATIONAL_SYSTEM_PROMPT = (
        "You are a helpful and friendly assistant. "
        "Respond naturally to greetings, thanks, and casual conversation. "
        "Be concise, warm, and conversational. "
        "You don't need to provide sources or context - just engage naturally with the user."
    )

    def __init__(
        self,
        retriever: WeaviateRetriever,
        chat_service: LMStudioChatService,
        system_prompt: Optional[str] = None,
        include_sources: bool = True,
        enable_multilingual: bool = True,
        chat_memory_manager: Optional[Any] = None,
        multi_tenant_retriever: Optional[MultiTenantRetriever] = None,
        file_tracker: Optional[Any] = None,
        web_search_client: Optional[SearXNGClient] = None,
        enable_web_fallback: bool = True,
        min_relevance_score: float = 0.5,
        enable_rag_gating: bool = True,
    ):
        """Initialize RAG orchestrator.

        Args:
            retriever: Document retriever instance.
            chat_service: LLM chat service instance.
            system_prompt: Custom system prompt (uses default if None).
            include_sources: Whether to include source citations in response.
            enable_multilingual: Enable automatic language detection and localization.
            chat_memory_manager: Optional ChatMemory manager for cross-chat recall.
            multi_tenant_retriever: Optional multi-tenant retriever for temporal files.
            file_tracker: Optional FileTracker for tracking chunk usage.
            web_search_client: Optional SearXNG client for web search fallback.
            enable_web_fallback: Enable web search when local retrieval fails or has low relevance.
            min_relevance_score: Minimum score threshold for triggering web search fallback.
            enable_rag_gating: Enable intent-based RAG gating (skip RAG for trivial queries).
        """
        self.retriever = retriever
        self.chat_service = chat_service
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.include_sources = include_sources
        self.enable_multilingual = enable_multilingual
        self.language_detector = LanguageDetector()
        self.chat_memory_manager = chat_memory_manager
        self.multi_tenant_retriever = multi_tenant_retriever
        self.file_tracker = file_tracker
        self.web_search_client = web_search_client
        self.enable_web_fallback = enable_web_fallback
        self.min_relevance_score = min_relevance_score
        self.enable_rag_gating = enable_rag_gating
        self.intent_classifier = IntentClassifier() if enable_rag_gating else None

        log.info(
            "Initialized RAGOrchestrator with system_prompt=%s chars, multilingual=%s, "
            "chat_memory=%s, multi_tenant=%s, file_tracker=%s, web_search=%s, web_fallback=%s, rag_gating=%s",
            len(self.system_prompt),
            enable_multilingual,
            chat_memory_manager is not None,
            multi_tenant_retriever is not None,
            file_tracker is not None,
            web_search_client is not None,
            enable_web_fallback,
            enable_rag_gating,
        )

    def query(
        self,
        question: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute full RAG pipeline for a question.

        Args:
            question: User's question.
            top_k: Number of documents to retrieve (uses retriever default if None).
            filters: Optional metadata filters for retrieval.
            temperature: LLM temperature (0.0-1.0).
            max_tokens: Maximum response tokens.
            system_prompt: Override the default system prompt if provided.
            model: Override the default LLM model (allows per-request model selection).
            user_id: Optional user ID for cross-chat memory retrieval.
            conversation_history: Full conversation history for context-aware responses.
            thread_id: Optional thread ID for temporal file retrieval.

        Returns:
            Dictionary with 'answer', 'sources', and 'metadata'.
        """
        log.info("Processing RAG query with model=%s, thread_id=%s: %s",
                 model or "default", thread_id or "none", question[:100])

        # Step 0: Intent classification for RAG gating
        intent = None
        skip_rag = False
        if self.enable_rag_gating and self.intent_classifier:
            intent = self.intent_classifier.classify(question)
            skip_rag = not self.intent_classifier.should_use_rag(intent)

            if skip_rag:
                log.info(
                    "RAG gating: skipping retrieval for intent=%s "
                    "(SMALL_TALK/PERSONAL_CHAT/CONTROL/GENERAL_KNOWLEDGE)",
                    intent
                )
                # Skip RAG, go directly to LLM
                answer = self._generate_answer(
                    question=question,
                    context="",  # No RAG context
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    model=model,
                    conversation_history=conversation_history,
                )

                return {
                    "answer": answer,
                    "sources": [],
                    "metadata": {
                        "retrieved_count": 0,
                        "query": question,
                        "model": model,
                        "intent": intent,
                        "rag_gating": True,
                        "skip_rag": True,
                        "reason": f"Intent {intent} does not require RAG",
                    },
                }

        # Step 1: Retrieve relevant documents (KB + temporal if thread_id provided)
        temporal_results = []
        kb_results = []
        retrieval_metadata = {}
        retrieval_error = None

        if self.multi_tenant_retriever and thread_id:
            # Use multi-tenant retriever (KB + temporal)
            log.debug(f"Using multi-tenant retriever for thread {thread_id}")
            retrieval_result = self.multi_tenant_retriever.retrieve_with_temporal(
                query=question,
                thread_id=thread_id,
                top_k_total=top_k or 6,  # Reduced from 10 to 6 for memory optimization
            )

            retrieved_docs = retrieval_result["combined_results"]
            temporal_results = retrieval_result["temporal_results"]
            kb_results = retrieval_result["kb_results"]

            log.info(
                "Multi-tenant retrieval: KB=%d, temporal=%d, combined=%d",
                retrieval_result["kb_count"],
                retrieval_result["temporal_count"],
                retrieval_result["total_count"],
            )

            # Track chunk usage for Pareto analysis
            if self.file_tracker and temporal_results and thread_id:
                self._track_temporal_chunk_usage(
                    thread_id=thread_id,
                    temporal_results=temporal_results,
                    query=question,
                )
        else:
            # Standard single-tenant retrieval with new signature
            retrieved_docs, retrieval_metadata = self.retriever.retrieve(
                query=question, top_k=top_k, filters=filters
            )

            # Check if retrieval failed
            if retrieved_docs is None:
                retrieval_error = retrieval_metadata.get("error_type", "unknown")
                log.error(
                    "Retrieval failed: error_type=%s, error=%s, retries=%d, time=%.2fms",
                    retrieval_error,
                    retrieval_metadata.get("error"),
                    retrieval_metadata.get("retries", 0),
                    retrieval_metadata.get("total_time_ms", 0)
                )
                retrieved_docs = []  # Set to empty list for downstream processing
            else:
                kb_results = retrieved_docs

        # Step 1.5: If ChatMemory enabled and user_id provided, retrieve + fuse with memory
        memory_context = ""
        used_chat_memory = False
        if self.chat_memory_manager and user_id:
            try:
                memory_results = self.chat_memory_manager.retrieve_with_memory(
                    query=question,
                    user_id=user_id,
                    kb_results=retrieved_docs,
                    top_k=top_k or 6,  # Reduced from 10 to 6 for memory optimization
                )

                # Use fused results if available
                if memory_results.get("combined_results"):
                    retrieved_docs = memory_results["combined_results"]
                    used_chat_memory = True
                    log.info(
                        "ChatMemory: RRF=%s, MMR=%s, results=%d",
                        memory_results.get("used_rrf"),
                        memory_results.get("used_mmr"),
                        len(retrieved_docs)
                    )

                # Format memory context for injection
                if memory_results.get("memory_results"):
                    memory_context = self.chat_memory_manager.format_memory_context(
                        memory_results["memory_results"],
                        max_length=500,
                    )
            except Exception as e:
                log.warning("ChatMemory retrieval failed, continuing without it: %s", e)

        # Step 2: Determine if web search fallback is needed
        web_results = []
        used_web_search = False
        trigger_web_search = False

        if not retrieved_docs:
            log.warning("No documents retrieved from local sources")
            trigger_web_search = True
        elif retrieval_error:
            log.warning("Retrieval error occurred: %s", retrieval_error)
            trigger_web_search = True
        elif retrieval_metadata.get("low_relevance"):
            avg_score = retrieval_metadata.get("avg_score", 0.0)
            log.warning(
                "Low relevance score detected: %.3f (threshold: %.2f)",
                avg_score, self.min_relevance_score
            )
            # For GENERAL_KNOWLEDGE queries with low relevance, prefer web search
            # For PERSONAL_KB queries, trust the RAG results even if low (user's data is what they want)
            if intent == "GENERAL_KNOWLEDGE":
                trigger_web_search = True
            else:
                log.info("PERSONAL_KB intent: using RAG results despite low relevance")
                trigger_web_search = False

        # Step 2.5: Execute web search if triggered and enabled
        if trigger_web_search and self.enable_web_fallback and self.web_search_client:
            log.info("Triggering web search fallback for query: %s", question[:50])
            try:
                # Import asyncio for running async web search in sync context
                import asyncio

                # Run async web search - handle both sync and async contexts
                try:
                    # Try to get running event loop
                    asyncio.get_running_loop()
                    # We're in async context - this shouldn't happen in current design
                    # but handle gracefully by running in thread pool
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self.web_search_client.search_and_format(
                                query=question,
                                categories=["general"]
                            )
                        )
                        web_results = future.result(timeout=30.0)
                except RuntimeError:
                    # No running event loop (normal case), create one
                    web_results = asyncio.run(
                        self.web_search_client.search_and_format(
                            query=question,
                            categories=["general"]
                        )
                    )

                used_web_search = True

                if web_results:
                    log.info("Web search returned %d results", len(web_results))

                    # Fusión: Combinar resultados locales + web
                    if retrieved_docs:
                        # Fusionar: priorizar docs locales, agregar web como suplemento
                        retrieved_docs = retrieved_docs + web_results
                        log.info(
                            "Fused local (%d) + web (%d) = %d total results",
                            len(kb_results), len(web_results), len(retrieved_docs)
                        )
                    else:
                        # Reemplazar: solo usar web si no hay docs locales
                        retrieved_docs = web_results
                        log.info("Using only web results (%d)", len(web_results))
                else:
                    log.warning("Web search returned no results")
            except Exception as e:
                log.error("Web search failed: %s", e, exc_info=True)

        # Step 2.7: Final fallback - LLM without context if everything failed
        if not retrieved_docs:
            log.warning("No documents retrieved from any source (local or web)")

            # For GENERAL_KNOWLEDGE, use LLM without context (model has general knowledge)
            # For PERSONAL_KB, inform user that no relevant documents were found
            if intent == "GENERAL_KNOWLEDGE":
                log.info("GENERAL_KNOWLEDGE: Falling back to LLM general knowledge")
                answer = self._generate_answer(
                    question=question,
                    context="",  # No context available
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    model=model,
                    conversation_history=conversation_history,
                )
            else:
                # PERSONAL_KB but no documents found - inform user
                log.info("PERSONAL_KB: No documents found, informing user")
                answer = (
                    "I couldn't find relevant information in your documents to answer this question. "
                    "Could you provide more context or check if the information is available in your files?"
                )

            return {
                "answer": answer,
                "sources": [],
                "metadata": {
                    "retrieved_count": 0,
                    "query": question,
                    "model": model,
                    "retrieval_error": retrieval_error,
                    "used_web_search": used_web_search,
                    "fallback_mode": "llm_only" if intent == "GENERAL_KNOWLEDGE" else "no_docs_found",
                    "retrieval_metadata": retrieval_metadata,
                    "intent": intent,
                    "rag_gating": self.enable_rag_gating,
                },
            }

        log.info(
            "Retrieved %d documents (%d local, %d web)",
            len(retrieved_docs), len(kb_results), len(web_results)
        )

        # Step 2.8: Check if all retrieved documents have extremely low relevance
        # If all scores are below 5%, treat as if no documents were found
        max_score = max((doc.get("score", 0.0) for doc in retrieved_docs), default=0.0)
        if max_score < 0.05:
            log.warning("All retrieved documents have very low relevance (max=%.3f)", max_score)

            # For GENERAL_KNOWLEDGE, use LLM without context
            if intent == "GENERAL_KNOWLEDGE":
                log.info("GENERAL_KNOWLEDGE: Falling back to LLM (irrelevant RAG results)")
                answer = self._generate_answer(
                    question=question,
                    context="",  # Ignore irrelevant context
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    model=model,
                    conversation_history=conversation_history,
                )

                return {
                    "answer": answer,
                    "sources": [],  # Don't show irrelevant sources
                    "metadata": {
                        "retrieved_count": 0,
                        "query": question,
                        "model": model,
                        "fallback_mode": "llm_only_irrelevant_results",
                        "max_relevance_score": max_score,
                        "intent": intent,
                        "rag_gating": self.enable_rag_gating,
                    },
                }
            else:
                # PERSONAL_KB: inform user that no relevant documents were found
                log.info("PERSONAL_KB: No relevant documents found (max score=%.3f)", max_score)
                answer = (
                    "No encontré información relevante en tus documentos para responder esta pregunta. "
                    "Verifica que los documentos estén indexados correctamente o proporciona más contexto."
                )

                return {
                    "answer": answer,
                    "sources": [],
                    "metadata": {
                        "retrieved_count": 0,
                        "query": question,
                        "model": model,
                        "fallback_mode": "no_relevant_docs",
                        "max_relevance_score": max_score,
                        "intent": intent,
                        "rag_gating": self.enable_rag_gating,
                    },
                }

        # Step 2: Build context from retrieved documents
        context = self._build_context(retrieved_docs)

        # Step 2.5: Prepend memory context if available
        if memory_context:
            context = f"{memory_context}\n\n## Relevant documents:\n{context}"

        # Step 3: Generate answer using LLM
        answer = self._generate_answer(
            question=question,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            model=model,
            conversation_history=conversation_history,
        )

        # Step 3.5: Add prefix if we used web search as primary source
        # (when no local docs were useful and we got results from web)
        if used_web_search and len(kb_results) == 0 and len(web_results) > 0:
            answer = (
                "No encontre informacion relevante en tus documentos, "
                "pero busque en internet y encontre lo siguiente:\n\n"
                + answer
            )
            log.info("Added web search fallback prefix to answer")

        # Step 4: Extract unique sources
        sources = self._extract_sources(retrieved_docs)

        return {
            "answer": answer,
            "sources": sources if self.include_sources else [],
            "metadata": {
                "retrieved_count": len(retrieved_docs),
                "kb_count": len(kb_results),
                "temporal_count": len(temporal_results),
                "web_count": len(web_results),
                "query": question,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "used_chat_memory": used_chat_memory,
                "used_temporal_rag": len(temporal_results) > 0,
                "used_web_search": used_web_search,
                "retrieval_error": retrieval_error,
                "thread_id": thread_id,
                "retrieval_metadata": retrieval_metadata,
                "intent": intent,
                "rag_gating": self.enable_rag_gating,
            },
        }

    def _build_context(self, documents: List[Dict[str, Any]]) -> str:
        """Build context string from retrieved documents.

        Args:
            documents: List of retrieved document dicts.

        Returns:
            Formatted context string.
        """
        context_parts = []

        for i, doc in enumerate(documents, 1):
            source = doc.get("source", "Unknown")
            text = doc.get("text", "")
            score = doc.get("score", 0.0)

            # Format each chunk with metadata
            chunk_text = f"[Document {i}] (Source: {source}, Score: {score:.3f})\n{text}\n"
            context_parts.append(chunk_text)

        context = "\n---\n".join(context_parts)
        log.debug("Built context: %d chars from %d documents", len(context), len(documents))
        return context

    def _generate_answer(
        self,
        question: str,
        context: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate answer using LLM with retrieved context.

        Args:
            question: User's question.
            context: Retrieved context (empty string for conversational queries).
            temperature: LLM temperature.
            max_tokens: Max response tokens.
            system_prompt: Override system prompt.
            model: Override default model.
            conversation_history: Full conversation history for context.

        Returns:
            Generated answer.
        """
        # Determine if this is a conversational query (no RAG context)
        is_conversational = not context or len(context.strip()) == 0

        # Detect language and adapt system prompt if multilingual is enabled
        if self.enable_multilingual and not system_prompt:
            detected_lang = self.language_detector.detect_language(question)
            lang_name = self.language_detector.get_language_name(detected_lang)
            log.info("Detected query language: %s (%s)", lang_name, detected_lang)

            if is_conversational:
                # Use conversational prompt for queries without RAG context
                final_prompt = self.CONVERSATIONAL_SYSTEM_PROMPT
                log.info("Using conversational system prompt (no RAG context)")
            else:
                # Get localized system prompt for RAG queries
                localized_prompt = self.language_detector.get_system_prompt(detected_lang)
                # Add explicit language instruction
                final_prompt = self.language_detector.add_language_instruction(
                    localized_prompt, detected_lang
                )
        else:
            # Use provided system_prompt or default based on context availability
            if is_conversational:
                final_prompt = system_prompt or self.CONVERSATIONAL_SYSTEM_PROMPT
                log.info("Using conversational system prompt (no RAG context)")
            else:
                final_prompt = system_prompt or self.system_prompt

        # Build messages with conversation history if provided
        messages = [{"role": "system", "content": final_prompt}]

        # Add full conversation history (doesn't include current question yet)
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            log.info("Added %d historical messages to context", len(conversation_history))

        # Format user message based on whether we have RAG context
        if is_conversational:
            # Simple conversational message without context formatting
            messages.append({
                "role": "user",
                "content": question
            })
        else:
            # RAG-style message with context
            messages.append({
                "role": "user",
                "content": f"""Context:
{context}

Question: {question}

Answer:"""
            })

        answer = self.chat_service.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

        return answer

    def _extract_sources(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract unique sources from retrieved documents.

        Args:
            documents: List of retrieved documents.

        Returns:
            List of unique sources with metadata.
        """
        sources_seen = set()
        sources = []

        for doc in documents:
            source_path = doc.get("source", "Unknown")

            if source_path not in sources_seen:
                sources_seen.add(source_path)
                sources.append({
                    "path": source_path,
                    "relevance_score": doc.get("score", 0.0),
                })

        return sources

    def _track_temporal_chunk_usage(
        self,
        thread_id: str,
        temporal_results: List[Dict[str, Any]],
        query: str,
    ) -> None:
        """Track chunk usage from temporal files for Pareto analysis.

        Args:
            thread_id: Thread identifier
            temporal_results: List of temporal chunks used in query
            query: User query
        """
        if not self.file_tracker or not temporal_results:
            return

        try:
            # Group chunks by file (source)
            chunks_by_file = {}
            for doc in temporal_results:
                source = doc.get("source", "")
                chunk_id = doc.get("uuid", "")
                score = doc.get("score", 0.0)

                if source not in chunks_by_file:
                    chunks_by_file[source] = []

                chunks_by_file[source].append({
                    "chunk_id": chunk_id,
                    "score": score,
                })

            # Track usage for each file
            # We need to map source back to file_id - for now we'll extract from source path
            # This is a simplification - in production you'd want better file_id tracking
            for source, chunks in chunks_by_file.items():
                # Try to extract file_id from Redis using source path
                file_ids = self.file_tracker.list_temporal_files(thread_id)

                for file_id in file_ids:
                    file_info = self.file_tracker.get_temporal_file_info(thread_id, file_id)

                    if not file_info:
                        continue

                    # Track each chunk
                    for chunk_data in chunks:
                        self.file_tracker.track_chunk_usage(
                            thread_id=thread_id,
                            file_id=file_id,
                            chunk_id=chunk_data["chunk_id"],
                            relevance_score=chunk_data["score"],
                            query=query,
                        )

            log.debug(
                f"Tracked {len(temporal_results)} temporal chunks from {len(chunks_by_file)} files"
            )

        except Exception as e:
            log.error(f"Failed to track temporal chunk usage: {e}", exc_info=True)


__all__ = ["RAGOrchestrator"]
