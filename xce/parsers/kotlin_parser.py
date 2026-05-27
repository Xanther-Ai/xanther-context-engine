"""Kotlin parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Kotlin.
Handles .kt and .kts files.
"""

from __future__ import annotations

import tree_sitter_kotlin as ts_kotlin
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_KOTLIN_LANGUAGE = Language(ts_kotlin.language())

# Kotlin node type mapping
_KOTLIN_MAPPING = NodeTypeMapping(
    class_types=("class_declaration", "interface_declaration", "object_declaration"),
    function_types=("function_declaration",),
    import_types=("import_header",),
    call_types=("call_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("delegation_specifiers",),
    decorator_types=("annotation",),
    method_parent_types=("class_body",),
    comment_types=("line_comment", "multiline_comment"),
    max_file_size=1_000_000,
)


class KotlinParser(TreeSitterBaseParser):
    """Kotlin parser via tree-sitter.

    Extracts classes, interfaces, object declarations, functions,
    and import headers from Kotlin source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".kt", ".kts"]

    def language_name(self) -> str:
        return "kotlin"

    def _get_language(self) -> Language:
        return _KOTLIN_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _KOTLIN_MAPPING
