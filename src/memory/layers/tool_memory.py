"""Tool memory manager for tracking tool executions in conversations."""
import hashlib
import logging
from typing import Optional

from src.memory.core.state import ConversationState, ToolExecution

logger = logging.getLogger(__name__)


class ToolMemoryManager:
    """Manages tool execution memory within conversations.

    Tracks which tools were used, on what files, and provides
    reference resolution ("the document", "the Excel", etc.)
    """

    def register_tool_execution(
        self,
        state: ConversationState,
        tool_name: str,
        input_path: str,
        output_path: Optional[str] = None,
        summary: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> ToolExecution:
        """Register a tool execution in conversation state.

        Args:
            state: Current conversation state
            tool_name: Tool used (office, ocr, archive)
            input_path: Path to input file
            output_path: Path to output artifact (optional)
            summary: Brief summary of content (optional)
            metadata: Additional metadata (optional)

        Returns:
            Created ToolExecution record
        """
        import time

        # Generate doc_id
        current_count = len(state.get("tool_executions", []))
        doc_id = f"doc#{current_count + 1}"

        # Calculate file hash
        try:
            with open(input_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception as e:
            logger.warning(f"Could not hash file {input_path}: {e}")
            file_hash = "unknown"

        # Extract structure from metadata
        structure = "unknown"
        if metadata:
            if "pages" in metadata:
                structure = f"{metadata['pages']} pages"
            elif "sheets" in metadata:
                structure = f"{metadata['sheets']} sheets"
            elif "files" in metadata:
                structure = f"{metadata['files']} files"

        # Generate auto-summary if not provided
        if not summary:
            import os
            filename = os.path.basename(input_path)
            summary = f"{tool_name.upper()} processed: {filename}"

        # Create execution record
        execution: ToolExecution = {
            "tool": tool_name,
            "doc_id": doc_id,
            "file_path": input_path,
            "file_hash": file_hash,
            "summary": summary,
            "structure": structure,
            "timestamp": time.time(),
            "output_path": output_path,
            "metadata": metadata
        }

        logger.info(
            f"Registered tool execution: {doc_id} - {tool_name} - {summary}"
        )

        return execution

    def get_tool_reference(
        self,
        state: ConversationState,
        query: str
    ) -> Optional[ToolExecution]:
        """Resolve tool reference from natural language query.

        Supports queries like:
        - "the document"
        - "the Excel"
        - "the last PDF"
        - "doc#1"

        Args:
            state: Current conversation state
            query: Natural language reference

        Returns:
            ToolExecution if found, None otherwise
        """
        executions = state.get("tool_executions", [])
        if not executions:
            return None

        query_lower = query.lower()

        # Direct doc_id reference
        if query_lower.startswith("doc#"):
            for exec in executions:
                if exec["doc_id"] == query_lower:
                    return exec

        # "the document" / "the last document" - most recent
        if "document" in query_lower or "file" in query_lower:
            if "last" in query_lower or "latest" in query_lower or query_lower == "the document":
                return executions[-1]

        # "the Excel" / "the spreadsheet"
        if "excel" in query_lower or "spreadsheet" in query_lower or ".xlsx" in query_lower:
            for exec in reversed(executions):
                if exec["file_path"].lower().endswith((".xlsx", ".xls", ".xlsm")):
                    return exec

        # "the PDF"
        if "pdf" in query_lower:
            for exec in reversed(executions):
                if exec["file_path"].lower().endswith(".pdf"):
                    return exec

        # "the Word document" / "the DOCX"
        if "word" in query_lower or "docx" in query_lower or ".docx" in query_lower:
            for exec in reversed(executions):
                if exec["file_path"].lower().endswith((".docx", ".doc")):
                    return exec

        # "the archive" / "the ZIP"
        if "archive" in query_lower or "zip" in query_lower:
            for exec in reversed(executions):
                if exec["tool"] == "archive":
                    return exec

        # "the OCR" / "the scan"
        if "ocr" in query_lower or "scan" in query_lower:
            for exec in reversed(executions):
                if exec["tool"] == "ocr":
                    return exec

        # "the first" - first execution
        if "first" in query_lower:
            return executions[0]

        # Default: return most recent
        return executions[-1] if executions else None

    def format_tool_memory(
        self,
        state: ConversationState,
        n: int = 5
    ) -> str:
        """Format tool memory for context injection.

        Args:
            state: Current conversation state
            n: Number of recent executions to include

        Returns:
            Formatted string for LLM context
        """
        executions = state.get("tool_executions", [])
        if not executions:
            return ""

        # Get recent executions
        recent = executions[-n:] if len(executions) > n else executions

        lines = ["Tools usados en esta conversación:"]
        for exec in recent:
            lines.append(
                f"- {exec['doc_id']}: {exec['summary']} "
                f"({exec['structure']}, tool: {exec['tool']})"
            )

        return "\n".join(lines)

    def get_execution_by_id(
        self,
        state: ConversationState,
        doc_id: str
    ) -> Optional[ToolExecution]:
        """Get execution by doc_id.

        Args:
            state: Current conversation state
            doc_id: Document ID (e.g., "doc#1")

        Returns:
            ToolExecution if found, None otherwise
        """
        executions = state.get("tool_executions", [])
        for exec in executions:
            if exec["doc_id"] == doc_id:
                return exec
        return None


def create_tool_memory_manager() -> ToolMemoryManager:
    """Factory function to create tool memory manager.

    Returns:
        New ToolMemoryManager instance
    """
    return ToolMemoryManager()