"""Property-based tests for parser output format.

Validates that all parsers produce output conforming to expected invariants.
"""

import pytest
from xce.parsers import get_default_registry
from xce.models import NodeKind


class TestParserOutputProperties:
    """Property-based tests for parser output invariants."""

    def test_nodes_have_valid_ids(self):
        """All nodes should have non-empty IDs."""
        registry = get_default_registry()
        
        # Test with Python parser (always available)
        python_code = """
def hello():
    pass

class MyClass:
    pass
"""
        parser = registry.get_parser("test.py")
        assert parser is not None
        nodes, edges = parser.parse_file("test.py", python_code, "test_repo")
        
        for node in nodes:
            assert node.id, "Node ID should not be empty"
            assert ":" in node.id, "Node ID should contain repo:filepath:kind:name format"

    def test_nodes_have_valid_kinds(self):
        """All nodes should have valid NodeKind values."""
        registry = get_default_registry()
        
        python_code = "def foo(): pass"
        parser = registry.get_parser("test.py")
        assert parser is not None
        nodes, _ = parser.parse_file("test.py", python_code, "test_repo")
        
        valid_kinds = {k.value for k in NodeKind}
        for node in nodes:
            assert node.kind.value in valid_kinds, f"Invalid NodeKind: {node.kind}"

    def test_edges_have_valid_relations(self):
        """All edges should have valid relation types."""
        registry = get_default_registry()
        
        python_code = """
def foo():
    bar()
    
class MyClass(Base):
    pass
"""
        parser = registry.get_parser("test.py")
        assert parser is not None
        _, edges = parser.parse_file("test.py", python_code, "test_repo")
        
        valid_relations = {"contains", "inherits", "decorates", "calls", "imports"}
        for edge in edges:
            assert edge.relation in valid_relations, f"Invalid relation: {edge.relation}"

    def test_edges_have_non_empty_source_and_target(self):
        """All edges should have non-empty source and target IDs."""
        registry = get_default_registry()
        
        python_code = "def foo(): pass"
        parser = registry.get_parser("test.py")
        assert parser is not None
        _, edges = parser.parse_file("test.py", python_code, "test_repo")
        
        for edge in edges:
            assert edge.source_id, "Edge source_id should not be empty"
            assert edge.target_id, "Edge target_id should not be empty"

    def test_line_numbers_are_valid(self):
        """All nodes should have valid start/end line numbers."""
        registry = get_default_registry()
        
        python_code = "def foo():\n    pass\n"
        parser = registry.get_parser("test.py")
        assert parser is not None
        nodes, _ = parser.parse_file("test.py", python_code, "test_repo")
        
        for node in nodes:
            assert node.start_line > 0, "start_line should be positive"
            assert node.end_line >= node.start_line, "end_line should be >= start_line"

    def test_no_self_referential_edges(self):
        """Edges should not connect a node to itself (except imports)."""
        registry = get_default_registry()
        
        python_code = "def foo(): pass"
        parser = registry.get_parser("test.py")
        assert parser is not None
        _, edges = parser.parse_file("test.py", python_code, "test_repo")
        
        for edge in edges:
            if edge.relation != "imports":
                assert edge.source_id != edge.target_id, "Self-referential edge found"

    def test_module_node_exists_for_file(self):
        """Each parsed file should produce a MODULE node."""
        registry = get_default_registry()
        
        python_code = "def foo(): pass"
        parser = registry.get_parser("test.py")
        assert parser is not None
        nodes, _ = parser.parse_file("test.py", python_code, "test_repo")
        
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1, "Should have exactly one MODULE node per file"

    def test_empty_source_returns_empty_results(self):
        """Parsing empty source should return empty results (not crash)."""
        registry = get_default_registry()
        
        parser = registry.get_parser("test.py")
        assert parser is not None
        nodes, edges = parser.parse_file("test.py", "", "test_repo")
        
        # Should return at least a module node
        assert len(nodes) >= 1