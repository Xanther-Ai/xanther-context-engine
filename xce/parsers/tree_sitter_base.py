"""Tree-sitter generic base parser and node-type mapping configuration.

Provides shared tree-walking logic for all tree-sitter-based language parsers.
Language-specific parsers subclass TreeSitterBaseParser and provide a
NodeTypeMapping configuration (~50 lines of config per language).
"""

from __future__ import annotations

import logging
import os
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional

from tree_sitter import Language, Parser as TSParser

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parsers.base import BaseParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeTypeMapping:
    """Maps tree-sitter grammar node types to XCE NodeKind values.

    Each field is a tuple of tree-sitter node type strings that should
    be mapped to the corresponding NodeKind.
    """

    # Node types that represent module/package declarations
    module_types: tuple[str, ...] = ()

    # Node types that represent class declarations
    class_types: tuple[str, ...] = ()

    # Node types that represent function/method declarations
    function_types: tuple[str, ...] = ()

    # Node types that represent import statements
    import_types: tuple[str, ...] = ()

    # Node types that represent variable declarations (module/class level)
    variable_types: tuple[str, ...] = ()

    # Node types that represent function calls
    call_types: tuple[str, ...] = ("call_expression",)

    # Field name used to extract the function/class name from a node
    name_field: str = "name"

    # Field name for function parameters
    parameters_field: str = "parameters"

    # Field name for class/function body
    body_field: str = "body"

    # Node types that indicate inheritance (e.g., extends_clause)
    inheritance_types: tuple[str, ...] = ()

    # Node types for decorator/annotation patterns
    decorator_types: tuple[str, ...] = ()

    # How to detect if a function is a method (parent node types)
    method_parent_types: tuple[str, ...] = ()

    # Comment node types for docstring extraction
    comment_types: tuple[str, ...] = ("comment",)

    # Maximum file size in bytes (skip larger files)
    max_file_size: int = 1_000_000


class TreeSitterBaseParser(BaseParser):
    """Generic tree-sitter parser that uses NodeTypeMapping for language-specific behavior.

    Subclasses provide:
      - _get_language() -> Language
      - _get_mapping() -> NodeTypeMapping
      - supported_extensions() -> list[str]
      - language_name() -> str

    Optionally override:
      - _extract_name(node) -> str | None  (custom name extraction)
      - _extract_signature(node, lines) -> str | None
      - _extract_docstring(node, lines) -> str | None
    """

    @abstractmethod
    def _get_language(self) -> Language:
        """Return the tree-sitter Language object for this parser."""
        ...

    @abstractmethod
    def _get_mapping(self) -> NodeTypeMapping:
        """Return the node-type mapping configuration."""
        ...

    def parse_file(
        self, filepath: str, source: str, repo_id: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse source code using tree-sitter and return nodes and edges.

        Creates a fresh parser per call for thread-safety. Catches all
        exceptions and returns partial/empty results — never raises.
        """
        try:
            mapping = self._get_mapping()

            # Enforce file size limit
            if len(source.encode("utf-8")) > mapping.max_file_size:
                logger.warning(
                    "Skipping %s: exceeds max file size (%d bytes)", filepath, mapping.max_file_size
                )
                return [], []

            # Create a fresh parser per call (thread-safe, no shared state)
            parser = TSParser()
            parser.language = self._get_language()

            tree = parser.parse(source.encode("utf-8"))

            lines = source.splitlines()
            nodes: list[ASTNode] = []
            edges: list[ASTEdge] = []

            # Create module node for the file
            mod_name = _stem(filepath)
            mod_id = _make_id(repo_id, filepath, NodeKind.MODULE, mod_name)
            nodes.append(
                ASTNode(
                    id=mod_id,
                    kind=NodeKind.MODULE,
                    name=mod_name,
                    filepath=filepath,
                    start_line=1,
                    end_line=max(len(lines), 1),
                    source_text=source[:2000],
                    docstring=None,
                )
            )

            # Walk the tree
            self._walk(tree.root_node, repo_id, filepath, lines, mod_id, nodes, edges, mapping)

            return _deduplicate(nodes, edges)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", filepath, exc)
            return [], []

    def _walk(
        self,
        node,
        repo_id: str,
        filepath: str,
        lines: list[str],
        parent_id: str,
        nodes: list[ASTNode],
        edges: list[ASTEdge],
        mapping: NodeTypeMapping,
    ) -> None:
        """Recursively walk tree-sitter nodes and extract declarations."""
        for child in node.children:
            node_type = child.type
            kind = self._classify_node(node_type, mapping, child)

            if kind is not None:
                name = self._extract_name(child, mapping)
                if name is None:
                    # Try to get name from first named child as fallback
                    name = self._fallback_name(child, node_type)

                if name:
                    node_id = _make_id(repo_id, filepath, kind, name)
                    start_line = child.start_point[0] + 1
                    end_line = child.end_point[0] + 1
                    source_text = child.text.decode("utf-8", errors="replace") if child.text else ""

                    signature = self._extract_signature(child, lines, mapping)
                    docstring = self._extract_docstring(child, lines, mapping)

                    ast_node = ASTNode(
                        id=node_id,
                        kind=kind,
                        name=name,
                        filepath=filepath,
                        start_line=start_line,
                        end_line=end_line,
                        source_text=source_text[:2000],
                        docstring=docstring,
                        signature=signature,
                        parent_id=parent_id,
                    )
                    nodes.append(ast_node)

                    # Create CONTAINS edge from parent to this node
                    edges.append(ASTEdge(source_id=parent_id, target_id=node_id, relation="contains"))

                    # Check for inheritance
                    self._extract_inheritance_edges(child, node_id, repo_id, filepath, edges, mapping)

                    # Check for decorators
                    self._extract_decorator_edges(child, node_id, repo_id, filepath, nodes, edges, mapping)

                    # Recurse into this node's body with updated parent
                    body = child.child_by_field_name(mapping.body_field)
                    if body:
                        self._walk(body, repo_id, filepath, lines, node_id, nodes, edges, mapping)
                    else:
                        # Some languages don't use a body field; walk all children
                        self._walk(child, repo_id, filepath, lines, node_id, nodes, edges, mapping)
                else:
                    # No name extracted, recurse into children with same parent
                    self._walk(child, repo_id, filepath, lines, parent_id, nodes, edges, mapping)
            else:
                # Check for call expressions to create CALLS edges
                if node_type in mapping.call_types:
                    self._extract_call_edge(child, parent_id, repo_id, filepath, edges, mapping)

                # Check for import nodes
                if node_type in mapping.import_types:
                    self._extract_import_node(child, parent_id, repo_id, filepath, nodes, edges, mapping)

                # Recurse into non-declaration nodes
                self._walk(child, repo_id, filepath, lines, parent_id, nodes, edges, mapping)

    def _classify_node(self, node_type: str, mapping: NodeTypeMapping, node) -> Optional[NodeKind]:
        """Determine the NodeKind for a tree-sitter node type, or None if not a declaration."""
        if node_type in mapping.class_types:
            return NodeKind.CLASS
        if node_type in mapping.function_types:
            # Check if it's a method (parent is a class body)
            if node.parent and node.parent.type in mapping.method_parent_types:
                return NodeKind.METHOD
            return NodeKind.FUNCTION
        if node_type in mapping.variable_types:
            return NodeKind.VARIABLE
        return None

    def _extract_name(self, node, mapping: NodeTypeMapping) -> Optional[str]:
        """Extract the name from a declaration node using the configured name field."""
        name_node = node.child_by_field_name(mapping.name_field)
        if name_node and name_node.text:
            return name_node.text.decode("utf-8", errors="replace")
        return None

    def _fallback_name(self, node, node_type: str) -> Optional[str]:
        """Try to extract a name from the first identifier child."""
        for child in node.children:
            if child.type == "identifier" or child.type == "type_identifier":
                if child.text:
                    return child.text.decode("utf-8", errors="replace")
        return None

    def _extract_signature(self, node, lines: list[str], mapping: NodeTypeMapping) -> Optional[str]:
        """Extract the signature (first line) of a declaration."""
        start_line = node.start_point[0]
        if start_line < len(lines):
            return lines[start_line].strip()
        return None

    def _extract_docstring(self, node, lines: list[str], mapping: NodeTypeMapping) -> Optional[str]:
        """Extract a docstring/comment immediately preceding or following a declaration."""
        # Look for a comment node immediately before this node
        if node.prev_sibling and node.prev_sibling.type in mapping.comment_types:
            comment_text = node.prev_sibling.text
            if comment_text:
                return comment_text.decode("utf-8", errors="replace").strip()
        # Look for a comment as first child of body
        body = node.child_by_field_name(mapping.body_field)
        if body:
            for child in body.children:
                if child.type in mapping.comment_types:
                    if child.text:
                        return child.text.decode("utf-8", errors="replace").strip()
                    break
                # Skip whitespace-only nodes
                if child.is_named:
                    break
        return None

    def _extract_inheritance_edges(
        self,
        node,
        node_id: str,
        repo_id: str,
        filepath: str,
        edges: list[ASTEdge],
        mapping: NodeTypeMapping,
    ) -> None:
        """Extract inheritance/extends edges from a class declaration."""
        for child in node.children:
            if child.type in mapping.inheritance_types:
                # Extract the parent class name(s)
                for identifier in child.children:
                    if identifier.type in ("identifier", "type_identifier") and identifier.text:
                        parent_name = identifier.text.decode("utf-8", errors="replace")
                        parent_class_id = _make_id(repo_id, filepath, NodeKind.CLASS, parent_name)
                        edges.append(ASTEdge(source_id=node_id, target_id=parent_class_id, relation="inherits"))

    def _extract_decorator_edges(
        self,
        node,
        node_id: str,
        repo_id: str,
        filepath: str,
        nodes: list[ASTNode],
        edges: list[ASTEdge],
        mapping: NodeTypeMapping,
    ) -> None:
        """Extract decorator/annotation edges."""
        if not mapping.decorator_types:
            return
        # Look for decorator nodes as previous siblings or children
        prev = node.prev_sibling
        while prev and prev.type in mapping.decorator_types:
            dec_name = None
            for child in prev.children:
                if child.type in ("identifier", "attribute") and child.text:
                    dec_name = child.text.decode("utf-8", errors="replace")
                    break
            if dec_name:
                dec_id = _make_id(repo_id, filepath, NodeKind.DECORATOR, dec_name)
                nodes.append(
                    ASTNode(
                        id=dec_id,
                        kind=NodeKind.DECORATOR,
                        name=dec_name,
                        filepath=filepath,
                        start_line=prev.start_point[0] + 1,
                        end_line=prev.end_point[0] + 1,
                        source_text=prev.text.decode("utf-8", errors="replace") if prev.text else "",
                    )
                )
                edges.append(ASTEdge(source_id=dec_id, target_id=node_id, relation="decorates"))
            prev = prev.prev_sibling

    def _extract_call_edge(
        self,
        node,
        caller_id: str,
        repo_id: str,
        filepath: str,
        edges: list[ASTEdge],
        mapping: NodeTypeMapping,
    ) -> None:
        """Extract a CALLS edge from a call expression."""
        # Try to get the function name from the call
        func_node = node.child_by_field_name("function")
        if func_node is None:
            # Some grammars use different field names
            for child in node.children:
                if child.type in ("identifier", "member_expression", "field_expression"):
                    func_node = child
                    break

        if func_node and func_node.text:
            callee_name = func_node.text.decode("utf-8", errors="replace")
            # Use a simplified callee ID (may not resolve to actual node)
            callee_id = _make_id(repo_id, filepath, NodeKind.FUNCTION, callee_name)
            edges.append(ASTEdge(source_id=caller_id, target_id=callee_id, relation="calls"))

    def _extract_import_node(
        self,
        node,
        parent_id: str,
        repo_id: str,
        filepath: str,
        nodes: list[ASTNode],
        edges: list[ASTEdge],
        mapping: NodeTypeMapping,
    ) -> None:
        """Extract an IMPORT node from an import statement."""
        import_text = node.text.decode("utf-8", errors="replace") if node.text else ""
        # Try to extract a meaningful name from the import
        import_name = self._get_import_name(node, import_text)
        if import_name:
            import_id = _make_id(repo_id, filepath, NodeKind.IMPORT, import_name)
            nodes.append(
                ASTNode(
                    id=import_id,
                    kind=NodeKind.IMPORT,
                    name=import_name,
                    filepath=filepath,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=import_text[:500],
                    parent_id=parent_id,
                )
            )
            edges.append(ASTEdge(source_id=parent_id, target_id=import_id, relation="contains"))
            edges.append(ASTEdge(source_id=import_id, target_id=import_id, relation="imports"))

    def _get_import_name(self, node, import_text: str) -> Optional[str]:
        """Extract a meaningful name from an import node."""
        # Try to find a string or identifier child that represents the module path
        for child in node.children:
            if child.type in ("identifier", "scoped_identifier", "dotted_name", "string"):
                if child.text:
                    name = child.text.decode("utf-8", errors="replace").strip("\"'")
                    if name:
                        return name
        # Fallback: use the first line of import text, cleaned up
        if import_text:
            first_line = import_text.split("\n")[0].strip()
            # Remove common prefixes
            for prefix in ("import ", "from ", "use ", "require ", "#include ", "using "):
                if first_line.lower().startswith(prefix):
                    first_line = first_line[len(prefix):].strip().rstrip(";")
                    break
            if first_line:
                return first_line[:100]
        return None


def _stem(filepath: str) -> str:
    """Extract the file stem (name without extension) from a filepath."""
    return os.path.splitext(os.path.basename(filepath))[0]


def _make_id(repo_id: str, filepath: str, kind: NodeKind, name: str) -> str:
    """Create a canonical ASTNode ID in the format {repo_id}:{filepath}:{kind}:{name}."""
    return f"{repo_id}:{filepath}:{kind.value}:{name}"


def _deduplicate(
    nodes: list[ASTNode], edges: list[ASTEdge]
) -> tuple[list[ASTNode], list[ASTEdge]]:
    """Remove duplicate nodes and edges."""
    seen_node_ids: set[str] = set()
    unique_nodes: list[ASTNode] = []
    for node in nodes:
        if node.id not in seen_node_ids:
            seen_node_ids.add(node.id)
            unique_nodes.append(node)

    seen_edges: set[tuple[str, str, str]] = set()
    unique_edges: list[ASTEdge] = []
    for edge in edges:
        key = (edge.source_id, edge.target_id, edge.relation)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(edge)

    return unique_nodes, unique_edges
