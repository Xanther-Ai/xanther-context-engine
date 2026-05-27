"""Unit tests for the PythonParser."""

from __future__ import annotations

from xce.models import NodeKind
from xce.parsers.python_parser import PythonParser


class TestPythonParserSupportedExtensions:
    """Test: PythonParser reports correct supported extensions."""

    def test_supported_extensions(self, python_parser: PythonParser) -> None:
        extensions = python_parser.supported_extensions()
        assert ".py" in extensions
        assert ".pyi" in extensions
        assert len(extensions) == 2


class TestPythonParserModuleNode:
    """Test: PythonParser produces output with MODULE node."""

    def test_produces_module_node(self, python_parser: PythonParser, repo_id: str) -> None:
        source = "x = 1\n"
        nodes, edges = python_parser.parse_file("src/simple.py", source, repo_id)

        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].name == "simple"
        assert module_nodes[0].filepath == "src/simple.py"

    def test_module_node_id_format(self, python_parser: PythonParser, repo_id: str) -> None:
        source = "pass\n"
        nodes, _ = python_parser.parse_file("pkg/mod.py", source, repo_id)

        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert module_nodes[0].id == f"{repo_id}:pkg/mod.py:module:mod"

    def test_extracts_classes_and_functions(
        self, python_parser: PythonParser, repo_id: str, sample_python_source: str
    ) -> None:
        nodes, _ = python_parser.parse_file("sample.py", sample_python_source, repo_id)

        kinds = {n.kind for n in nodes}
        assert NodeKind.MODULE in kinds
        assert NodeKind.CLASS in kinds
        assert NodeKind.FUNCTION in kinds
        assert NodeKind.METHOD in kinds
        assert NodeKind.IMPORT in kinds

    def test_extracts_class_by_name(
        self, python_parser: PythonParser, repo_id: str, sample_python_source: str
    ) -> None:
        nodes, _ = python_parser.parse_file("sample.py", sample_python_source, repo_id)

        class_names = [n.name for n in nodes if n.kind == NodeKind.CLASS]
        assert "DataProcessor" in class_names

    def test_extracts_function_by_name(
        self, python_parser: PythonParser, repo_id: str, sample_python_source: str
    ) -> None:
        nodes, _ = python_parser.parse_file("sample.py", sample_python_source, repo_id)

        func_names = [n.name for n in nodes if n.kind == NodeKind.FUNCTION]
        assert "load_data" in func_names


class TestPythonParserSyntaxError:
    """Test: syntax error returns empty lists."""

    def test_syntax_error_returns_empty(self, python_parser: PythonParser, repo_id: str) -> None:
        source = "def broken(\n"
        nodes, edges = python_parser.parse_file("bad.py", source, repo_id)

        assert nodes == []
        assert edges == []

    def test_invalid_source_no_exception(self, python_parser: PythonParser, repo_id: str) -> None:
        source = "class Foo:\n  def bar(self\n    pass"
        nodes, edges = python_parser.parse_file("bad2.py", source, repo_id)

        assert isinstance(nodes, list)
        assert isinstance(edges, list)


class TestPythonParserEdges:
    """Test: output contains CONTAINS edges, CALLS edges."""

    def test_contains_edges(
        self, python_parser: PythonParser, repo_id: str, sample_python_source: str
    ) -> None:
        _, edges = python_parser.parse_file("sample.py", sample_python_source, repo_id)

        contains_edges = [e for e in edges if e.relation == "contains"]
        assert len(contains_edges) > 0

    def test_calls_edges(self, python_parser: PythonParser, repo_id: str) -> None:
        source = """\
def helper():
    return 42

def main():
    result = helper()
    print(result)
"""
        _, edges = python_parser.parse_file("calls.py", source, repo_id)

        calls_edges = [e for e in edges if e.relation == "calls"]
        assert len(calls_edges) > 0

        # main should call helper
        callee_ids = [e.target_id for e in calls_edges]
        assert any("helper" in cid for cid in callee_ids)

    def test_contains_edges_link_module_to_class(
        self, python_parser: PythonParser, repo_id: str, sample_python_source: str
    ) -> None:
        nodes, edges = python_parser.parse_file("sample.py", sample_python_source, repo_id)

        module_id = next(n.id for n in nodes if n.kind == NodeKind.MODULE)
        class_id = next(n.id for n in nodes if n.kind == NodeKind.CLASS)

        contains_from_module = [
            e for e in edges if e.source_id == module_id and e.relation == "contains"
        ]
        target_ids = [e.target_id for e in contains_from_module]
        assert class_id in target_ids
