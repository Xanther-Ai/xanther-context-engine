"""Unit tests for xce.summarizer.ContextSummarizer.

Tests deduplication, token budget enforcement, ranking, and code snippet
preservation. LLM calls are mocked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xce.models import SummarizationRequest, SummarizedContext, TraversalResult
from xce.indexing.summarizer import RESERVED_FOR_SUMMARY, ContextSummarizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    contexts: list[dict[str, Any]] | None = None,
    confidence: float = 0.8,
) -> TraversalResult:
    return TraversalResult(
        contexts=contexts or [],
        reasoning=["test"],
        confidence=confidence,
        nodes_visited=len(contexts or []),
    )


def _make_ctx(
    node_id: str,
    *,
    score: float = 0.5,
    impact: float = 0.5,
    source_text: str = "",
    name: str = "",
) -> dict[str, Any]:
    data: dict[str, Any] = {"name": name or node_id}
    if source_text:
        data["source_text"] = source_text
        data["filepath"] = "test.py"
    return {
        "type": "test",
        "node_id": node_id,
        "score": score,
        "impact_score": impact,
        "data": data,
    }


# ===================================================================
# 8.2  Deduplication
# ===================================================================


class TestDeduplication:
    def test_removes_duplicate_node_ids(self):
        r1 = _make_result([_make_ctx("n1"), _make_ctx("n2")])
        r2 = _make_result([_make_ctx("n1"), _make_ctx("n3")])
        merged = ContextSummarizer._merge_and_deduplicate([r1, r2])
        node_ids = [c["node_id"] for c in merged]
        assert len(node_ids) == len(set(node_ids))
        assert set(node_ids) == {"n1", "n2", "n3"}

    def test_empty_results(self):
        merged = ContextSummarizer._merge_and_deduplicate([])
        assert merged == []

    def test_single_result_no_duplicates(self):
        r = _make_result([_make_ctx("a"), _make_ctx("b")])
        merged = ContextSummarizer._merge_and_deduplicate([r])
        assert len(merged) == 2

    def test_all_duplicates(self):
        r1 = _make_result([_make_ctx("x")])
        r2 = _make_result([_make_ctx("x")])
        r3 = _make_result([_make_ctx("x")])
        merged = ContextSummarizer._merge_and_deduplicate([r1, r2, r3])
        assert len(merged) == 1


# ===================================================================
# 8.3  Ranking
# ===================================================================


class TestRanking:
    def test_ranking_order(self):
        contexts = [
            _make_ctx("low", score=0.1, impact=0.1),
            _make_ctx("high", score=0.9, impact=0.9),
            _make_ctx("mid", score=0.5, impact=0.5),
        ]
        ranked = ContextSummarizer._rank_contexts(contexts, "test query")
        scores = [c["_combined_score"] for c in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0]["node_id"] == "high"
        assert ranked[-1]["node_id"] == "low"

    def test_combined_score_formula(self):
        ctx = _make_ctx("n1", score=0.8, impact=0.6)
        ranked = ContextSummarizer._rank_contexts([ctx], "q")
        expected = 0.6 * 0.8 + 0.4 * 0.6
        assert ranked[0]["_combined_score"] == pytest.approx(expected)

    def test_default_scores(self):
        """When no score/impact, defaults to 0.5 each."""
        ctx: dict[str, Any] = {"type": "t", "node_id": "n1", "data": {}}
        ranked = ContextSummarizer._rank_contexts([ctx], "q")
        assert ranked[0]["_combined_score"] == pytest.approx(0.6 * 0.5 + 0.4 * 0.5)


# ===================================================================
# 8.4  Token budget enforcement
# ===================================================================


class TestTokenBudget:
    def test_respects_budget(self):
        summarizer = ContextSummarizer(api_key="test")
        contexts = [
            _make_ctx(f"n{i}", source_text="x " * 100) for i in range(20)
        ]
        ranked = ContextSummarizer._rank_contexts(contexts, "q")
        selected, tokens = summarizer._select_within_budget(ranked, max_tokens=1000)
        assert tokens <= 1000 - RESERVED_FOR_SUMMARY

    def test_empty_when_budget_too_small(self):
        summarizer = ContextSummarizer(api_key="test")
        contexts = [_make_ctx("n1", source_text="hello world")]
        ranked = ContextSummarizer._rank_contexts(contexts, "q")
        selected, tokens = summarizer._select_within_budget(ranked, max_tokens=100)
        # Budget is 100 - 800 = negative, so nothing selected
        assert selected == []
        assert tokens == 0

    def test_selects_as_many_as_fit(self):
        summarizer = ContextSummarizer(api_key="test")
        # Each context is small
        contexts = [_make_ctx(f"n{i}", name=f"n{i}") for i in range(5)]
        ranked = ContextSummarizer._rank_contexts(contexts, "q")
        selected, tokens = summarizer._select_within_budget(ranked, max_tokens=4000)
        assert len(selected) == 5


# ===================================================================
# 8.5  Code snippet preservation
# ===================================================================


class TestCodeSnippetPreservation:
    def test_extracts_code_snippets(self):
        code = "def foo():\n    return 42"
        contexts = [_make_ctx("n1", source_text=code)]
        snippets = ContextSummarizer._extract_code_snippets(contexts)
        assert len(snippets) == 1
        assert snippets[0]["snippet"] == code
        assert snippets[0]["filepath"] == "test.py"

    def test_no_snippets_without_source(self):
        contexts = [_make_ctx("n1")]
        snippets = ContextSummarizer._extract_code_snippets(contexts)
        assert snippets == []


# ===================================================================
# 8.6  Full summarize() with mocked LLM
# ===================================================================


class TestSummarize:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        summarizer = ContextSummarizer(api_key="test")

        # Mock the LLM call
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary of the code context."
        summarizer._client = MagicMock()
        summarizer._client.chat = MagicMock()
        summarizer._client.chat.completions = MagicMock()
        summarizer._client.chat.completions.create = AsyncMock(return_value=mock_response)

        request = SummarizationRequest(
            traversal_results=[
                _make_result([
                    _make_ctx("n1", score=0.9, impact=0.8, source_text="def foo(): pass"),
                    _make_ctx("n2", score=0.5, impact=0.3),
                ]),
            ],
            query="What does foo do?",
            max_tokens=4000,
        )
        result = await summarizer.summarize(request)
        assert isinstance(result, SummarizedContext)
        assert result.summary == "Summary of the code context."
        assert result.token_count > 0
        assert len(result.relevant_code_snippets) == 1

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        summarizer = ContextSummarizer(api_key="test")
        summarizer._client = MagicMock()
        summarizer._client.chat = MagicMock()
        summarizer._client.chat.completions = MagicMock()
        summarizer._client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))

        request = SummarizationRequest(
            traversal_results=[_make_result([_make_ctx("n1", name="foo")])],
            query="test",
            max_tokens=4000,
        )
        result = await summarizer.summarize(request)
        # Should still return a result (fallback text)
        assert isinstance(result, SummarizedContext)
        assert result.summary != ""


# ===================================================================
# Property-based tests
# ===================================================================


class TestPropertyDeduplication:
    """**Validates: Requirements 5.1** — P8: No duplicate node_ids in output."""

    @given(
        node_ids=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
                min_size=1,
                max_size=10,
            ),
            min_size=0,
            max_size=30,
        ),
    )
    @settings(max_examples=100)
    def test_no_duplicate_node_ids(self, node_ids: list[str]):
        """P8: After deduplication, no node_id appears more than once."""
        results = [_make_result([_make_ctx(nid) for nid in node_ids])]
        merged = ContextSummarizer._merge_and_deduplicate(results)
        seen = [c["node_id"] for c in merged]
        assert len(seen) == len(set(seen))


class TestPropertyTokenBudget:
    """**Validates: Requirements 5.1** — P7: output ≤ max_tokens."""

    @given(
        max_tokens=st.integers(min_value=801, max_value=8000),
        n_contexts=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_selected_within_budget(self, max_tokens: int, n_contexts: int):
        """P7: Selected context tokens ≤ max_tokens - RESERVED_FOR_SUMMARY."""
        summarizer = ContextSummarizer(api_key="test")
        contexts = [_make_ctx(f"n{i}", name=f"node_{i}") for i in range(n_contexts)]
        ranked = ContextSummarizer._rank_contexts(contexts, "q")
        selected, tokens = summarizer._select_within_budget(ranked, max_tokens)
        assert tokens <= max_tokens - RESERVED_FOR_SUMMARY
