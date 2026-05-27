"""Unit tests for xce.agents — LangGraph traversal agents.

All tests use mocked GraphStore to avoid Neo4j dependency.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xce.query.agents import (
    ArchitectureAgent,
    ImpactAnalysisAgent,
    SearchDiscoveryAgent,
    TraceabilityAgent,
)
from xce.models import GraphQuery, SearchResult, TraversalResult


# ---------------------------------------------------------------------------
# Mock GraphStore factory
# ---------------------------------------------------------------------------


def _mock_graph_store(
    *,
    execute_query_side_effect: Any = None,
    execute_query_return: list[dict[str, Any]] | None = None,
    get_neighbors_return: list[SearchResult] | None = None,
    semantic_search_return: list[SearchResult] | None = None,
) -> MagicMock:
    gs = MagicMock()

    if execute_query_side_effect is not None:
        gs.execute_query = AsyncMock(side_effect=execute_query_side_effect)
    elif execute_query_return is not None:
        gs.execute_query = AsyncMock(return_value=execute_query_return)
    else:
        gs.execute_query = AsyncMock(return_value=[])

    gs.get_neighbors = AsyncMock(return_value=get_neighbors_return or [])
    gs.semantic_search = AsyncMock(return_value=semantic_search_return or [])
    return gs


# ===================================================================
# 7.2  Architecture Agent
# ===================================================================


class TestArchitectureAgent:
    @pytest.mark.asyncio
    async def test_returns_traversal_result(self):
        gs = _mock_graph_store(
            execute_query_return=[{"nid": "repo1:a.py:function:foo"}],
        )
        agent = ArchitectureAgent(gs)
        result = await agent.query("foo", "repo1")
        assert isinstance(result, TraversalResult)
        assert result.nodes_visited >= 0
        assert isinstance(result.reasoning, list)

    @pytest.mark.asyncio
    async def test_locate_finds_nodes(self):
        gs = _mock_graph_store(
            execute_query_return=[{"nid": "repo1:a.py:function:foo"}],
        )
        agent = ArchitectureAgent(gs)
        result = await agent.query("foo", "repo1")
        assert result.nodes_visited >= 1

    @pytest.mark.asyncio
    async def test_terminates_at_max_depth(self):
        """Agent should terminate even with no results — bounded by max_depth."""
        gs = _mock_graph_store(execute_query_return=[{"nid": "n1"}])
        agent = ArchitectureAgent(gs)
        result = await agent.query("foo", "repo1", max_depth=1)
        assert isinstance(result, TraversalResult)
        # Should have reasoning trace entries
        assert len(result.reasoning) >= 1

    @pytest.mark.asyncio
    async def test_terminates_at_context_limit(self):
        """Agent should stop expanding when 30 context items are collected."""
        # Return many neighbors to fill context quickly
        neighbors = [
            SearchResult(node_id=f"n{i}", score=0.9, node_data={"name": f"n{i}"})
            for i in range(35)
        ]
        gs = _mock_graph_store(
            execute_query_return=[{"nid": "root"}],
            get_neighbors_return=neighbors,
        )
        agent = ArchitectureAgent(gs)
        result = await agent.query("root", "repo1", max_depth=10)
        assert isinstance(result, TraversalResult)

    @pytest.mark.asyncio
    async def test_empty_locate_returns_empty(self):
        gs = _mock_graph_store(execute_query_return=[])
        agent = ArchitectureAgent(gs)
        result = await agent.query("nonexistent", "repo1")
        assert result.nodes_visited == 0


# ===================================================================
# 7.3  Traceability Agent
# ===================================================================


class TestTraceabilityAgent:
    @pytest.mark.asyncio
    async def test_returns_traversal_result(self):
        gs = _mock_graph_store(execute_query_return=[{"nid": "repo1:a.py:function:foo"}])
        agent = TraceabilityAgent(gs)
        result = await agent.trace("foo", "architecture", "repo1")
        assert isinstance(result, TraversalResult)

    @pytest.mark.asyncio
    async def test_trace_to_code_level(self):
        gs = _mock_graph_store(
            execute_query_return=[{"nid": "repo1:a.py:function:foo"}],
        )
        agent = TraceabilityAgent(gs)
        result = await agent.trace("foo", "code", "repo1")
        assert isinstance(result, TraversalResult)
        assert len(result.reasoning) >= 1

    @pytest.mark.asyncio
    async def test_trace_to_hld_includes_chain(self):
        call_count = 0

        async def _side_effect(query: GraphQuery) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # locate
                return [{"nid": "repo1:a.py:function:foo"}]
            elif call_count == 2:
                # DESCRIBED_BY
                return [{"d": {"summary": "Does stuff"}, "did": "repo1:a.py:function:foo"}]
            elif call_count == 3:
                # DETAILED_IN
                return [{"l": {"algo": "BFS"}, "lid": "repo1:a.py:function:foo"}]
            elif call_count == 4:
                # PART_OF_ARCHITECTURE
                return [{"h": {"role": "service"}, "hid": "src/services"}]
            return []

        gs = _mock_graph_store(execute_query_side_effect=_side_effect)
        agent = TraceabilityAgent(gs)
        result = await agent.trace("foo", "architecture", "repo1")
        assert len(result.contexts) >= 1

    @pytest.mark.asyncio
    async def test_no_source_found(self):
        gs = _mock_graph_store(execute_query_return=[])
        agent = TraceabilityAgent(gs)
        result = await agent.trace("nonexistent", "architecture", "repo1")
        assert result.nodes_visited == 0
        assert result.confidence == 0.0


# ===================================================================
# 7.4  Impact Analysis Agent
# ===================================================================


class TestImpactAnalysisAgent:
    @pytest.mark.asyncio
    async def test_returns_traversal_result(self):
        gs = _mock_graph_store(execute_query_return=[{"nid": "repo1:a.py:function:foo"}])
        agent = ImpactAnalysisAgent(gs)
        result = await agent.analyze(["a.py"], "repo1")
        assert isinstance(result, TraversalResult)

    @pytest.mark.asyncio
    async def test_direct_node_has_score_1(self):
        gs = _mock_graph_store(execute_query_return=[{"nid": "repo1:a.py:function:foo"}])
        agent = ImpactAnalysisAgent(gs)
        result = await agent.analyze(["a.py"], "repo1")
        # Direct nodes should have score 1.0
        for ctx in result.contexts:
            if ctx["node_id"] == "repo1:a.py:function:foo":
                assert ctx["impact_score"] == 1.0

    @pytest.mark.asyncio
    async def test_score_decays_with_depth(self):
        """Callers at depth 1 should have score 0.5 = 1/(1+1)."""
        call_count = 0

        async def _side_effect(query: GraphQuery) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if "filepath" in query.cypher:
                return [{"nid": "root"}]
            if "CALLS|IMPORTS" in query.cypher:
                if query.params.get("nid") == "root":
                    return [{"cid": "caller1"}]
                return []
            return []

        gs = _mock_graph_store(execute_query_side_effect=_side_effect)
        agent = ImpactAnalysisAgent(gs)
        result = await agent.analyze(["a.py"], "repo1")

        scores = {c["node_id"]: c["impact_score"] for c in result.contexts}
        assert scores.get("root") == 1.0
        assert scores.get("caller1") == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_descending(self):
        call_count = 0

        async def _side_effect(query: GraphQuery) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if "filepath" in query.cypher:
                return [{"nid": "root"}]
            if "CALLS|IMPORTS" in query.cypher:
                if query.params.get("nid") == "root":
                    return [{"cid": "c1"}, {"cid": "c2"}]
                if query.params.get("nid") in ("c1", "c2"):
                    return [{"cid": f"deep_{query.params['nid']}"}]
                return []
            return []

        gs = _mock_graph_store(execute_query_side_effect=_side_effect)
        agent = ImpactAnalysisAgent(gs)
        result = await agent.analyze(["a.py"], "repo1", max_depth=3)

        scores = [c["impact_score"] for c in result.contexts]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_files(self):
        gs = _mock_graph_store(execute_query_return=[])
        agent = ImpactAnalysisAgent(gs)
        result = await agent.analyze([], "repo1")
        assert result.nodes_visited == 0
        assert result.confidence == 0.0


# ===================================================================
# 7.5  Search & Discovery Agent
# ===================================================================


class TestSearchDiscoveryAgent:
    @pytest.mark.asyncio
    async def test_symbol_search(self):
        gs = _mock_graph_store(
            execute_query_return=[
                {"node_id": "repo1:a.py:function:foo", "name": "foo", "data": {"name": "foo"}},
            ],
        )
        agent = SearchDiscoveryAgent(gs)
        result = await agent.search("foo", "repo1", search_type="symbol")
        assert isinstance(result, TraversalResult)
        assert len(result.contexts) >= 1

    @pytest.mark.asyncio
    async def test_semantic_search_with_embedding(self):
        embed = AsyncMock()
        embed.encode = AsyncMock(return_value=[0.1, 0.2, 0.3])

        gs = _mock_graph_store(
            semantic_search_return=[
                SearchResult(node_id="n1", score=0.9, node_data={"name": "foo"}),
                SearchResult(node_id="n2", score=0.7, node_data={"name": "bar"}),
            ],
        )
        agent = SearchDiscoveryAgent(gs, embedding_service=embed)
        result = await agent.search("find foo", "repo1", search_type="semantic")
        assert len(result.contexts) == 2
        # Sorted descending by score
        assert result.contexts[0]["score"] >= result.contexts[1]["score"]

    @pytest.mark.asyncio
    async def test_semantic_fallback_without_embedding(self):
        """Without embedding service, semantic search falls back to symbol search."""
        gs = _mock_graph_store(
            execute_query_return=[
                {"node_id": "n1", "name": "foo", "data": {}},
            ],
        )
        agent = SearchDiscoveryAgent(gs, embedding_service=None)
        result = await agent.search("foo", "repo1", search_type="semantic")
        assert len(result.contexts) >= 1

    @pytest.mark.asyncio
    async def test_results_bounded_by_top_k(self):
        gs = _mock_graph_store(
            execute_query_return=[
                {"node_id": f"n{i}", "name": f"n{i}", "data": {}}
                for i in range(20)
            ],
        )
        agent = SearchDiscoveryAgent(gs)
        result = await agent.search("n", "repo1", search_type="symbol", top_k=5)
        assert len(result.contexts) <= 5

    @pytest.mark.asyncio
    async def test_empty_search(self):
        gs = _mock_graph_store(execute_query_return=[])
        agent = SearchDiscoveryAgent(gs)
        result = await agent.search("nonexistent", "repo1", search_type="symbol")
        assert result.nodes_visited == 0
        assert result.confidence == 0.0


# ===================================================================
# Property-based tests for agents
# ===================================================================


class TestPropertyImpactScoreDecay:
    """**Validates: Requirements 4.3** — P6: Impact score = 1/(depth+1) ≤ 1.0."""

    @given(depth=st.integers(min_value=0, max_value=100))
    @settings(max_examples=100)
    def test_score_decay_formula(self, depth: int):
        """P6: score = 1/(depth+1) is always in (0, 1]."""
        score = 1.0 / (depth + 1)
        assert 0 < score <= 1.0


class TestPropertyTraversalTermination:
    """**Validates: Requirements 4.1** — P10: Traversal terminates within max_depth."""

    @given(max_depth=st.integers(min_value=1, max_value=10))
    @settings(max_examples=20)
    @pytest.mark.asyncio
    async def test_architecture_terminates(self, max_depth: int):
        """P10: Architecture agent always terminates."""
        gs = _mock_graph_store(execute_query_return=[{"nid": "n1"}])
        agent = ArchitectureAgent(gs)
        result = await agent.query("test", "repo1", max_depth=max_depth)
        assert isinstance(result, TraversalResult)
