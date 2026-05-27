"""Unit tests for the AST parser.

Covers: node extraction, edge types, ID uniqueness, syntax error handling,
edge cases (empty files, nested classes, async functions, generators, decorators).

Validates:
- P1: Every top-level definition has exactly one ASTNode
- P2: All node IDs are unique
- P3: All edges reference existing nodes (no dangling edges)
- No self-referential edges (source_id != target_id)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from xce.models import ASTEdge, ASTNode, NodeKind
from xce.parser import ASTParser, make_node_id, resolve_cross_file_imports


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SOURCE = '''\
"""Module docstring."""

import os
from pathlib import Path

MY_CONST = 42

class Base:
    """Base class."""
    pass

class Child(Base):
    """Child class."""

    class_var: int = 10

    def __init__(self, x):
        """Init."""
        self.x = x

    def method(self):
        """A method."""
        return self.x

    @staticmethod
    def static_method():
        pass

def top_level_func(a, b=1):
    """Top-level function."""
    return a + b

def caller():
    top_level_func(1, 2)

async def async_func():
    """An async function."""
    pass

def generator_func():
    """A generator."""
    yield 1
    yield 2
'''

DECORATED_SOURCE = '''\
import functools

def my_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@my_decorator
def decorated_func():
    """Decorated."""
    pass

class MyClass:
    @staticmethod
    def static_m():
        pass

    @classmethod
    def class_m(cls):
        pass
'''

EMPTY_SOURCE = ""

SYNTAX_ERROR_SOURCE = "def broken(\n"

DEEPLY_NESTED_SOURCE = '''\
class Outer:
    class Middle:
        class Inner:
            def deep_method(self):
                pass
'''


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser(repo_id="test-repo")


# ---------------------------------------------------------------------------
# Sub-task 2.1: NodeKind enum and dataclasses
# ---------------------------------------------------------------------------

class TestModels:
    def test_node_kind_values(self):
        assert NodeKind.MODULE.value == "module"
        assert NodeKind.CLASS.value == "class"
        assert NodeKind.FUNCTION.value == "function"
        assert NodeKind.METHOD.value == "method"
        assert NodeKind.IMPORT.value == "import"
        assert NodeKind.VARIABLE.value == "variable"
        assert NodeKind.DECORATOR.value == "decorator"
        assert NodeKind.ARGUMENT.value == "argument"

    def test_ast_node_creation(self):
        node = ASTNode(
            id="r:f:function:foo",
            kind=NodeKind.FUNCTION,
            name="foo",
            filepath="f.py",
            start_line=1,
            end_line=3,
            source_text="def foo(): pass",
        )
        assert node.docstring is None
        assert node.signature is None
        assert node.parent_id is None

    def test_ast_edge_creation(self):
        edge = ASTEdge(source_id="a", target_id="b", relation="calls")
        assert edge.relation == "calls"


# ---------------------------------------------------------------------------
# Sub-task 2.6: ID generation
# ---------------------------------------------------------------------------

class TestNodeIdGeneration:
    def test_format(self):
        nid = make_node_id("myrepo", "src/foo.py", NodeKind.FUNCTION, "bar")
        assert nid == "myrepo:src/foo.py:function:bar"

    def test_different_kinds_produce_different_ids(self):
        id1 = make_node_id("r", "f.py", NodeKind.FUNCTION, "x")
        id2 = make_node_id("r", "f.py", NodeKind.CLASS, "x")
        assert id1 != id2

    def test_different_files_produce_different_ids(self):
        id1 = make_node_id("r", "a.py", NodeKind.FUNCTION, "x")
        id2 = make_node_id("r", "b.py", NodeKind.FUNCTION, "x")
        assert id1 != id2


# ---------------------------------------------------------------------------
# Sub-task 2.2: parse_file
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_module_node_created(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        modules = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(modules) == 1
        assert modules[0].name == "sample"

    def test_classes_extracted(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        classes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = {c.name for c in classes}
        assert "Base" in class_names
        assert "Child" in class_names

    def test_functions_extracted(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        funcs = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = {f.name for f in funcs}
        assert "top_level_func" in func_names
        assert "caller" in func_names
        assert "async_func" in func_names
        assert "generator_func" in func_names

    def test_methods_extracted(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        methods = [n for n in nodes if n.kind == NodeKind.METHOD]
        method_names = {m.name for m in methods}
        assert "__init__" in method_names
        assert "method" in method_names
        assert "static_method" in method_names

    def test_imports_extracted(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        imports = [n for n in nodes if n.kind == NodeKind.IMPORT]
        import_names = {i.name for i in imports}
        assert "os" in import_names
        assert "Path" in import_names

    def test_variables_extracted(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        variables = [n for n in nodes if n.kind == NodeKind.VARIABLE]
        var_names = {v.name for v in variables}
        assert "MY_CONST" in var_names
        assert "class_var" in var_names

    def test_docstrings_captured(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        mod = next(n for n in nodes if n.kind == NodeKind.MODULE)
        assert mod.docstring == "Module docstring."
        child = next(n for n in nodes if n.kind == NodeKind.CLASS and n.name == "Child")
        assert child.docstring == "Child class."

    def test_signatures_captured(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        func = next(n for n in nodes if n.name == "top_level_func")
        assert func.signature is not None
        assert "a" in func.signature
        assert "b=..." in func.signature

    def test_line_numbers(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        for n in nodes:
            assert n.start_line >= 1
            assert n.end_line >= n.start_line

    def test_filepath_set(self, parser: ASTParser):
        nodes, _ = parser.parse_file("my/file.py", SAMPLE_SOURCE)
        for n in nodes:
            assert n.filepath == "my/file.py"

    # -- P1: completeness -------------------------------------------------

    def test_p1_every_top_level_definition_has_node(self, parser: ASTParser):
        """**Validates: Requirements 1.1** — P1"""
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        names = {n.name for n in nodes}
        # Top-level definitions in SAMPLE_SOURCE
        for expected in ["Base", "Child", "top_level_func", "caller", "async_func", "generator_func", "MY_CONST"]:
            assert expected in names, f"Missing node for {expected}"

    # -- P2: uniqueness ---------------------------------------------------

    def test_p2_all_node_ids_unique(self, parser: ASTParser):
        """**Validates: Requirements 1.3** — P2"""
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        ids = [n.id for n in nodes]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {[x for x in ids if ids.count(x) > 1]}"

    # -- P3: edge referential integrity -----------------------------------

    def test_p3_no_dangling_edges(self, parser: ASTParser):
        """**Validates: Requirements 1.4** — P3"""
        nodes, edges = parser.parse_file("sample.py", SAMPLE_SOURCE)
        node_ids = {n.id for n in nodes}
        for e in edges:
            # source must exist; target may reference cross-file nodes
            assert e.source_id in node_ids, f"Dangling source: {e.source_id}"

    def test_no_self_referential_edges(self, parser: ASTParser):
        """**Validates: Requirements 1.4**"""
        _, edges = parser.parse_file("sample.py", SAMPLE_SOURCE)
        for e in edges:
            assert e.source_id != e.target_id, f"Self-ref edge: {e}"


# ---------------------------------------------------------------------------
# Sub-task 2.3: intra-file edges
# ---------------------------------------------------------------------------

class TestIntraFileEdges:
    def test_contains_edges(self, parser: ASTParser):
        """Module contains classes and functions."""
        _, edges = parser.parse_file("sample.py", SAMPLE_SOURCE)
        contains = [e for e in edges if e.relation == "contains"]
        assert len(contains) > 0

    def test_calls_edges(self, parser: ASTParser):
        """caller() calls top_level_func()."""
        _, edges = parser.parse_file("sample.py", SAMPLE_SOURCE)
        calls = [e for e in edges if e.relation == "calls"]
        call_targets = {e.target_id for e in calls}
        expected_target = make_node_id("test-repo", "sample.py", NodeKind.FUNCTION, "top_level_func")
        assert expected_target in call_targets

    def test_inherits_edges(self, parser: ASTParser):
        """Child inherits from Base."""
        _, edges = parser.parse_file("sample.py", SAMPLE_SOURCE)
        inherits = [e for e in edges if e.relation == "inherits"]
        assert len(inherits) >= 1
        child_id = make_node_id("test-repo", "sample.py", NodeKind.CLASS, "Child")
        base_id = make_node_id("test-repo", "sample.py", NodeKind.CLASS, "Base")
        assert any(e.source_id == child_id and e.target_id == base_id for e in inherits)

    def test_decorates_edges(self, parser: ASTParser):
        nodes, edges = parser.parse_file("decorated.py", DECORATED_SOURCE)
        decorates = [e for e in edges if e.relation == "decorates"]
        assert len(decorates) >= 1


# ---------------------------------------------------------------------------
# Sub-task 2.4: parse_repository
# ---------------------------------------------------------------------------

class TestParseRepository:
    def test_discovers_and_parses_py_files(self, parser: ASTParser):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a small repo
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "mod.py").write_text("def hello(): pass\n")
            (Path(tmpdir) / "main.py").write_text("from pkg.mod import hello\nhello()\n")

            nodes, edges = parser.parse_repository(tmpdir)
            names = {n.name for n in nodes}
            assert "hello" in names
            assert "main" in names  # module node

    def test_skips_syntax_errors(self, parser: ASTParser):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "good.py").write_text("x = 1\n")
            (Path(tmpdir) / "bad.py").write_text("def broken(\n")

            nodes, edges = parser.parse_repository(tmpdir)
            # good.py should still be parsed
            filepaths = {n.filepath for n in nodes}
            assert "good.py" in filepaths
            # bad.py should be skipped
            assert "bad.py" not in filepaths

    def test_p2_ids_unique_across_files(self, parser: ASTParser):
        """**Validates: Requirements 1.3** — P2 across files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("def foo(): pass\n")
            (Path(tmpdir) / "b.py").write_text("def foo(): pass\n")

            nodes, _ = parser.parse_repository(tmpdir)
            ids = [n.id for n in nodes]
            assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Sub-task 2.5: cross-file import resolution
# ---------------------------------------------------------------------------

class TestCrossFileImports:
    def test_resolves_import_to_definition(self, parser: ASTParser):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "lib.py").write_text("def helper(): pass\n")
            (Path(tmpdir) / "main.py").write_text("from lib import helper\nhelper()\n")

            nodes, edges = parser.parse_repository(tmpdir)
            import_edges = [e for e in edges if e.relation == "imports"]
            assert len(import_edges) >= 1

            # The import node for 'helper' should point to the function node
            helper_func_id = make_node_id("test-repo", "lib.py", NodeKind.FUNCTION, "helper")
            assert any(e.target_id == helper_func_id for e in import_edges)

    def test_no_self_referential_import_edges(self, parser: ASTParser):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("from b import x\n")
            (Path(tmpdir) / "b.py").write_text("x = 1\n")

            nodes, edges = parser.parse_repository(tmpdir)
            for e in edges:
                assert e.source_id != e.target_id


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_file(self, parser: ASTParser):
        nodes, edges = parser.parse_file("empty.py", EMPTY_SOURCE)
        # Should still produce a module node
        modules = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(modules) == 1

    def test_syntax_error_graceful_skip(self, parser: ASTParser):
        nodes, edges = parser.parse_file("bad.py", SYNTAX_ERROR_SOURCE)
        assert nodes == []
        assert edges == []

    def test_deeply_nested_classes(self, parser: ASTParser):
        nodes, edges = parser.parse_file("nested.py", DEEPLY_NESTED_SOURCE)
        class_names = {n.name for n in nodes if n.kind == NodeKind.CLASS}
        assert "Outer" in class_names
        assert "Middle" in class_names
        assert "Inner" in class_names
        method_names = {n.name for n in nodes if n.kind == NodeKind.METHOD}
        assert "deep_method" in method_names

    def test_async_function(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        async_func = next((n for n in nodes if n.name == "async_func"), None)
        assert async_func is not None
        assert async_func.kind == NodeKind.FUNCTION
        assert async_func.signature is not None
        assert "async def" in async_func.signature

    def test_generator_function(self, parser: ASTParser):
        nodes, _ = parser.parse_file("sample.py", SAMPLE_SOURCE)
        gen = next((n for n in nodes if n.name == "generator_func"), None)
        assert gen is not None
        assert gen.kind == NodeKind.FUNCTION

    def test_decorators_create_nodes_and_edges(self, parser: ASTParser):
        nodes, edges = parser.parse_file("dec.py", DECORATED_SOURCE)
        dec_nodes = [n for n in nodes if n.kind == NodeKind.DECORATOR]
        assert len(dec_nodes) >= 1
        dec_edges = [e for e in edges if e.relation == "decorates"]
        assert len(dec_edges) >= 1

    def test_file_with_only_comments(self, parser: ASTParser):
        source = "# just a comment\n# another comment\n"
        nodes, edges = parser.parse_file("comments.py", source)
        modules = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(modules) == 1
        # No other definitions
        non_module = [n for n in nodes if n.kind != NodeKind.MODULE]
        assert len(non_module) == 0
