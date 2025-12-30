"""RAG pipeline orchestrator - combines retrieval and generation."""
from typing import List, Dict, Any, Optional
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.multilingual import LanguageDetector
from src.rag.audit import get_logger
from src.rag.temporal.retriever import MultiTenantRetriever, apply_rrf_fusion

log = get_logger(__name__)


class RAGOrchestrator:
    """Orchestrates the full RAG pipeline: retrieve -> generate."""

    DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided context and conversation history.

Guidelines:
- Answer questions using the information from the provided context.
- Remember and reference previous messages in the conversation when relevant.
- If asked to repeat or translate previous responses, use the conversation history.
- If the context doesn't contain enough information to answer, say so clearly.
- Be concise but complete in your answers.
- Cite sources when relevant (mention document names/paths).
- If multiple sources provide conflicting information, acknowledge this.
"""

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

        log.info(
            "Initialized RAGOrchestrator with system_prompt=%s chars, multilingual=%s, "
            "chat_memory=%s, multi_tenant=%s, file_tracker=%s",
            len(self.system_prompt),
            enable_multilingual,
            chat_memory_manager is not None,
            multi_tenant_retriever is not None,
            file_tracker is not None,
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

        # Step 1: Retrieve relevant documents (KB + temporal if thread_id provided)
        temporal_results = []
        kb_results = []

        if self.multi_tenant_retriever and thread_id:
            # Use multi-tenant retriever (KB + temporal)
            log.debug(f"Using multi-tenant retriever for thread {thread_id}")
            retrieval_result = self.multi_tenant_retriever.retrieve_with_temporal(
                query=question,
                thread_id=thread_id,
                top_k_total=top_k or 10,
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
            # Standard single-tenant retrieval
            retrieved_docs = self.retriever.retrieve(query=question, top_k=top_k, filters=filters)
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
                    top_k=top_k or 10,
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

        if not retrieved_docs:
            log.warning("No documents retrieved for query")
            return {
                "answer": "I couldn't find any relevant information to answer your question.",
                "sources": [],
                "metadata": {
                    "retrieved_count": 0,
                    "query": question,
                    "model": model,
                },
            }

        log.info("Retrieved %d documents", len(retrieved_docs))

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

        # Step 4: Extract unique sources
        sources = self._extract_sources(retrieved_docs)

        return {
            "answer": answer,
            "sources": sources if self.include_sources else [],
            "metadata": {
                "retrieved_count": len(retrieved_docs),
                "kb_count": len(kb_results),
                "temporal_count": len(temporal_results),
                "query": question,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "used_chat_memory": used_chat_memory,
                "used_temporal_rag": len(temporal_results) > 0,
                "thread_id": thread_id,
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
            context: Retrieved context.
            temperature: LLM temperature.
            max_tokens: Max response tokens.
            system_prompt: Override system prompt.
            model: Override default model.
            conversation_history: Full conversation history for context.

        Returns:
            Generated answer.
        """
        # Detect language and adapt system prompt if multilingual is enabled
        if self.enable_multilingual and not system_prompt:
            detected_lang = self.language_detector.detect_language(question)
            lang_name = self.language_detector.get_language_name(detected_lang)
            log.info("Detected query language: %s (%s)", lang_name, detected_lang)

            # Get localized system prompt
            localized_prompt = self.language_detector.get_system_prompt(detected_lang)
            # Add explicit language instruction
            final_prompt = self.language_detector.add_language_instruction(
                localized_prompt, detected_lang
            )
        else:
            final_prompt = system_prompt or self.system_prompt

        # Build messages with conversation history if provided
        messages = [{"role": "system", "content": final_prompt}]

        # Add conversation history (excluding the last user message)
        if conversation_history:
            # Filter out the last user message (it's the current question)
            for msg in conversation_history[:-1]:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            log.info("Added %d historical messages to context", len(conversation_history) - 1)

        # Add current question with RAG context
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
