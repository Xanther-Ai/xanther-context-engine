"""Unit tests for the ParserRegistry."""

from __future__ import annotations

import importlib

import pytest

from xce.models import ASTEdge, ASTNode
from xce.parsers.base import BaseParser
from xce.parsers.registry import ParserRegistry
from xce.parsers import get_default_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _grammar_available(module_name: str) -> bool:
    """Check if a tree-sitter grammar module is importable."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


class _FakeParser(BaseParser):
    """Minimal parser for testing registry behavior."""

    def __init__(self, name: str, extensions: list[str]) -> None:
        self._name = name
        self._extensions = extensions

    def parse_file(
        self, filepath: str, source: str, repo_id: str
    ) -> tuple[list[ASTNode], list[ASTEdge]]:
        return [], []

    def supported_extensions(self) -> list[str]:
        return self._extensions

    def language_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterAndRetrieve:
    """Test: register parser, get_parser returns correct parser."""

    def test_register_and_get_parser(self) -> None:
        registry = ParserRegistry()
        parser = _FakeParser("fake", [".fk", ".fake"])
        registry.register(parser)

        assert registry.get_parser("src/module.fk") is parser
        assert registry.get_parser("lib/other.fake") is parser

    def test_get_parser_case_insensitive_extension(self) -> None:
        registry = ParserRegistry()
        parser = _FakeParser("fake", [".fk"])
        registry.register(parser)

        # Extensions are lowercased during lookup
        assert registry.get_parser("file.FK") is parser


class TestDuplicateExtension:
    """Test: duplicate extension raises ValueError."""

    def test_duplicate_extension_raises(self) -> None:
        registry = ParserRegistry()
        parser_a = _FakeParser("lang_a", [".x"])
        parser_b = _FakeParser("lang_b", [".x"])

        registry.register(parser_a)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(parser_b)

    def test_same_parser_different_extensions_ok(self) -> None:
        registry = ParserRegistry()
        parser_a = _FakeParser("lang_a", [".a1", ".a2"])
        parser_b = _FakeParser("lang_b", [".b1"])

        registry.register(parser_a)
        registry.register(parser_b)

        assert registry.get_parser("f.a1") is parser_a
        assert registry.get_parser("f.b1") is parser_b


class TestUnknownExtension:
    """Test: unknown extension returns None."""

    def test_unknown_extension_returns_none(self) -> None:
        registry = ParserRegistry()
        parser = _FakeParser("fake", [".fk"])
        registry.register(parser)

        assert registry.get_parser("file.unknown") is None
        assert registry.get_parser("file") is None


class TestFreeze:
    """Test: freeze prevents further registration."""

    def test_freeze_prevents_registration(self) -> None:
        registry = ParserRegistry()
        registry.freeze()

        parser = _FakeParser("fake", [".fk"])
        with pytest.raises(RuntimeError, match="frozen"):
            registry.register(parser)

    def test_get_parser_works_after_freeze(self) -> None:
        registry = ParserRegistry()
        parser = _FakeParser("fake", [".fk"])
        registry.register(parser)
        registry.freeze()

        assert registry.get_parser("file.fk") is parser


class TestDefaultRegistry:
    """Test: all expected extensions are registered in default registry."""

    def test_python_extensions_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.py") is not None
        assert registry.get_parser("file.pyi") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_typescript"),
        reason="tree-sitter-typescript not installed",
    )
    def test_typescript_extensions_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.ts") is not None
        assert registry.get_parser("file.tsx") is not None
        assert registry.get_parser("file.js") is not None
        assert registry.get_parser("file.jsx") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_go"),
        reason="tree-sitter-go not installed",
    )
    def test_go_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.go") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_rust"),
        reason="tree-sitter-rust not installed",
    )
    def test_rust_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.rs") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_java"),
        reason="tree-sitter-java not installed",
    )
    def test_java_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.java") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_c_sharp"),
        reason="tree-sitter-c-sharp not installed",
    )
    def test_csharp_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.cs") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_ruby"),
        reason="tree-sitter-ruby not installed",
    )
    def test_ruby_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.rb") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_php"),
        reason="tree-sitter-php not installed",
    )
    def test_php_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.php") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_kotlin"),
        reason="tree-sitter-kotlin not installed",
    )
    def test_kotlin_extensions_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.kt") is not None
        assert registry.get_parser("file.kts") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_swift"),
        reason="tree-sitter-swift not installed",
    )
    def test_swift_extension_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.swift") is not None

    @pytest.mark.skipif(
        not _grammar_available("tree_sitter_cpp"),
        reason="tree-sitter-cpp not installed",
    )
    def test_cpp_extensions_registered(self, registry: ParserRegistry) -> None:
        assert registry.get_parser("file.c") is not None
        assert registry.get_parser("file.cpp") is not None
        assert registry.get_parser("file.cc") is not None
        assert registry.get_parser("file.cxx") is not None
        assert registry.get_parser("file.h") is not None
        assert registry.get_parser("file.hpp") is not None

    def test_all_expected_extensions_present(self, registry: ParserRegistry) -> None:
        """Verify all extensions are registered when all grammars are available.

        Skips individual extensions whose grammars are not installed.
        """
        grammar_ext_map = {
            "tree_sitter_typescript": {".ts", ".tsx", ".js", ".jsx"},
            "tree_sitter_go": {".go"},
            "tree_sitter_rust": {".rs"},
            "tree_sitter_java": {".java"},
            "tree_sitter_c_sharp": {".cs"},
            "tree_sitter_ruby": {".rb"},
            "tree_sitter_php": {".php"},
            "tree_sitter_kotlin": {".kt", ".kts"},
            "tree_sitter_swift": {".swift"},
            "tree_sitter_cpp": {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"},
        }
        # Python is always available
        expected = {".py", ".pyi"}
        for grammar, exts in grammar_ext_map.items():
            if _grammar_available(grammar):
                expected.update(exts)

        registered = set(registry.supported_extensions)
        assert expected.issubset(registered), f"Missing: {expected - registered}"

    def test_default_registry_languages_list(self, registry: ParserRegistry) -> None:
        """Verify all language names are present when grammars are available."""
        grammar_lang_map = {
            "tree_sitter_typescript": "typescript",
            "tree_sitter_go": "go",
            "tree_sitter_rust": "rust",
            "tree_sitter_java": "java",
            "tree_sitter_c_sharp": "csharp",
            "tree_sitter_ruby": "ruby",
            "tree_sitter_php": "php",
            "tree_sitter_kotlin": "kotlin",
            "tree_sitter_swift": "swift",
            "tree_sitter_cpp": "cpp",
        }
        # Python is always available
        expected_languages = {"python"}
        for grammar, lang in grammar_lang_map.items():
            if _grammar_available(grammar):
                expected_languages.add(lang)

        languages = set(registry.languages)
        assert expected_languages.issubset(languages), (
            f"Missing languages: {expected_languages - languages}"
        )
