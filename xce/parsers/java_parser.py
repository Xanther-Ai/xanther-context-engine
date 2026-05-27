"""Java parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Java.
Handles .java files.
"""

from __future__ import annotations

import tree_sitter_java as ts_java
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_JAVA_LANGUAGE = Language(ts_java.language())

# Java node type mapping
_JAVA_MAPPING = NodeTypeMapping(
    class_types=("class_declaration", "interface_declaration"),
    function_types=("method_declaration", "constructor_declaration"),
    import_types=("import_declaration",),
    call_types=("method_invocation",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("superclass", "super_interfaces"),
    decorator_types=("marker_annotation", "annotation"),
    method_parent_types=("class_body",),
    comment_types=("line_comment", "block_comment"),
    max_file_size=1_000_000,
)


class JavaParser(TreeSitterBaseParser):
    """Java parser via tree-sitter.

    Extracts classes, interfaces, methods, constructors,
    and import declarations from Java source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".java"]

    def language_name(self) -> str:
        return "java"

    def _get_language(self) -> Language:
        return _JAVA_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _JAVA_MAPPING
