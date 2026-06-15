"""Tool memory manager for tracking tool executions in conversations."""
import hashlib
import logging
from typing import Optional

from src.workflows.memory.core.state import ConversationState, ToolExecution

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
        file_hash = self._calculate_file_hash(input_path)

        # Extract structure from metadata
        structure = self._extract_structure_from_metadata(metadata)

        # Generate auto-summary if not provided
        summary = summary or self._generate_auto_summary(tool_name, input_path)

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
        
    def _calculate_file_hash(self, input_path: str) -> str:
        """Calculate file hash for the given input path."""
        try:
            with open(input_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception as e:
            logger.warning(f"Could not hash file {input_path}: {e}")
            return "unknown"
            
    def _extract_structure_from_metadata(self, metadata: Optional[dict]) -> str:
        """Extract structure information from metadata."""
        if not metadata:
            return "unknown"
            
        structure_mappings = {
            "pages": lambda m: f"{m['pages']} pages",
            "sheets": lambda m: f"{m['sheets']} sheets", 
            "files": lambda m: f"{m['files']} files"
        }
        
        for key, formatter in structure_mappings.items():
            if key in metadata:
                return formatter(metadata)
                
        return "unknown"
        
    def _generate_auto_summary(self, tool_name: str, input_path: str) -> str:
        """Generate automatic summary for tool execution."""
        import os
        filename = os.path.basename(input_path)
        return f"{tool_name.upper()} processed: {filename}"

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
            return self._find_execution_by_doc_id(executions, query_lower)

        # Use lookup table for different query types
        query_handlers = {
            "document": lambda: self._handle_document_reference(executions, query_lower),
            "file": lambda: self._handle_document_reference(executions, query_lower),
            "excel": lambda: self._find_by_file_extension(executions, [".xlsx", ".xls", ".xlsm"]),
            "spreadsheet": lambda: self._find_by_file_extension(executions, [".xlsx", ".xls", ".xlsm"]),
            "pdf": lambda: self._find_by_file_extension(executions, [".pdf"]),
            "word": lambda: self._find_by_file_extension(executions, [".docx", ".doc"]),
            "docx": lambda: self._find_by_file_extension(executions, [".docx", ".doc"]),
            "archive": lambda: self._find_by_tool_type(executions, "archive"),
            "zip": lambda: self._find_by_tool_type(executions, "archive"),
            "ocr": lambda: self._find_by_tool_type(executions, "ocr"),
            "scan": lambda: self._find_by_tool_type(executions, "ocr"),
            "first": lambda: executions[0] if executions else None,
        }
        
        # Check for specific query types
        for key, handler in query_handlers.items():
            if key in query_lower:
                result = handler()
                if result:
                    return result

        # Default: return most recent
        return executions[-1] if executions else None
        
    def _find_execution_by_doc_id(self, executions: list, doc_id: str) -> Optional[ToolExecution]:
        """Find execution by document ID."""
        for exec in executions:
            if exec["doc_id"] == doc_id:
                return exec
        return None
        
    def _handle_document_reference(self, executions: list, query: str) -> Optional[ToolExecution]:
        """Handle document/file references."""
        if "last" in query or "latest" in query or query == "the document":
            return executions[-1] if executions else None
        return None
        
    def _find_by_file_extension(self, executions: list, extensions: list) -> Optional[ToolExecution]:
        """Find execution by file extension."""
        for exec in reversed(executions):
            if any(exec["file_path"].lower().endswith(ext) for ext in extensions):
                return exec
        return None
        
    def _find_by_tool_type(self, executions: list, tool_type: str) -> Optional[ToolExecution]:
        """Find execution by tool type."""
        for exec in reversed(executions):
            if exec["tool"] == tool_type:
                return exec
        return None

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

        lines = ["Tools used in this conversation:"]
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
