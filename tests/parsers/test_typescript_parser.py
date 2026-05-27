"""Unit tests for the TypeScriptParser."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_typescript", reason="tree-sitter-typescript not installed")

from xce.models import NodeKind
from xce.parsers.typescript_parser import TypeScriptParser


class TestTypeScriptParserBasic:
    """Test: parses .ts file extracting classes, functions, imports."""

    def test_extracts_class(
        self, typescript_parser: TypeScriptParser, repo_id: str, sample_ts_source: str
    ) -> None:
        nodes, _ = typescript_parser.parse_file("src/service.ts", sample_ts_source, repo_id)

        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) >= 1
        class_names = [n.name for n in class_nodes]
        assert "DataService" in class_names

    def test_extracts_functions(
        self, typescript_parser: TypeScriptParser, repo_id: str, sample_ts_source: str
    ) -> None:
        nodes, _ = typescript_parser.parse_file("src/service.ts", sample_ts_source, repo_id)

        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = [n.name for n in func_nodes]
        # Should find arrow function and regular function
        assert "formatOutput" in func_names or "parseConfig" in func_names

    def test_extracts_imports(
        self, typescript_parser: TypeScriptParser, repo_id: str, sample_ts_source: str
    ) -> None:
        nodes, _ = typescript_parser.parse_file("src/service.ts", sample_ts_source, repo_id)

        import_nodes = [n for n in nodes if n.kind == NodeKind.IMPORT]
        assert len(import_nodes) >= 1

    def test_produces_module_node(
        self, typescript_parser: TypeScriptParser, repo_id: str, sample_ts_source: str
    ) -> None:
        nodes, _ = typescript_parser.parse_file("src/service.ts", sample_ts_source, repo_id)

        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].name == "service"

    def test_produces_contains_edges(
        self, typescript_parser: TypeScriptParser, repo_id: str, sample_ts_source: str
    ) -> None:
        _, edges = typescript_parser.parse_file("src/service.ts", sample_ts_source, repo_id)

        contains_edges = [e for e in edges if e.relation == "contains"]
        assert len(contains_edges) >= 1

    def test_parses_tsx_file(self, typescript_parser: TypeScriptParser, repo_id: str) -> None:
        source = """\
import React from "react";

interface Props {
    name: string;
}

export class Greeting extends React.Component<Props> {
    render() {
        return <div>Hello {this.props.name}</div>;
    }
}
"""
        nodes, _ = typescript_parser.parse_file("App.tsx", source, repo_id)

        # Should parse without error and produce nodes
        assert len(nodes) >= 1
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1

    def test_parses_js_file(self, typescript_parser: TypeScriptParser, repo_id: str) -> None:
        source = """\
import { useState } from "react";

function Counter() {
    const [count, setCount] = useState(0);
    return count;
}

module.exports = { Counter };
"""
        nodes, _ = typescript_parser.parse_file("counter.js", source, repo_id)

        assert len(nodes) >= 1
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = [n.name for n in func_nodes]
        assert "Counter" in func_names


class TestTypeScriptParserSyntaxError:
    """Test: syntax error returns partial results."""

    def test_syntax_error_returns_partial(
        self, typescript_parser: TypeScriptParser, repo_id: str
    ) -> None:
        # tree-sitter is error-tolerant, so it should still produce partial results
        source = """\
import { foo } from "bar";

class Broken {
    method() {
        // missing closing brace
"""
        nodes, edges = typescript_parser.parse_file("broken.ts", source, repo_id)

        # Should not raise and should return at least the module node
        assert isinstance(nodes, list)
        assert isinstance(edges, list)
        # tree-sitter typically still extracts what it can
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1

    def test_completely_invalid_source(
        self, typescript_parser: TypeScriptParser, repo_id: str
    ) -> None:
        source = "}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}"
        nodes, edges = typescript_parser.parse_file("garbage.ts", source, repo_id)

        # Should not raise
        assert isinstance(nodes, list)
        assert isinstance(edges, list)
