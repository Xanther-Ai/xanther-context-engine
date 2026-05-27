"""Ruby parser using tree-sitter.

Implements TreeSitterBaseParser with a NodeTypeMapping for Ruby.
Handles .rb files.
"""

from __future__ import annotations

import tree_sitter_ruby as ts_ruby
from tree_sitter import Language

from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

# Initialize language
_RUBY_LANGUAGE = Language(ts_ruby.language())

# Ruby node type mapping
_RUBY_MAPPING = NodeTypeMapping(
    class_types=("class", "module"),
    function_types=("method", "singleton_method"),
    import_types=("call",),  # require/require_relative are method calls in Ruby
    call_types=("call",),
    name_field="name",
    parameters_field="parameters",
    body_field="body",
    inheritance_types=("superclass",),
    method_parent_types=("class", "module"),
    comment_types=("comment",),
    max_file_size=1_000_000,
)


class RubyParser(TreeSitterBaseParser):
    """Ruby parser via tree-sitter.

    Extracts classes, modules, methods, singleton methods,
    and require statements from Ruby source files.
    """

    def supported_extensions(self) -> list[str]:
        return [".rb"]

    def language_name(self) -> str:
        return "ruby"

    def _get_language(self) -> Language:
        return _RUBY_LANGUAGE

    def _get_mapping(self) -> NodeTypeMapping:
        return _RUBY_MAPPING
