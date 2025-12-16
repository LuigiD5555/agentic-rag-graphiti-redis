"""Optimized path tree structure for fast directory lookup and traversal."""

from typing import Optional, Set, Dict
from dataclasses import dataclass, field


@dataclass
class PathNode:
    """
    Node in the path tree (Trie).

    Each node represents a directory component in a path hierarchy.
    This allows O(k) lookups where k is the path depth.
    """
    name: str
    children: Dict[str, 'PathNode'] = field(default_factory=dict)
    is_excluded: bool = False
    is_cached: bool = False
    file_count: int = 0

    def add_child(self, name: str) -> 'PathNode':
        """Add a child node if it doesn't exist and return it."""
        if name not in self.children:
            self.children[name] = PathNode(name=name)
        return self.children[name]

    def get_child(self, name: str) -> Optional['PathNode']:
        """Get a child node by name."""
        return self.children.get(name)

    def mark_excluded(self) -> None:
        """Mark this path and all descendants as excluded."""
        self.is_excluded = True
        # Recursively mark all children
        for child in self.children.values():
            child.mark_excluded()


class PathTree:
    """
    Trie-based tree structure for efficient path operations.

    Benefits:
    - O(k) lookup time where k is path depth (vs O(n) linear search)
    - Memory efficient - shared prefixes stored once
    - Fast exclusion checks without regex on every path
    - Easy to mark entire subtrees as visited/excluded
    """

    def __init__(self):
        self.root = PathNode(name="")
        self._visited_paths: Set[str] = set()

    def add_path(self, path: str, is_excluded: bool = False) -> PathNode:
        """
        Add a path to the tree.

        Args:
            path: Path to add (can be absolute or relative)
            is_excluded: Whether this path should be marked as excluded

        Returns:
            The leaf node representing this path
        """
        parts = self._normalize_path(path)
        current = self.root

        for part in parts:
            current = current.add_child(part)

        if is_excluded:
            current.mark_excluded()

        return current

    def find_node(self, path: str) -> Optional[PathNode]:
        """
        Find a node in the tree by path.

        Args:
            path: Path to find

        Returns:
            The node if found, None otherwise
        """
        parts = self._normalize_path(path)
        current = self.root

        for part in parts:
            current = current.get_child(part)
            if current is None:
                return None

        return current

    def is_path_excluded(self, path: str) -> bool:
        """
        Check if a path or any of its ancestors is excluded.

        This is O(k) where k is the depth of the path.

        Args:
            path: Path to check

        Returns:
            True if the path or any ancestor is excluded
        """
        parts = self._normalize_path(path)
        current = self.root

        for part in parts:
            current = current.get_child(part)
            if current is None:
                return False
            if current.is_excluded:
                return True

        return False

    def mark_visited(self, path: str) -> None:
        """
        Mark a path as visited to prevent re-scanning.

        Args:
            path: Path to mark as visited
        """
        self._visited_paths.add(path)
        node = self.find_node(path)
        if node:
            node.is_cached = True

    def is_visited(self, path: str) -> bool:
        """
        Check if a path has been visited.

        Args:
            path: Path to check

        Returns:
            True if the path has been visited
        """
        return path in self._visited_paths

    def get_unvisited_children(self, path: str) -> list[str]:
        """
        Get list of child paths that haven't been visited yet.

        Args:
            path: Parent path to check

        Returns:
            List of unvisited child path names
        """
        node = self.find_node(path)
        if not node:
            return []

        unvisited = []
        base = path.rstrip('/') if path else ''

        for child_name, child_node in node.children.items():
            child_path = f"{base}/{child_name}" if base else child_name
            if not self.is_visited(child_path) and not child_node.is_excluded:
                unvisited.append(child_path)

        return unvisited

    def clear_visited(self) -> None:
        """Clear all visited path tracking."""
        self._visited_paths.clear()
        self._clear_cached_flag(self.root)

    def _clear_cached_flag(self, node: PathNode) -> None:
        """Recursively clear cached flags."""
        node.is_cached = False
        for child in node.children.values():
            self._clear_cached_flag(child)

    @staticmethod
    def _normalize_path(path: str) -> list[str]:
        """
        Normalize a path into components for tree traversal.

        Args:
            path: Path to normalize

        Returns:
            List of path components
        """
        if not path:
            return []

        # Remove leading/trailing slashes and split
        path = path.strip('/')
        if not path:
            return []

        return path.split('/')

    def get_stats(self) -> dict:
        """Get statistics about the tree."""
        total_nodes = self._count_nodes(self.root)
        excluded_nodes = self._count_excluded(self.root)

        return {
            'total_nodes': total_nodes,
            'excluded_nodes': excluded_nodes,
            'visited_paths': len(self._visited_paths),
            'memory_savings': self._estimate_memory_savings()
        }

    def _count_nodes(self, node: PathNode) -> int:
        """Recursively count all nodes."""
        count = 1
        for child in node.children.values():
            count += self._count_nodes(child)
        return count

    def _count_excluded(self, node: PathNode) -> int:
        """Recursively count excluded nodes."""
        count = 1 if node.is_excluded else 0
        for child in node.children.values():
            count += self._count_excluded(child)
        return count

    def _estimate_memory_savings(self) -> str:
        """
        Estimate memory savings from path prefix sharing.

        Returns:
            Human-readable string describing savings
        """
        if not self._visited_paths:
            return "0 paths tracked"

        # Calculate total characters if stored separately
        total_chars = sum(len(p) for p in self._visited_paths)
        # Estimate shared prefix savings (rough estimate)
        nodes = self._count_nodes(self.root)
        avg_savings = max(0, total_chars - (nodes * 10))  # Rough estimate

        return f"~{avg_savings} chars saved via prefix sharing"


__all__ = ["PathTree", "PathNode"]
