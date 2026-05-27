"""AST parser for Python source files — backward-compatible shim.

This module preserves the original public API (ASTParser, parse_repository,
resolve_cross_file_imports, _discover_py_files) while delegating to the
refactored PythonParser in xce/parsers/python_parser.py.

Existing callers can continue importing from this module unchanged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parsers.python_parser import (
    PythonParser,
    make_node_id,
    _FileVisitor,
    _get_docstring,
    _get_signature,
    _get_source_segment,
    _resolve_name,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ASTParser  (public API — backward-compatible shim)
# ---------------------------------------------------------------------------


class ASTParser:
    """Parse Python source files into AST nodes and edges.

    This class delegates to PythonParser internally while preserving
    the original public API for backward compatibility.
    """

    def __init__(self, repo_id: str = "default") -> None:
        self.repo_id = repo_id
        self._parser = PythonParser()

    def parse_file(
        self, filepath: str, source: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse a single Python file and return (nodes, edges).

        If the file has a syntax error the method returns empty lists and
        logs a warning (graceful skip per requirement 8.3).
        """
        return self._parser.parse_file(filepath, source, self.repo_id)

    def parse_repository(
        self, repo_path: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Discover all ``.py`` files under *repo_path*, parse each, and
        return the aggregated nodes and edges (including cross-file imports).
        """
        all_nodes: list[ASTNode] = []
        all_edges: list[ASTEdge] = []

        py_files = _discover_py_files(repo_path)
        for abs_path in py_files:
            rel_path = os.path.relpath(abs_path, repo_path)
            try:
                source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Cannot read %s: %s", abs_path, exc)
                continue
            nodes, edges = self.parse_file(rel_path, source)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        # Cross-file import resolution
        cross_edges = resolve_cross_file_imports(all_nodes)
        all_edges.extend(cross_edges)

        return all_nodes, all_edges


# ---------------------------------------------------------------------------
# Cross-file import resolution
# ---------------------------------------------------------------------------


def resolve_cross_file_imports(nodes: list[ASTNode]) -> list[ASTEdge]:
    """Resolve import nodes to their target definitions across files.

    For each IMPORT node whose ``docstring`` field stores the full import
    path (e.g. ``mypackage.module.ClassName``), look for a matching
    definition node (CLASS, FUNCTION, METHOD, VARIABLE) by name.

    Returns a list of ``ASTEdge`` with ``relation="imports"``.
    """
    # Build lookup: name -> list of node ids (for non-import definitions)
    name_to_ids: dict[str, list[str]] = {}
    for n in nodes:
        if n.kind not in (NodeKind.IMPORT, NodeKind.MODULE, NodeKind.DECORATOR):
            name_to_ids.setdefault(n.name, []).append(n.id)

    edges: list[ASTEdge] = []
    seen: set[tuple[str, str]] = set()
    for n in nodes:
        if n.kind != NodeKind.IMPORT:
            continue
        # The import target name is stored in docstring (full path) or just name
        target_name = n.name
        if n.docstring:
            # e.g. "os.path.join" -> "join"
            target_name = n.docstring.rsplit(".", 1)[-1]

        for target_id in name_to_ids.get(target_name, []):
            if target_id == n.id:
                continue
            key = (n.id, target_id)
            if key not in seen:
                seen.add(key)
                edges.append(ASTEdge(source_id=n.id, target_id=target_id, relation="imports"))

    return edges


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _discover_py_files(repo_path: str) -> list[str]:
    """Recursively find all ``.py`` files under *repo_path*."""
    result: list[str] = []
    for root, _dirs, files in os.walk(repo_path):
        # Skip hidden directories and common non-source dirs
        _dirs[:] = [d for d in _dirs if not d.startswith(".") and d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                result.append(os.path.join(root, f))
    return result
