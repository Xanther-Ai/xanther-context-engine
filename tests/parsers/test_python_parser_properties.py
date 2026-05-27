"""Property-based tests for Python parser.

Uses Hypothesis to generate valid Python code and verify parsing behavior.
"""

import pytest

try:
    from hypothesis import given, settings, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False
    pytest.skip("hypothesis not installed", allow_module_level=True)

from xce.parsers import get_default_registry
from xce.models import NodeKind


# Strategies for generating valid Python code fragments
@st.composite
def python_identifier(draw):
    """Generate valid Python identifiers."""
    return draw(st.from_regex(r"^[a-zA-Z_][a-zA-Z0-9_]*$").filter(lambda x: x not in ("if", "else", "for", "while", "class", "def", "import", "from")))


class TestPythonParserProperties:
    """Property-based tests for Python parser."""

    @given(func_name=python_identifier())
    @settings(max_examples=50)
    def test_parse_simple_function(self, func_name):
        """Parser should correctly handle simple function definitions."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = f"def {func_name}():\n    pass"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        # Should have at least module and function nodes
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) >= 1
        assert any(n.name == func_name for n in func_nodes)

    @given(class_name=st.from_regex(r"^[A-Z][a-zA-Z0-9_]*$"))
    @settings(max_examples=50)
    def test_parse_simple_class(self, class_name):
        """Parser should correctly handle simple class definitions."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = f"class {class_name}:\n    pass"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) >= 1
        assert any(n.name == class_name for n in class_nodes)

    def test_parse_function_with_parameters(self):
        """Parser should extract function parameters in signature."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def greet(name, greeting='hello'):\n    print(f'{greeting}, {name}')"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) >= 1
        
        func = func_nodes[0]
        assert func.signature is not None
        assert "name" in func.signature
        assert "greeting" in func.signature

    def test_parse_class_with_inheritance(self):
        """Parser should detect class inheritance."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "class Child(Parent):\n    pass"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) >= 1
        
        # Check for inheritance edge
        inherits_edges = [e for e in edges if e.relation == "inherits"]
        assert len(inherits_edges) >= 1

    def test_parse_function_with_decorator(self):
        """Parser should detect function decorators."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "@staticmethod\ndef helper():\n    pass"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        # Check for decorator edge
        decorates_edges = [e for e in edges if e.relation == "decorates"]
        assert len(decorates_edges) >= 1

    def test_parse_import_statements(self):
        """Parser should extract import statements."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "import os\nfrom pathlib import Path"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        import_nodes = [n for n in nodes if n.kind == NodeKind.IMPORT]
        # May have 1-2 imports depending on how they're parsed
        assert len(import_nodes) >= 1

    def test_parse_nested_definitions(self):
        """Parser should handle nested functions and classes."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = """
class Outer:
    def method(self):
        def inner():
            pass
"""
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        # Should have class, method, and function nodes
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        method_nodes = [n for n in nodes if n.kind == NodeKind.METHOD]
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        
        assert len(class_nodes) >= 1
        assert len(method_nodes) >= 1
        assert len(func_nodes) >= 1

    def test_parse_async_function(self):
        """Parser should handle async functions."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "async def fetch():\n    await asyncio.sleep(1)"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) >= 1
        assert "async" in (func_nodes[0].signature or "")

    def test_invalid_syntax_returns_empty(self):
        """Parser should gracefully handle syntax errors."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def unclosed(:\n    pass"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        # Should return at least module node, possibly empty function list
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) >= 1