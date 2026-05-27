"""TypeScript/JavaScript parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for TypeScript and
JavaScript. Handles .ts, .tsx, .js, and .jsx files by selecting the
appropriate tree-sitter language grammar based on file extension.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import tree_sitter_typescript as ts_typescript
import tree_sitter_javascript as ts_javascript
from tree_sitter import Language, Parser as TSParser

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parsers.base import BaseParser
from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

logger = logging.getLogger(__name__)

# Initialize languages
_TS_LANGUAGE = Language(ts_typescript.language_typescript())
_TSX_LANGUAGE = Language(ts_typescript.language_tsx())
_JS_LANGUAGE = Language(ts_javascript.language())

# Extension to language mapping
_EXT_LANGUAGE = {
    ".ts": _TS_LANGUAGE,
    ".tsx": _TSX_LANGUAGE,
    ".js": _JS_LANGUAGE,
    ".jsx": _JS_LANGUAGE,
}

# TypeScript/JavaScript node type mapping
_TS_MAPPING = NodeTypeMapping(
    class_types=("class_declaration",),
    function_types=(
        "function_declaration",
        "method_definition",
        "arrow_function",
    ),
    import_types=("import_statement",),
    variable_types=("lexical_declaration",),
    call_types=("call_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("extends_clause",),
    decorator_types=("decorator",),
    method_parent_types=("class_body",),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class TypeScriptParser(TreeSitterBaseParser):
    """TypeScript/JavaScript parser via tree-sitter.

    Selects the correct tree-sitter language (TypeScript, TSX, or JavaScript)
    based on the file extension. All variants share the same NodeTypeMapping.
    """

    def supported_extensions(self) -> list[str]:
        return [".ts", ".tsx", ".js", ".jsx"]

    def language_name(self) -> str:
        return "typescript"

    def _get_language(self) -> Language:
        """Return the default TypeScript language.

        Note: parse_file overrides this to select the correct language
        based on file extension.
        """
        return _TS_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _TS_MAPPING

    def parse_file(
        self, filepath: str, source: str, repo_id: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse a TypeScript/JavaScript file, selecting the correct grammar.

        Overrides the base class to dispatch to the appropriate tree-sitter
        language based on file extension (.ts, .tsx, .js, .jsx).
        """
        try:
            mapping = self._get_mapping()

            # Enforce file size limit
            if len(source.encode("utf-8")) > mapping.max_file_size:
                logger.warning(
                    "Skipping %s: exceeds max file size (%d bytes)",
                    filepath,
                    mapping.max_file_size,
                )
                return [], []

            # Select language based on extension
            ext = os.path.splitext(filepath)[1].lower()
            language = _EXT_LANGUAGE.get(ext)
            if language is None:
                logger.warning("Unsupported extension for TypeScript parser: %s", ext)
                return [], []

            # Create a fresh parser per call (thread-safe, no shared state)
            parser = TSParser()
            parser.language = language

            tree = parser.parse(source.encode("utf-8"))

            lines = source.splitlines()
            nodes: list[ASTNode] = []
            edges: list[ASTEdge] = []

            # Create module node for the file
            mod_name = os.path.splitext(os.path.basename(filepath))[0]
            mod_id = f"{repo_id}:{filepath}:{NodeKind.MODULE.value}:{mod_name}"
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

            # Walk the tree — handle export wrappers at top level
            self._walk_ts(tree.root_node, repo_id, filepath, lines, mod_id, nodes, edges, mapping)

            return self._deduplicate(nodes, edges)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", filepath, exc)
            return [], []

    def _walk_ts(
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
        """Walk tree-sitter nodes, handling TypeScript-specific patterns.

        Unwraps export_statement wrappers and delegates to the base _walk logic.
        """
        for child in node.children:
            node_type = child.type

            # Unwrap export statements to find the actual declaration inside
            if node_type == "export_statement":
                self._walk_ts(child, repo_id, filepath, lines, parent_id, nodes, edges, mapping)
                continue

            kind = self._classify_node(node_type, mapping, child)

            if kind is not None:
                # Special handling for lexical_declaration (arrow functions)
                if node_type == "lexical_declaration":
                    self._extract_lexical_declarations(
                        child, repo_id, filepath, lines, parent_id, nodes, edges, mapping
                    )
                    continue

                name = self._extract_name(child, mapping)
                if name is None:
                    name = self._fallback_name(child, node_type)

                if name:
                    node_id = f"{repo_id}:{filepath}:{kind.value}:{name}"
                    start_line = child.start_point[0] + 1
                    end_line = child.end_point[0] + 1
                    source_text = (
                        child.text.decode("utf-8", errors="replace") if child.text else ""
                    )

                    signature = self._extract_ts_signature(child, lines, kind, name)
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
                    edges.append(
                        ASTEdge(source_id=parent_id, target_id=node_id, relation="contains")
                    )

                    # Extract inheritance edges for classes
                    if kind == NodeKind.CLASS:
                        self._extract_inheritance_edges(
                            child, node_id, repo_id, filepath, edges, mapping
                        )

                    # Recurse into body for nested declarations
                    body = child.child_by_field_name(mapping.body_field)
                    if body:
                        self._walk_ts(
                            body, repo_id, filepath, lines, node_id, nodes, edges, mapping
                        )
                    else:
                        self._walk_ts(
                            child, repo_id, filepath, lines, node_id, nodes, edges, mapping
                        )
                else:
                    self._walk_ts(
                        child, repo_id, filepath, lines, parent_id, nodes, edges, mapping
                    )
            else:
                # Handle imports
                if node_type in mapping.import_types:
                    self._extract_ts_import(
                        child, parent_id, repo_id, filepath, nodes, edges
                    )
                # Handle call expressions
                elif node_type in mapping.call_types:
                    self._extract_call_edge(child, parent_id, repo_id, filepath, edges, mapping)

                # Recurse into non-declaration nodes
                self._walk_ts(child, repo_id, filepath, lines, parent_id, nodes, edges, mapping)

    def _extract_lexical_declarations(
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
        """Extract arrow functions from const/let/var declarations."""
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if not name_node or not value_node:
                    continue
                if value_node.type != "arrow_function":
                    # It's a regular variable, not a function
                    name = name_node.text.decode("utf-8", errors="replace") if name_node.text else None
                    if name:
                        var_id = f"{repo_id}:{filepath}:{NodeKind.VARIABLE.value}:{name}"
                        nodes.append(
                            ASTNode(
                                id=var_id,
                                kind=NodeKind.VARIABLE,
                                name=name,
                                filepath=filepath,
                                start_line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                source_text=(
                                    node.text.decode("utf-8", errors="replace")[:2000]
                                    if node.text
                                    else ""
                                ),
                                parent_id=parent_id,
                            )
                        )
                        edges.append(
                            ASTEdge(source_id=parent_id, target_id=var_id, relation="contains")
                        )
                    continue

                name = name_node.text.decode("utf-8", errors="replace") if name_node.text else None
                if not name:
                    continue

                func_id = f"{repo_id}:{filepath}:{NodeKind.FUNCTION.value}:{name}"
                params_node = value_node.child_by_field_name("parameters")
                params = (
                    params_node.text.decode("utf-8", errors="replace") if params_node and params_node.text else "()"
                )
                is_async = any(c.type == "async" for c in value_node.children)
                prefix = "async " if is_async else ""
                sig = f"const {name} = {prefix}{params} =>"

                source_text = node.text.decode("utf-8", errors="replace") if node.text else ""
                docstring = self._extract_docstring(node, lines, mapping)

                nodes.append(
                    ASTNode(
                        id=func_id,
                        kind=NodeKind.FUNCTION,
                        name=name,
                        filepath=filepath,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        source_text=source_text[:2000],
                        docstring=docstring,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                edges.append(
                    ASTEdge(source_id=parent_id, target_id=func_id, relation="contains")
                )

    def _extract_ts_signature(
        self, node, lines: list[str], kind: NodeKind, name: str
    ) -> Optional[str]:
        """Extract a TypeScript-appropriate signature."""
        if kind == NodeKind.FUNCTION:
            params_node = node.child_by_field_name("parameters")
            params = (
                params_node.text.decode("utf-8", errors="replace")
                if params_node and params_node.text
                else "()"
            )
            is_async = any(c.type == "async" for c in node.children)
            prefix = "async function" if is_async else "function"
            return f"{prefix} {name}{params}"
        elif kind == NodeKind.METHOD:
            params_node = node.child_by_field_name("parameters")
            params = (
                params_node.text.decode("utf-8", errors="replace")
                if params_node and params_node.text
                else "()"
            )
            return f"{name}{params}"
        # For classes, return the first line
        start_line = node.start_point[0]
        if start_line < len(lines):
            return lines[start_line].strip()
        return None

    def _extract_ts_import(
        self,
        node,
        parent_id: str,
        repo_id: str,
        filepath: str,
        nodes: list[ASTNode],
        edges: list[ASTEdge],
    ) -> None:
        """Extract import statement nodes for TypeScript/JavaScript."""
        src_text = node.text.decode("utf-8", errors="replace") if node.text else ""

        # Find import clause and extract imported names
        imported_names: list[str] = []
        for child in node.children:
            if child.type == "import_clause":
                for spec in child.children:
                    if spec.type == "identifier" and spec.text:
                        imported_names.append(spec.text.decode("utf-8", errors="replace"))
                    elif spec.type == "named_imports":
                        for imp_spec in spec.children:
                            if imp_spec.type == "import_specifier":
                                name_node = imp_spec.child_by_field_name("name")
                                if name_node and name_node.text:
                                    imported_names.append(
                                        name_node.text.decode("utf-8", errors="replace")
                                    )
                    elif spec.type == "namespace_import":
                        # import * as name
                        for ns_child in spec.children:
                            if ns_child.type == "identifier" and ns_child.text:
                                imported_names.append(
                                    ns_child.text.decode("utf-8", errors="replace")
                                )

        # If no names extracted, use the source path as fallback
        if not imported_names:
            # Try to get the module source string
            for child in node.children:
                if child.type == "string" and child.text:
                    mod_path = child.text.decode("utf-8", errors="replace").strip("\"'")
                    if mod_path:
                        imported_names.append(mod_path)
                    break

        for name in imported_names:
            import_id = f"{repo_id}:{filepath}:{NodeKind.IMPORT.value}:{name}"
            nodes.append(
                ASTNode(
                    id=import_id,
                    kind=NodeKind.IMPORT,
                    name=name,
                    filepath=filepath,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    source_text=src_text[:500],
                    parent_id=parent_id,
                )
            )
            edges.append(
                ASTEdge(source_id=parent_id, target_id=import_id, relation="contains")
            )

    @staticmethod
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
