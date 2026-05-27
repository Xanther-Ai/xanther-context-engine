"""Tests for patch pattern index (Task 15).

Validates:
- P22: Similarity score bounds (0.0-1.0)
- Structural signature determinism
- Ranking order
- Upsert idempotency
- Retrieval with known similar patches
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from xce.models import PatchPattern
from xce.patch_pattern_index import PatchPatternIndex, _cosine_similarity
from xce.swe_bench_harness import SWEBenchInstance


def _make_instance(
    instance_id: str,
    repo: str = "django/django",
    patch: str = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
    problem: str = "Fix the filter bug",
) -> SWEBenchInstance:
    return SWEBenchInstance(
        instance_id=instance_id,
        repo=repo,
        base_commit="abc",
        problem_statement=problem,
        patch=patch,
        test_patch="",
    )


class TestStructuralSignature:
    """15.4 — Deterministic structural signature."""

    def test_deterministic(self):
        sig1 = PatchPatternIndex._compute_structural_signature(
            ["a.py", "b.py"], ["foo", "bar"], "bugfix",
        )
        sig2 = PatchPatternIndex._compute_structural_signature(
            ["b.py", "a.py"], ["bar", "foo"], "bugfix",
        )
        assert sig1 == sig2  # Order shouldn't matter (sorted)

    def test_different_inputs_different_sigs(self):
        sig1 = PatchPatternIndex._compute_structural_signature(
            ["a.py"], ["foo"], "bugfix",
        )
        sig2 = PatchPatternIndex._compute_structural_signature(
            ["b.py"], ["bar"], "bugfix",
        )
        assert sig1 != sig2


class TestIndexGoldPatches:
    @pytest.mark.asyncio
    async def test_indexes_instances(self):
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        instances = [_make_instance("i-1"), _make_instance("i-2")]
        count = await index.index_gold_patches(instances)
        assert count == 2

    @pytest.mark.asyncio
    async def test_upsert_idempotency(self):
        """15.7 — Re-indexing same instance updates, no duplicates."""
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        inst = _make_instance("i-1")
        await index.index_gold_patches([inst])
        await index.index_gold_patches([inst])
        # Should still have exactly 1 pattern
        assert len(index._patterns) == 1


class TestFindSimilar:
    @pytest.mark.asyncio
    async def test_empty_index_returns_empty(self):
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        results = await index.find_similar("problem", ["file.py"])
        assert results == []

    @pytest.mark.asyncio
    async def test_finds_similar_by_files(self):
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        await index.index_gold_patches([
            _make_instance("i-1", patch="--- a/models.py\n+++ b/models.py\n@@ -1 +1 @@\n-x\n+y"),
            _make_instance("i-2", patch="--- a/views.py\n+++ b/views.py\n@@ -1 +1 @@\n-x\n+y"),
        ])
        results = await index.find_similar("fix models", ["models.py"])
        assert len(results) >= 1
        # The one with models.py should rank higher
        assert results[0].pattern.instance_id == "i-1"

    @pytest.mark.asyncio
    async def test_similarity_score_bounds(self):
        """P22: All similarity scores in [0.0, 1.0]."""
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        await index.index_gold_patches([_make_instance("i-1")])
        results = await index.find_similar("problem", ["file.py"])
        for r in results:
            assert 0.0 <= r.similarity_score <= 1.0

    @pytest.mark.asyncio
    async def test_top_k_limit(self):
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        for i in range(10):
            await index.index_gold_patches([_make_instance(f"i-{i}")])
        results = await index.find_similar("problem", ["file.py"], top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_results_ordered_by_score(self):
        gs = AsyncMock()
        index = PatchPatternIndex(graph_store=gs)
        await index.index_gold_patches([
            _make_instance("i-1", patch="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y"),
            _make_instance("i-2", patch="--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y"),
        ])
        results = await index.find_similar("fix", ["a.py", "b.py"])
        if len(results) >= 2:
            assert results[0].similarity_score >= results[1].similarity_score


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0

    def test_different_lengths(self):
        assert _cosine_similarity([1, 2], [1, 2, 3]) == 0.0
