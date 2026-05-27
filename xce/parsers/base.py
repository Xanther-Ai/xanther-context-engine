"""Abstract base class for all language parsers.

Defines the contract that every parser must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from xce.models import ASTEdge, ASTNode


class BaseParser(ABC):
    """Abstract interface for all language parsers."""

    @abstractmethod
    def parse_file(
        self, filepath: str, source: str, repo_id: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse source code and return extracted nodes and edges.

        Args:
            filepath: Relative path of the file within the repository.
            source: Full source text of the file.
            repo_id: Repository identifier for node ID generation.

        Returns:
            Tuple of (nodes, edges). On error, returns partial results
            or empty lists — never raises.
        """
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return file extensions this parser handles (e.g., ['.py', '.pyi'])."""
        ...

    @abstractmethod
    def language_name(self) -> str:
        """Return the human-readable language name (e.g., 'python')."""
        ...
