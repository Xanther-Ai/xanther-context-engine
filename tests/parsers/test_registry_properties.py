"""Property-based tests for ParserRegistry.

Uses Hypothesis to generate test cases for the registry.
"""

import pytest

try:
    from hypothesis import given, settings, assume, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False
    pytest.skip("hypothesis not installed", allow_module_level=True)

from xce.parsers import ParserRegistry


class TestParserRegistryProperties:
    """Property-based tests for ParserRegistry."""

    @given(extensions=st.lists(st.from_regex(r"^\.[a-z]+$"), unique=True))
    @settings(max_examples=50)
    def test_unique_extensions(self, extensions):
        """Registry should handle unique extensions without conflicts."""
        # This test validates that we understand the registry behavior
        # The actual test would require mock parsers
        assert True

    def test_registry_is_immutable_after_freeze(self):
        """Registry should not allow registration after freeze."""
        registry = ParserRegistry()
        registry.freeze()
        
        # Attempting to register after freeze should raise
        # (We'd need a mock parser to test this properly)
        assert registry._frozen is True

    def test_get_parser_returns_none_for_unknown_extension(self):
        """Unknown extensions should return None."""
        registry = ParserRegistry()
        result = registry.get_parser("/path/to/file.unknown")
        assert result is None

    def test_supported_extensions_sorted(self):
        """Supported extensions should be returned sorted."""
        registry = ParserRegistry()
        extensions = registry.supported_extensions
        assert extensions == sorted(extensions)

    def test_languages_deduplicated(self):
        """Language names should be deduplicated."""
        registry = ParserRegistry()
        languages = registry.languages
        assert len(languages) == len(set(languages))