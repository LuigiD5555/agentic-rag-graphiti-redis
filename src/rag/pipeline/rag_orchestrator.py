"""RAG pipeline orchestrator - combines retrieval and generation."""
from typing import List, Dict, Any, Optional
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.multilingual import LanguageDetector
from src.rag.audit import get_logger

log = get_logger(__name__)


class RAGOrchestrator:
    """Orchestrates the full RAG pipeline: retrieve -> generate."""

    DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided context.

Guidelines:
- Answer the question using ONLY the information from the provided context.
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
    ):
        """Initialize RAG orchestrator.

        Args:
            retriever: Document retriever instance.
            chat_service: LLM chat service instance.
            system_prompt: Custom system prompt (uses default if None).
            include_sources: Whether to include source citations in response.
            enable_multilingual: Enable automatic language detection and localization.
        """
        self.retriever = retriever
        self.chat_service = chat_service
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.include_sources = include_sources
        self.enable_multilingual = enable_multilingual
        self.language_detector = LanguageDetector()

        log.info(
            "Initialized RAGOrchestrator with system_prompt=%s chars, multilingual=%s",
            len(self.system_prompt),
            enable_multilingual
        )

    def query(
        self,
        question: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute full RAG pipeline for a question.

        Args:
            question: User's question.
            top_k: Number of documents to retrieve (uses retriever default if None).
            filters: Optional metadata filters for retrieval.
            temperature: LLM temperature (0.0-1.0).
            max_tokens: Maximum response tokens.
            system_prompt: Override the default system prompt if provided.

        Returns:
            Dictionary with 'answer', 'sources', and 'metadata'.
        """
        log.info("Processing RAG query: %s", question[:100])

        # Step 1: Retrieve relevant documents
        retrieved_docs = self.retriever.retrieve(query=question, top_k=top_k, filters=filters)

        if not retrieved_docs:
            log.warning("No documents retrieved for query")
            return {
                "answer": "I couldn't find any relevant information to answer your question.",
                "sources": [],
                "metadata": {
                    "retrieved_count": 0,
                    "query": question,
                },
            }

        log.info("Retrieved %d documents", len(retrieved_docs))

        # Step 2: Build context from retrieved documents
        context = self._build_context(retrieved_docs)

        # Step 3: Generate answer using LLM
        answer = self._generate_answer(
            question=question,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

        # Step 4: Extract unique sources
        sources = self._extract_sources(retrieved_docs)

        return {
            "answer": answer,
            "sources": sources if self.include_sources else [],
            "metadata": {
                "retrieved_count": len(retrieved_docs),
                "query": question,
                "temperature": temperature,
                "max_tokens": max_tokens,
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
    ) -> str:
        """Generate answer using LLM with retrieved context.

        Args:
            question: User's question.
            context: Retrieved context.
            temperature: LLM temperature.
            max_tokens: Max response tokens.
            system_prompt: Override system prompt.

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

        # Build prompt with system message, context, and question
        messages = [
            {"role": "system", "content": final_prompt},
            {
                "role": "user",
                "content": f"""Context:
{context}

Question: {question}

Answer:"""
            },
        ]

        answer = self.chat_service.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
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


__all__ = ["RAGOrchestrator"]
