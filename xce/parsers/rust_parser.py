"""Rust parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Rust.
Handles .rs files.
"""

from __future__ import annotations

import tree_sitter_rust as ts_rust
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_RUST_LANGUAGE = Language(ts_rust.language())

# Rust node type mapping
_RUST_MAPPING = NodeTypeMapping(
    class_types=("struct_item", "enum_item", "trait_item", "impl_item"),
    function_types=("function_item",),
    import_types=("use_declaration",),
    call_types=("call_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    comment_types=("line_comment", "block_comment"),
    max_file_size=1_000_000,
)


class RustParser(TreeSitterBaseParser):
    """Rust parser via tree-sitter.

    Extracts structs, enums, traits, impl blocks, functions,
    and use declarations from Rust source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".rs"]

    def language_name(self) -> str:
        return "rust"

    def _get_language(self) -> Language:
        return _RUST_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _RUST_MAPPING
