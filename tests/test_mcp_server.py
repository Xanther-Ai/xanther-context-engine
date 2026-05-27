"""Unit tests for xce.mcp_server.XCEMCPServer.

Tests tool registration, routing, input validation, and response format.
Agents are mocked.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xce.mcp_server import (
    TOOLS,
    ValidationError,
    XCEMCPServer,
    validate_tool_arguments,
)
from xce.models import TraversalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(result: TraversalResult | None = None) -> MagicMock:
    agent = MagicMock()
    r = result or TraversalResult(
        contexts=[{"node_id": "n1", "type": "test"}],
        reasoning=["ok"],
        confidence=0.9,
        nodes_visited=1,
    )
    agent.query = AsyncMock(return_value=r)
    agent.trace = AsyncMock(return_value=r)
    agent.analyze = AsyncMock(return_value=r)
    agent.search = AsyncMock(return_value=r)
    return agent


def _make_server(agents: dict[str, Any] | None = None) -> XCEMCPServer:
    default_agents = {
        "architecture": _mock_agent(),
        "traceability": _mock_agent(),
        "impact": _mock_agent(),
        "search": _mock_agent(),
    }
    return XCEMCPServer(agents=agents or default_agents)


# ===================================================================
# 9.1  Tool registration
# ===================================================================


class TestToolRegistration:
    def test_five_tools_registered(self):
        server = _make_server()
        tools = server.get_tools()
        assert len(tools) == 5

    def test_tool_names(self):
        server = _make_server()
        names = {t.name for t in server.get_tools()}
        assert names == {
            "xce_architecture_context",
            "xce_trace",
            "xce_impact_analysis",
            "xce_search",
            "xce_index_repo",
        }

    def test_tools_have_input_schemas(self):
        server = _make_server()
        for tool in server.get_tools():
            assert tool.inputSchema is not None
            assert "properties" in tool.inputSchema
            assert "required" in tool.inputSchema

    def test_tools_have_descriptions(self):
        server = _make_server()
        for tool in server.get_tools():
            assert tool.description
            assert len(tool.description) > 5


# ===================================================================
# 9.2  Routing
# ===================================================================


class TestRouting:
    @pytest.mark.asyncio
    async def test_architecture_routing(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_architecture_context",
            {"file_or_symbol": "foo.py", "repo_id": "repo1"},
        )
        assert len(results) == 1
        data = json.loads(results[0].text)
        assert "contexts" in data
        assert "confidence" in data

    @pytest.mark.asyncio
    async def test_trace_routing(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_trace",
            {"source": "foo", "target_level": "hld", "repo_id": "repo1"},
        )
        data = json.loads(results[0].text)
        assert "contexts" in data

    @pytest.mark.asyncio
    async def test_impact_routing(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_impact_analysis",
            {"changed_files": ["a.py"], "repo_id": "repo1"},
        )
        data = json.loads(results[0].text)
        assert "contexts" in data

    @pytest.mark.asyncio
    async def test_search_routing(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_search",
            {"query": "find foo", "repo_id": "repo1"},
        )
        data = json.loads(results[0].text)
        assert "contexts" in data

    @pytest.mark.asyncio
    async def test_index_routing_no_indexer(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_index_repo",
            {"repo_path": "/tmp/repo", "repo_id": "repo1"},
        )
        data = json.loads(results[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_nonexistent",
            {"foo": "bar"},
        )
        data = json.loads(results[0].text)
        assert "error" in data


# ===================================================================
# 9.3  Input validation
# ===================================================================


class TestInputValidation:
    def test_missing_required_field(self):
        with pytest.raises(ValidationError, match="Missing required"):
            validate_tool_arguments("xce_architecture_context", {"repo_id": "r1"})

    def test_wrong_type_string(self):
        with pytest.raises(ValidationError, match="must be a string"):
            validate_tool_arguments(
                "xce_architecture_context",
                {"file_or_symbol": 123, "repo_id": "r1"},
            )

    def test_wrong_type_array(self):
        with pytest.raises(ValidationError, match="must be an array"):
            validate_tool_arguments(
                "xce_impact_analysis",
                {"changed_files": "not_a_list", "repo_id": "r1"},
            )

    def test_unknown_tool_name(self):
        with pytest.raises(ValidationError, match="Unknown tool"):
            validate_tool_arguments("xce_fake_tool", {})

    def test_valid_arguments_pass(self):
        # Should not raise
        validate_tool_arguments(
            "xce_architecture_context",
            {"file_or_symbol": "foo.py", "repo_id": "repo1"},
        )

    @pytest.mark.asyncio
    async def test_validation_error_returns_error_response(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_architecture_context",
            {"repo_id": "r1"},  # missing file_or_symbol
        )
        data = json.loads(results[0].text)
        assert "error" in data
        assert "Missing required" in data["error"]


# ===================================================================
# 9.5  Response format
# ===================================================================


class TestResponseFormat:
    @pytest.mark.asyncio
    async def test_response_is_text_content(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_search",
            {"query": "test", "repo_id": "r1"},
        )
        assert len(results) >= 1
        assert results[0].type == "text"
        # Should be valid JSON
        data = json.loads(results[0].text)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_error_response_format(self):
        server = _make_server()
        results = await server.handle_tool_call(
            "xce_architecture_context",
            {},  # missing all required
        )
        data = json.loads(results[0].text)
        assert "error" in data
        assert "tool" in data

    @pytest.mark.asyncio
    async def test_agent_exception_returns_error(self):
        agent = MagicMock()
        agent.query = AsyncMock(side_effect=RuntimeError("boom"))
        server = XCEMCPServer(agents={"architecture": agent})
        results = await server.handle_tool_call(
            "xce_architecture_context",
            {"file_or_symbol": "foo", "repo_id": "r1"},
        )
        data = json.loads(results[0].text)
        assert "error" in data
        assert "boom" in data["error"]


# ===================================================================
# Property-based tests
# ===================================================================


class TestPropertyMCPResponseValidity:
    """**Validates: Requirements 6.1** — P12: MCP response validity."""

    @given(
        tool_name=st.sampled_from([t.name for t in TOOLS]),
    )
    @settings(max_examples=20)
    @pytest.mark.asyncio
    async def test_always_returns_text_content(self, tool_name: str):
        """P12: Every tool call returns a non-empty list of TextContent."""
        server = _make_server()
        # Build minimal valid arguments for each tool
        args: dict[str, Any] = {}
        schema = next(t for t in TOOLS if t.name == tool_name).inputSchema
        for field in schema.get("required", []):  # type: ignore[union-attr]
            prop = schema["properties"][field]  # type: ignore[index]
            if prop.get("type") == "string":
                args[field] = "test"
            elif prop.get("type") == "array":
                args[field] = ["test"]
            elif prop.get("type") == "boolean":
                args[field] = True

        results = await server.handle_tool_call(tool_name, args)
        assert len(results) >= 1
        assert results[0].type == "text"
        # Must be valid JSON
        data = json.loads(results[0].text)
        assert isinstance(data, dict)
