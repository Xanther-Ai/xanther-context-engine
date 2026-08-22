"""XCE parser package — pluggable, registry-based multi-language parsing.

Exports:
    BaseParser: Abstract base class for all language parsers.
    TreeSitterBaseParser: Generic tree-sitter parser with shared tree-walking logic.
    NodeTypeMapping: Frozen dataclass configuring tree-sitter node type mappings.
    ParserRegistry: Maps file extensions to parser instances.
    get_default_registry: Factory function returning a fully-configured registry.
"""

from xce.parsers.base import BaseParser
from xce.parsers.registry import ParserRegistry
from xce.parsers.tree_sitter_base import NodeTypeMapping, TreeSitterBaseParser

__all__ = [
    "BaseParser",
    "TreeSitterBaseParser",
    "NodeTypeMapping",
    "ParserRegistry",
    "get_default_registry",
]


def get_default_registry() -> ParserRegistry:
    """Create and return a fully-configured parser registry with all languages.

    Gracefully skips languages whose tree-sitter grammar fails to load.
    The Python parser is always available (uses stdlib ast module).
    """
    import importlib
    import logging

    logger = logging.getLogger(__name__)
    registry = ParserRegistry()

    def _try_register(module_path: str, class_name: str) -> None:
        """Attempt to import and register a parser, logging errors on failure."""
        try:
            mod = importlib.import_module(module_path)
            parser_cls = getattr(mod, class_name)
            registry.register(parser_cls())
        except Exception as exc:
            # Only log at debug level — missing tree-sitter grammars are not errors
            # (e.g., tree_sitter_php has version incompatibility on some platforms)
            logger.debug("Skipped %s.%s: %s", module_path, class_name, exc)

    # Always available (uses stdlib ast)
    _try_register("xce.parsers.python_parser", "PythonParser")

    # Tree-sitter based parsers — each wrapped in try/except
    _try_register("xce.parsers.typescript_parser", "TypeScriptParser")
    _try_register("xce.parsers.go_parser", "GoParser")
    _try_register("xce.parsers.rust_parser", "RustParser")
    _try_register("xce.parsers.java_parser", "JavaParser")
    _try_register("xce.parsers.csharp_parser", "CSharpParser")
    _try_register("xce.parsers.ruby_parser", "RubyParser")
    _try_register("xce.parsers.php_parser", "PHPParser")
    _try_register("xce.parsers.kotlin_parser", "KotlinParser")
    _try_register("xce.parsers.swift_parser", "SwiftParser")
    _try_register("xce.parsers.cpp_parser", "CppParser")

    registry.freeze()
    return registry
