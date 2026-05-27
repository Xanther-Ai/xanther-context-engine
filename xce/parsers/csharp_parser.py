"""C# parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for C#.
Handles .cs files.
"""

from __future__ import annotations

import tree_sitter_c_sharp as ts_csharp
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_CSHARP_LANGUAGE = Language(ts_csharp.language())

# C# node type mapping
_CSHARP_MAPPING = NodeTypeMapping(
    class_types=("class_declaration", "interface_declaration", "struct_declaration"),
    function_types=("method_declaration", "constructor_declaration"),
    import_types=("using_directive",),
    call_types=("invocation_expression",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("base_list",),
    decorator_types=("attribute_list",),
    method_parent_types=("declaration_list",),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class CSharpParser(TreeSitterBaseParser):
    """C# parser via tree-sitter.

    Extracts classes, interfaces, structs, methods, constructors,
    and using directives from C# source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".cs"]

    def language_name(self) -> str:
        return "csharp"

    def _get_language(self) -> Language:
        return _CSHARP_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _CSHARP_MAPPING
