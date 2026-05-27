"""C/C++ parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for C and C++.
Handles .c, .cpp, .cc, .cxx, .h, and .hpp files.
"""

from __future__ import annotations

import tree_sitter_cpp as ts_cpp
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language — C++ grammar is a superset of C
_CPP_LANGUAGE = Language(ts_cpp.language())

# C/C++ node type mapping
_CPP_MAPPING = NodeTypeMapping(
    class_types=("class_specifier", "struct_specifier"),
    function_types=("function_definition", "declaration"),
    import_types=("preproc_include",),
    call_types=("call_expression",),
    name_field="declarator",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("base_class_clause",),
    method_parent_types=("class_specifier", "struct_specifier"),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class CppParser(TreeSitterBaseParser):
    """C/C++ parser via tree-sitter.

    Extracts classes, structs, functions, and include directives
    from C and C++ source files. Uses the C++ grammar which is
    a superset of C.
    """

    def supported_extensions(self) -> list[str]:
        return [".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"]

    def language_name(self) -> str:
        return "cpp"

    def _get_language(self) -> Language:
        return _CPP_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _CPP_MAPPING
