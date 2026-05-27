"""PHP parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for PHP.
Handles .php files.
"""

from __future__ import annotations

import tree_sitter_php as ts_php
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language — PHP grammar exposes language_php()
_PHP_LANGUAGE = Language(ts_php.language())

# PHP node type mapping
_PHP_MAPPING = NodeTypeMapping(
    class_types=("class_declaration", "interface_declaration", "trait_declaration"),
    function_types=("function_definition", "method_declaration"),
    import_types=("namespace_use_declaration",),
    call_types=("function_call_expression", "member_call_expression"),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("base_clause",),
    method_parent_types=("declaration_list",),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class PHPParser(TreeSitterBaseParser):
    """PHP parser via tree-sitter.

    Extracts classes, interfaces, traits, functions, methods,
    and namespace use declarations from PHP source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".php"]

    def language_name(self) -> str:
        return "php"

    def _get_language(self) -> Language:
        return _PHP_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _PHP_MAPPING
