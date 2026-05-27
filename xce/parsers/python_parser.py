"""Python parser using the stdlib ast module.

Implements the BaseParser interface while preserving identical behavior
to the original xce/parser.py implementation. Uses Python's built-in
ast module (NOT tree-sitter) for superior semantic accuracy.
"""

from __future__ import annotations

import ast
import logging
import os
import textwrap
from pathlib import Path
from typing import Optional

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parsers.base import BaseParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def make_node_id(repo_id: str, filepath: str, kind: NodeKind, name: str) -> str:
    """Build a deterministic node ID: ``{repo_id}:{filepath}:{kind}:{name}``."""
    return f"{repo_id}:{filepath}:{kind.value}:{name}"


# ---------------------------------------------------------------------------
# AST visitor helpers
# ---------------------------------------------------------------------------


def _get_source_segment(source_lines: list[str], node: ast.AST) -> str:
    """Return the source text for an AST node."""
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    if end is None:
        end = start + 1
    return "\n".join(source_lines[start:end])


def _get_docstring(node: ast.AST) -> Optional[str]:
    """Extract the docstring from a class/function/module node."""
    return ast.get_docstring(node)


def _get_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a human-readable signature string for a function/method."""
    args = node.args
    parts: list[str] = []

    # positional-only
    for a in args.posonlyargs:
        parts.append(a.arg)
    if args.posonlyargs:
        parts.append("/")

    # regular positional
    n_defaults = len(args.defaults)
    n_args = len(args.args)
    for i, a in enumerate(args.args):
        default_idx = i - (n_args - n_defaults)
        if default_idx >= 0:
            parts.append(f"{a.arg}=...")
        else:
            parts.append(a.arg)

    # *args
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")

    # keyword-only
    for i, a in enumerate(args.kwonlyargs):
        if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
            parts.append(f"{a.arg}=...")
        else:
            parts.append(a.arg)

    # **kwargs
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return_ann = ""
    if node.returns:
        try:
            return_ann = f" -> {ast.unparse(node.returns)}"
        except Exception:
            return_ann = ""
    return f"{prefix} {node.name}({', '.join(parts)}){return_ann}"


# ---------------------------------------------------------------------------
# Name resolution helper
# ---------------------------------------------------------------------------


def _resolve_name(node: ast.AST) -> Optional[str]:
    """Try to extract a simple name from an AST expression node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _resolve_name(node.func)
    return None


# ---------------------------------------------------------------------------
# Core visitor
# ---------------------------------------------------------------------------


class _FileVisitor(ast.NodeVisitor):
    """Walk a single file's AST and collect nodes + intra-file edges."""

    def __init__(
        self,
        repo_id: str,
        filepath: str,
        source_lines: list[str],
    ) -> None:
        self.repo_id = repo_id
        self.filepath = filepath
        self.source_lines = source_lines
        self.nodes: list[ASTNode] = []
        self.edges: list[ASTEdge] = []
        # Stack of (node_id, ast_node) for tracking parent context
        self._parent_stack: list[tuple[str, ast.AST]] = []

    # -- helpers ----------------------------------------------------------

    def _make_id(self, kind: NodeKind, name: str) -> str:
        return make_node_id(self.repo_id, self.filepath, kind, name)

    def _current_parent_id(self) -> Optional[str]:
        return self._parent_stack[-1][0] if self._parent_stack else None

    def _add_node(self, node: ASTNode) -> None:
        self.nodes.append(node)
        parent_id = self._current_parent_id()
        if parent_id is not None:
            self.edges.append(ASTEdge(source_id=parent_id, target_id=node.id, relation="contains"))

    # -- visitors ---------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:  # noqa: N802
        mod_name = Path(self.filepath).stem
        nid = self._make_id(NodeKind.MODULE, mod_name)
        ast_node = ASTNode(
            id=nid,
            kind=NodeKind.MODULE,
            name=mod_name,
            filepath=self.filepath,
            start_line=1,
            end_line=len(self.source_lines),
            source_text="\n".join(self.source_lines),
            docstring=_get_docstring(node),
        )
        self.nodes.append(ast_node)
        self._parent_stack.append((nid, node))
        self.generic_visit(node)
        self._parent_stack.pop()

    # -- classes ----------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        nid = self._make_id(NodeKind.CLASS, node.name)
        ast_node = ASTNode(
            id=nid,
            kind=NodeKind.CLASS,
            name=node.name,
            filepath=self.filepath,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            source_text=_get_source_segment(self.source_lines, node),
            docstring=_get_docstring(node),
            parent_id=self._current_parent_id(),
        )
        self._add_node(ast_node)

        # INHERITS edges
        for base in node.bases:
            base_name = _resolve_name(base)
            if base_name:
                target_id = self._make_id(NodeKind.CLASS, base_name)
                self.edges.append(ASTEdge(source_id=nid, target_id=target_id, relation="inherits"))

        # DECORATES edges
        for dec in node.decorator_list:
            dec_name = _resolve_name(dec)
            if dec_name:
                dec_id = self._make_id(NodeKind.DECORATOR, dec_name)
                dec_node = ASTNode(
                    id=dec_id,
                    kind=NodeKind.DECORATOR,
                    name=dec_name,
                    filepath=self.filepath,
                    start_line=dec.lineno,
                    end_line=dec.end_lineno or dec.lineno,
                    source_text=_get_source_segment(self.source_lines, dec),
                    parent_id=self._current_parent_id(),
                )
                self._add_node(dec_node)
                self.edges.append(ASTEdge(source_id=dec_id, target_id=nid, relation="decorates"))

        self._parent_stack.append((nid, node))
        self.generic_visit(node)
        self._parent_stack.pop()

    # -- functions / methods ----------------------------------------------

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Determine if this is a method (inside a class) or a function
        is_method = any(isinstance(p, ast.ClassDef) for _, p in self._parent_stack)
        kind = NodeKind.METHOD if is_method else NodeKind.FUNCTION
        nid = self._make_id(kind, node.name)

        ast_node = ASTNode(
            id=nid,
            kind=kind,
            name=node.name,
            filepath=self.filepath,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            source_text=_get_source_segment(self.source_lines, node),
            docstring=_get_docstring(node),
            signature=_get_signature(node),
            parent_id=self._current_parent_id(),
        )
        self._add_node(ast_node)

        # DECORATES edges
        for dec in node.decorator_list:
            dec_name = _resolve_name(dec)
            if dec_name:
                dec_id = self._make_id(NodeKind.DECORATOR, dec_name)
                dec_node = ASTNode(
                    id=dec_id,
                    kind=NodeKind.DECORATOR,
                    name=dec_name,
                    filepath=self.filepath,
                    start_line=dec.lineno,
                    end_line=dec.end_lineno or dec.lineno,
                    source_text=_get_source_segment(self.source_lines, dec),
                    parent_id=self._current_parent_id(),
                )
                self._add_node(dec_node)
                self.edges.append(ASTEdge(source_id=dec_id, target_id=nid, relation="decorates"))

        # CALLS edges — scan the function body for Call nodes
        self._parent_stack.append((nid, node))
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                callee_name = _resolve_name(child.func)
                if callee_name:
                    target_id = self._make_id(NodeKind.FUNCTION, callee_name)
                    # Avoid self-referential edges
                    if target_id != nid:
                        self.edges.append(ASTEdge(source_id=nid, target_id=target_id, relation="calls"))

        # Visit children (nested functions/classes)
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        self._parent_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_func(node)

    # -- imports ----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            name = alias.asname or alias.name
            nid = self._make_id(NodeKind.IMPORT, name)
            ast_node = ASTNode(
                id=nid,
                kind=NodeKind.IMPORT,
                name=name,
                filepath=self.filepath,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                source_text=_get_source_segment(self.source_lines, node),
                parent_id=self._current_parent_id(),
            )
            self._add_node(ast_node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for alias in (node.names or []):
            name = alias.asname or alias.name
            full_name = f"{module}.{alias.name}" if module else alias.name
            nid = self._make_id(NodeKind.IMPORT, name)
            ast_node = ASTNode(
                id=nid,
                kind=NodeKind.IMPORT,
                name=name,
                filepath=self.filepath,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                source_text=_get_source_segment(self.source_lines, node),
                parent_id=self._current_parent_id(),
            )
            # Store the full import path in docstring field for cross-file resolution
            ast_node.docstring = full_name
            self._add_node(ast_node)

    # -- variables (module-level assignments) -----------------------------

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        # Only capture module-level or class-level variables
        if len(self._parent_stack) > 0:
            parent_kind = None
            for pid, pnode in reversed(self._parent_stack):
                if isinstance(pnode, ast.Module):
                    parent_kind = "module"
                    break
                if isinstance(pnode, ast.ClassDef):
                    parent_kind = "class"
                    break
            if parent_kind in ("module", "class"):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        nid = self._make_id(NodeKind.VARIABLE, target.id)
                        ast_node = ASTNode(
                            id=nid,
                            kind=NodeKind.VARIABLE,
                            name=target.id,
                            filepath=self.filepath,
                            start_line=node.lineno,
                            end_line=node.end_lineno or node.lineno,
                            source_text=_get_source_segment(self.source_lines, node),
                            parent_id=self._current_parent_id(),
                        )
                        self._add_node(ast_node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if len(self._parent_stack) > 0:
            parent_kind = None
            for pid, pnode in reversed(self._parent_stack):
                if isinstance(pnode, ast.Module):
                    parent_kind = "module"
                    break
                if isinstance(pnode, ast.ClassDef):
                    parent_kind = "class"
                    break
            if parent_kind in ("module", "class") and isinstance(node.target, ast.Name):
                nid = self._make_id(NodeKind.VARIABLE, node.target.id)
                ast_node = ASTNode(
                    id=nid,
                    kind=NodeKind.VARIABLE,
                    name=node.target.id,
                    filepath=self.filepath,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    source_text=_get_source_segment(self.source_lines, node),
                    parent_id=self._current_parent_id(),
                )
                self._add_node(ast_node)


# ---------------------------------------------------------------------------
# PythonParser (BaseParser implementation)
# ---------------------------------------------------------------------------


class PythonParser(BaseParser):
    """Python parser using the stdlib ast module.

    Preserves identical behavior to the original xce/parser.py implementation.
    Uses Python's built-in ast module (NOT tree-sitter) for superior accuracy.
    """

    def supported_extensions(self) -> list[str]:
        return [".py", ".pyi"]

    def language_name(self) -> str:
        return "python"

    def parse_file(
        self, filepath: str, source: str, repo_id: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse a single Python file and return (nodes, edges).

        If the file has a syntax error the method returns empty lists and
        logs a warning (graceful skip).
        """
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError as exc:
            logger.warning("Skipping %s due to syntax error: %s", filepath, exc)
            return [], []

        source_lines = source.splitlines()
        visitor = _FileVisitor(repo_id, filepath, source_lines)
        visitor.visit(tree)

        # Deduplicate nodes by id (keep first occurrence)
        seen_ids: set[str] = set()
        unique_nodes: list[ASTNode] = []
        for n in visitor.nodes:
            if n.id not in seen_ids:
                seen_ids.add(n.id)
                unique_nodes.append(n)

        # Deduplicate edges and remove self-referential / dangling
        seen_edges: set[tuple[str, str, str]] = set()
        unique_edges: list[ASTEdge] = []
        for e in visitor.edges:
            key = (e.source_id, e.target_id, e.relation)
            if key not in seen_edges and e.source_id != e.target_id:
                seen_edges.add(key)
                unique_edges.append(e)

        return unique_nodes, unique_edges
