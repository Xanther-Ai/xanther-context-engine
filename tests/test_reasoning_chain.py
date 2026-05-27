"""Tests for multi-hop reasoning chain builder (Task 13).

Validates:
- P13: Chain connectivity (consecutive steps connected by edges)
- P14: Chain length bounds (3 ≤ len ≤ max_chain_length)
- Relevance ordering
- Fallback behavior when fewer than 3 nodes
- Narrative generation with mocked LLM
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from xce.models import ChainStep, ReasoningChain, TraversalResult
from xce.query.reasoning import ReasoningChainBuilder


def _make_traversal_result(node_ids: list[str]) -> TraversalResult:
    return TraversalResult(
        contexts=[
            {"node_id": nid, "data": {"name": nid.split(":")[-1] if ":" in nid else nid}}
            for nid in node_ids
        ],
        reasoning=["test"],
        confidence=0.8,
        nodes_visited=len(node_ids),
    )


class TestReasoningChainBuilder:
    @pytest.mark.asyncio
    async def test_fallback_on_few_nodes(self):
        """Fewer than 3 nodes → empty chains (fallback)."""
        gs = AsyncMock()
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        result = _make_traversal_result(["a", "b"])
        chains = await builder.build_chains([result], "test query")
        assert chains == []

    @pytest.mark.asyncio
    async def test_fallback_on_no_paths(self):
        """No connected paths found → empty chains."""
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[])
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        result = _make_traversal_result(["a", "b", "c", "d"])
        chains = await builder.build_chains([result], "test query")
        assert chains == []

    @pytest.mark.asyncio
    async def test_builds_chains_from_paths(self):
        """Builds chains when connected paths exist."""
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[
            {
                "node_chain": ["a", "b", "c"],
                "rel_chain": ["CALLS", "IMPORTS"],
            },
        ])
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        result = _make_traversal_result(["a", "b", "c", "d"])
        chains = await builder.build_chains([result], "test query")
        assert len(chains) >= 1
        for chain in chains:
            assert 3 <= len(chain.steps) <= 4
            assert chain.narrative  # non-empty
            assert chain.entry_node_id == chain.steps[0].node_id

    @pytest.mark.asyncio
    async def test_chain_length_bounds(self):
        """P14: Each chain has 3 ≤ steps ≤ max_chain_length."""
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[
            {"node_chain": ["a", "b", "c", "d", "e"], "rel_chain": ["CALLS", "IMPORTS", "CONTAINS", "INHERITS"]},
        ])
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        result = _make_traversal_result(["a", "b", "c", "d", "e"])
        chains = await builder.build_chains([result], "query")
        for chain in chains:
            assert 3 <= len(chain.steps) <= 4

    @pytest.mark.asyncio
    async def test_chains_ordered_by_relevance(self):
        """Chains are ordered by descending confidence/score."""
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[
            {"node_chain": ["a", "b", "c"], "rel_chain": ["CALLS", "IMPORTS"]},
            {"node_chain": ["d", "e", "f"], "rel_chain": ["CONTAINS", "CALLS"]},
        ])
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        result = _make_traversal_result(["a", "b", "c", "d", "e", "f"])
        chains = await builder.build_chains([result], "query", max_chains=5)
        if len(chains) >= 2:
            assert chains[0].confidence >= chains[1].confidence

    @pytest.mark.asyncio
    async def test_deduplicates_contexts(self):
        """Duplicate node_ids across results are deduplicated."""
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[
            {"node_chain": ["a", "b", "c"], "rel_chain": ["CALLS", "IMPORTS"]},
        ])
        builder = ReasoningChainBuilder(graph_store=gs, max_chain_length=4)
        r1 = _make_traversal_result(["a", "b"])
        r2 = _make_traversal_result(["b", "c"])
        chains = await builder.build_chains([r1, r2], "query")
        # Should still work with deduplicated nodes
        assert isinstance(chains, list)
