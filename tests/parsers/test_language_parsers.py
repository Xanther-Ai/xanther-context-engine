"""Parametrized unit tests for all tree-sitter language parsers.

Tests Go, Rust, Java, C#, Ruby, PHP, Kotlin, Swift, and C/C++ parsers.
Each parser is verified to:
  - Produce a MODULE node
  - Extract classes/functions/imports
  - Produce valid ASTNode IDs
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parsers import get_default_registry
from xce.parsers.base import BaseParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Valid ASTNode ID pattern: {repo_id}:{filepath}:{kind}:{name}
_ID_PATTERN = re.compile(r"^[^:]+:[^:]+:[^:]+:.+$")

# Valid NodeKind values
_VALID_KINDS = {k.value for k in NodeKind}

# Valid edge relations
_VALID_RELATIONS = {"contains", "calls", "imports", "inherits", "decorates"}


# ---------------------------------------------------------------------------
# Test parameters: (fixture_filename, extension, expected_class, expected_func)
# ---------------------------------------------------------------------------

_LANGUAGE_PARAMS = [
    pytest.param("sample.go", ".go", "DataProcessor", "NewDataProcessor", id="go"),
    pytest.param("sample.rs", ".rs", "DataProcessor", "load_data", id="rust"),
    pytest.param("sample.java", ".java", "DataProcessor", "DataProcessor", id="java"),
    pytest.param("sample.cs", ".cs", "DataProcessor", "Process", id="csharp"),
    pytest.param("sample.rb", ".rb", "DataProcessor", "initialize", id="ruby"),
    pytest.param("sample.php", ".php", "DataProcessor", "__construct", id="php"),
    pytest.param("sample.kt", ".kt", "DataProcessor", "loadData", id="kotlin"),
    pytest.param("sample.swift", ".swift", "DataProcessor", "loadData", id="swift"),
    pytest.param("sample.cpp", ".cpp", "DataProcessor", "process", id="cpp"),
]


def _get_parser_for_ext(ext: str) -> BaseParser:
    """Get the parser for a given extension from the default registry.

    Skips the test if the grammar for the extension is not installed.
    """
    registry = get_default_registry()
    parser = registry.get_parser(f"file{ext}")
    if parser is None:
        pytest.skip(f"No parser registered for {ext} (grammar not installed)")
    return parser


def _parse_fixture(fixture_name: str, ext: str, repo_id: str = "test-repo"):
    """Parse a fixture file and return (nodes, edges)."""
    parser = _get_parser_for_ext(ext)
    source = (FIXTURES_DIR / fixture_name).read_text()
    filepath = f"src/{fixture_name}"
    return parser.parse_file(filepath, source, repo_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModuleNode:
    """Each parser produces a MODULE node."""

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_produces_module_node(self, fixture: str, ext: str, _cls: str, _func: str) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) >= 1, f"No MODULE node for {fixture}"


class TestExtractsDeclarations:
    """Each parser extracts classes/functions/imports."""

    @pytest.mark.parametrize("fixture,ext,expected_class,_func", _LANGUAGE_PARAMS)
    def test_extracts_class_or_struct(
        self, fixture: str, ext: str, expected_class: str, _func: str
    ) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = [n.name for n in class_nodes]
        assert expected_class in class_names, (
            f"Expected class '{expected_class}' not found in {fixture}. "
            f"Got: {class_names}"
        )

    @pytest.mark.parametrize("fixture,ext,_cls,expected_func", _LANGUAGE_PARAMS)
    def test_extracts_function_or_method(
        self, fixture: str, ext: str, _cls: str, expected_func: str
    ) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        func_nodes = [
            n for n in nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)
        ]
        func_names = [n.name for n in func_nodes]
        assert expected_func in func_names, (
            f"Expected function '{expected_func}' not found in {fixture}. "
            f"Got: {func_names}"
        )

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_extracts_imports(self, fixture: str, ext: str, _cls: str, _func: str) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        import_nodes = [n for n in nodes if n.kind == NodeKind.IMPORT]
        assert len(import_nodes) >= 1, f"No IMPORT nodes for {fixture}"


class TestValidNodeIDs:
    """Each parser produces valid ASTNode IDs."""

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_node_ids_match_format(
        self, fixture: str, ext: str, _cls: str, _func: str
    ) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        for node in nodes:
            assert _ID_PATTERN.match(node.id), (
                f"Invalid node ID format: '{node.id}' in {fixture}"
            )

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_node_kinds_are_valid(
        self, fixture: str, ext: str, _cls: str, _func: str
    ) -> None:
        nodes, _ = _parse_fixture(fixture, ext)

        for node in nodes:
            assert node.kind.value in _VALID_KINDS, (
                f"Invalid NodeKind: {node.kind} in {fixture}"
            )

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_edge_relations_are_valid(
        self, fixture: str, ext: str, _cls: str, _func: str
    ) -> None:
        _, edges = _parse_fixture(fixture, ext)

        for edge in edges:
            assert edge.relation in _VALID_RELATIONS, (
                f"Invalid edge relation: '{edge.relation}' in {fixture}"
            )

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_node_id_contains_repo_id(
        self, fixture: str, ext: str, _cls: str, _func: str
    ) -> None:
        repo_id = "test-repo"
        nodes, _ = _parse_fixture(fixture, ext, repo_id=repo_id)

        for node in nodes:
            assert node.id.startswith(f"{repo_id}:"), (
                f"Node ID doesn't start with repo_id: '{node.id}'"
            )


class TestHandlesEmptyFile:
    """Each parser handles empty file gracefully."""

    @pytest.mark.parametrize("fixture,ext,_cls,_func", _LANGUAGE_PARAMS)
    def test_parser_handles_empty_file_gracefully(
        self, fixture: str, ext: str, _cls: str, _func: str
    ) -> None:
        parser = _get_parser_for_ext(ext)
        nodes, edges = parser.parse_file(f"empty{ext}", "", "test-repo")

        # Should not raise; returns at least a module node or empty lists
        assert isinstance(nodes, list)
        assert isinstance(edges, list)


class TestCppHeaderFile:
    """Additional test for C/C++ header file parsing."""

    def test_parses_header_file(self) -> None:
        nodes, _ = _parse_fixture("sample.h", ".h")

        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) >= 1

        # Should find the IProcessor class
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = [n.name for n in class_nodes]
        assert "IProcessor" in class_names

    def test_header_extracts_imports(self) -> None:
        nodes, _ = _parse_fixture("sample.h", ".h")

        import_nodes = [n for n in nodes if n.kind == NodeKind.IMPORT]
        assert len(import_nodes) >= 1
