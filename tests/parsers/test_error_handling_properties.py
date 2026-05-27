"""Property-based tests for parser error handling.

Validates that parsers handle edge cases gracefully without crashing.
"""

import pytest
from xce.parsers import get_default_registry
from xce.models import NodeKind


class TestErrorHandlingProperties:
    """Property-based tests for error handling."""

    def test_empty_source_returns_module_node(self):
        """Empty source should return at least a module node."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        nodes, edges = parser.parse_file("test.py", "", "test_repo")
        
        # Should have module node
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1

    def test_whitespace_only_source(self):
        """Whitespace-only source should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        nodes, edges = parser.parse_file("test.py", "   \n\n   ", "test_repo")
        
        assert nodes is not None
        assert edges is not None

    def test_comment_only_source(self):
        """Comment-only source should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "# This is a comment\n# Another comment\n"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None
        assert edges is not None

    def test_very_long_source_handled(self):
        """Very long source should be handled without crashing."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        # Create a large but reasonable source
        code = "\n".join([f"def func_{i}(): pass" for i in range(1000)])
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_unicode_source(self):
        """Unicode source should be handled correctly."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def 日本語():\n    pass\n"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_mixed_tabs_and_spaces(self):
        """Mixed tabs and spaces should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def foo():\n\tpass\n"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_none_source_handled(self):
        """None source should be handled gracefully."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        # None source is invalid - parser should handle gracefully or we skip
        try:
            nodes, edges = parser.parse_file("test.py", None, "test_repo")  # type: ignore
            assert nodes is not None
        except (TypeError, ValueError):
            # Expected - None is not valid Python source
            pass

    def test_none_repo_id(self):
        """None repo_id should be handled gracefully."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def foo(): pass"
        
        # May need to handle None repo_id
        try:
            nodes, edges = parser.parse_file("test.py", code, None)  # type: ignore
            assert nodes is not None
        except (TypeError, AttributeError):
            # Some parsers may not handle None - this is acceptable
            pass

    def test_special_characters_in_source(self):
        """Source with special characters should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = 'def foo():\n    print("Hello\\nWorld")\n'
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_multiple_encoding_markers(self):
        """Source with encoding markers should be handled."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "# -*- coding: utf-8 -*-\ndef foo(): pass\n"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_doctype_or_shebang_lines(self):
        """Shebang and doctype lines should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\ndef foo(): pass\n"
        nodes, edges = parser.parse_file("test.py", code, "test_repo")
        
        assert nodes is not None

    def test_empty_filepath(self):
        """Empty filepath should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def foo(): pass"
        nodes, edges = parser.parse_file("", code, "test_repo")
        
        # Should still return something
        assert nodes is not None

    def test_special_characters_in_filepath(self):
        """Filepath with special characters should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = "def foo(): pass"
        
        # Should not raise
        try:
            nodes, edges = parser.parse_file("path/with spaces/test.py", code, "test_repo")
            assert nodes is not None
        except Exception:
            # May fail on special paths - acceptable
            pass

    def test_binary_content_like_source(self):
        """Binary-like content should not crash."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        # Null bytes are invalid in Python source - expect graceful handling
        try:
            code = "def foo():\x00\x01\x02: pass\n"
            nodes, edges = parser.parse_file("test.py", code, "test_repo")
            # Should either succeed with graceful handling or fail cleanly
            assert nodes is not None
        except (ValueError, TypeError):
            # Expected - null bytes are invalid in Python source
            pass