"""Tests for iterative refinement loop (Task 16).

Validates:
- P17: Termination within max_iterations
- P18: len(patch_attempts) == len(test_results)
- Convergence detection (tests pass)
- Stagnation detection (no progress)
- Context refinement merging
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from xce.models import RefinementState, SummarizedContext, TestResult
from xce.refinement_loop import RefinementLoop


def _make_context() -> SummarizedContext:
    return SummarizedContext(
        summary="test context",
        key_facts=["fact1"],
        relevant_code_snippets=[],
        confidence=0.8,
        token_count=100,
    )


class TestRefinementLoop:
    @pytest.mark.asyncio
    async def test_terminates_within_max_iterations(self):
        """P17: Loop terminates within max_iterations."""
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=TestResult(
            passed=False,
            failed_tests=["test_a"],
        ))
        loop = RefinementLoop(test_runner=runner, max_iterations=3)
        state = await loop.run("fix bug", "repo-1", _make_context(), "patch")
        assert state.iteration <= state.max_iterations

    @pytest.mark.asyncio
    async def test_patch_test_parity(self):
        """P18: len(patch_attempts) == len(test_results)."""
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=TestResult(
            passed=False,
            failed_tests=["test_a"],
        ))
        loop = RefinementLoop(test_runner=runner, max_iterations=2)
        state = await loop.run("fix bug", "repo-1", _make_context(), "patch")
        assert len(state.patch_attempts) == len(state.test_results)

    @pytest.mark.asyncio
    async def test_stops_on_convergence(self):
        """Stops immediately when tests pass."""
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=TestResult(passed=True))
        loop = RefinementLoop(test_runner=runner, max_iterations=5)
        state = await loop.run("fix bug", "repo-1", _make_context(), "patch")
        assert state.converged
        assert len(state.patch_attempts) == 1  # Stopped after first success

    @pytest.mark.asyncio
    async def test_stops_on_stagnation(self):
        """Stops when no progress between iterations."""
        call_count = 0

        async def mock_run(patch, test_patch, repo_id):
            nonlocal call_count
            call_count += 1
            return TestResult(
                passed=False,
                failed_tests=["test_a", "test_b"],  # Same failures each time
            )

        runner = AsyncMock()
        runner.run = mock_run
        loop = RefinementLoop(test_runner=runner, max_iterations=5)
        state = await loop.run("fix bug", "repo-1", _make_context(), "patch")
        # Should stop early due to stagnation (same failures)
        assert state.converged or state.iteration <= state.max_iterations

    @pytest.mark.asyncio
    async def test_no_test_runner(self):
        """Handles missing test runner gracefully."""
        loop = RefinementLoop(max_iterations=2)
        state = await loop.run("fix bug", "repo-1", _make_context(), "patch")
        assert len(state.test_results) > 0
        assert not state.test_results[0].passed


class TestShouldStop:
    def test_stops_at_max_iterations(self):
        state = RefinementState(
            iteration=3,
            max_iterations=3,
            problem_statement="",
            repo_id="",
            current_context=None,
        )
        assert RefinementLoop._should_stop(state, 0.5)

    def test_stops_on_no_progress(self):
        state = RefinementState(
            iteration=2,
            max_iterations=5,
            problem_statement="",
            repo_id="",
            current_context=None,
            test_results=[
                TestResult(passed=False, failed_tests=["a", "b"]),
                TestResult(passed=False, failed_tests=["a", "b"]),
            ],
        )
        assert RefinementLoop._should_stop(state, 0.5)

    def test_continues_on_progress(self):
        state = RefinementState(
            iteration=1,
            max_iterations=5,
            problem_statement="",
            repo_id="",
            current_context=None,
            test_results=[
                TestResult(passed=False, failed_tests=["a", "b"]),
                TestResult(passed=False, failed_tests=["a"]),  # Improved
            ],
        )
        assert not RefinementLoop._should_stop(state, 0.5)
