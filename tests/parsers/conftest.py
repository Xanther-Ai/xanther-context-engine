"""Shared fixtures for parser tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from xce.parsers import ParserRegistry, get_default_registry
from xce.parsers.python_parser import PythonParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo_id() -> str:
    """A stable repo_id for deterministic test assertions."""
    return "test-repo"


@pytest.fixture
def registry() -> ParserRegistry:
    """A fresh default registry instance."""
    return get_default_registry()


@pytest.fixture
def python_parser() -> PythonParser:
    """A standalone PythonParser instance."""
    return PythonParser()


@pytest.fixture
def typescript_parser():
    """A standalone TypeScriptParser instance (skips if grammar not installed)."""
    try:
        from xce.parsers.typescript_parser import TypeScriptParser
        return TypeScriptParser()
    except ImportError:
        pytest.skip("tree-sitter-typescript not installed")


@pytest.fixture
def sample_python_source() -> str:
    """Read the sample Python fixture file."""
    return (FIXTURES_DIR / "sample.py").read_text()


@pytest.fixture
def sample_ts_source() -> str:
    """Read the sample TypeScript fixture file."""
    return (FIXTURES_DIR / "sample.ts").read_text()


def read_fixture(filename: str) -> str:
    """Helper to read a fixture file by name."""
    return (FIXTURES_DIR / filename).read_text()
