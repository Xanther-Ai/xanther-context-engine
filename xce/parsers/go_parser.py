"""Go parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Go.
Handles .go files.
"""

from __future__ import annotations

import tree_sitter_go as ts_go
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_GO_LANGUAGE = Language(ts_go.language())

# Go node type mapping
_GO_MAPPING = NodeTypeMapping(
    module_types=("package_clause",),
    class_types=("type_declaration",),
    function_types=("function_declaration", "method_declaration"),
    import_types=("import_declaration",),
    variable_types=("var_declaration", "const_declaration"),
    call_types=("call_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    method_parent_types=("type_declaration",),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class GoParser(TreeSitterBaseParser):
    """Go parser via tree-sitter.

    Extracts packages, structs, interfaces, functions, methods,
    and import declarations from Go source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".go"]

    def language_name(self) -> str:
        return "go"

    def _get_language(self) -> Language:
        return _GO_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _GO_MAPPING
