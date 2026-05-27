"""Swift parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Swift.
Handles .swift files.
"""

from __future__ import annotations

import tree_sitter_swift as ts_swift
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_SWIFT_LANGUAGE = Language(ts_swift.language())

# Swift node type mapping
_SWIFT_MAPPING = NodeTypeMapping(
    class_types=("class_declaration", "struct_declaration", "protocol_declaration"),
    function_types=("function_declaration",),
    import_types=("import_declaration",),
    call_types=("call_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("inheritance_specifier",),
    decorator_types=("attribute",),
    method_parent_types=("class_body", "struct_body"),
    comment_types=("comment", "multiline_comment"),
    max_file_size=1_000_000,
)


class SwiftParser(TreeSitterBaseParser):
    """Swift parser via tree-sitter.

    Extracts classes, structs, protocols, functions,
    and import declarations from Swift source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".swift"]

    def language_name(self) -> str:
        return "swift"

    def _get_language(self) -> Language:
        return _SWIFT_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _SWIFT_MAPPING
