"""Iterative refinement loop for the Xanther Context Engine.

Orchestrates: context → patch → test → analyze failure → refine context → retry.
Maximum 3 iterations. Stops on convergence or stagnation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from xce.models import RefinementState, SummarizedContext, TestResult

logger = logging.getLogger(__name__)


class RefinementLoop:
    """Iterative refinement: generate patch, test, analyze, refine."""

    # ------------------------------------------------------------------
    # 16.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        mcp_server: Any = None,
        impact_agent: Any = None,
        summarizer: Any = None,
        test_runner: Any = None,
        max_iterations: int = 3,
    ) -> None:
        self._mcp = mcp_server
        self._impact = impact_agent
        self._summarizer = summarizer
        self._test_runner = test_runner
        self._max_iterations = max_iterations

    # ------------------------------------------------------------------
    # 16.3  run — iterative cycle
    # ------------------------------------------------------------------

    async def run(
        self,
        problem_statement: str,
        repo_id: str,
        initial_context: Any,
        test_patch: str,
    ) -> RefinementState:
        """Run the iterative refinement loop.

        Returns final state with best patch and convergence info.
        """
        state = RefinementState(
            iteration=0,
            max_iterations=self._max_iterations,
            problem_statement=problem_statement,
            repo_id=repo_id,
            current_context=initial_context,
        )

        prev_pass_rate = 0.0

        while state.iteration < state.max_iterations and not state.converged:
            # Step 1: Generate patch
            patch = await self._generate_patch(state)
            state.patch_attempts.append(patch)

            # Step 2: Run tests
            test_result = await self._run_tests(patch, test_patch, repo_id)
            state.test_results.append(test_result)

            # Step 3: Check convergence
            if test_result.passed:
                state.converged = True
                break

            # Step 4: Check for progress
            if self._should_stop(state, prev_pass_rate):
                state.converged = True  # stagnated
                break

            total_tests = len(test_result.failed_tests) + (1 if not test_result.failed_tests else 0)
            current_pass_rate = 1.0 - (len(test_result.failed_tests) / max(total_tests, 1))
            prev_pass_rate = current_pass_rate

            # Step 5: Analyze failure
            analysis = await self._analyze_failure(test_result, state.current_context, patch)
            state.failure_analysis.append(analysis)

            # Step 6: Refine context
            state.current_context = await self._refine_context(
                analysis, state.current_context, repo_id,
            )

            state.iteration += 1

        return state

    # ------------------------------------------------------------------
    # 16.4  _generate_patch
    # ------------------------------------------------------------------

    async def _generate_patch(self, state: RefinementState) -> str:
        """Generate a patch using the coding agent with current context."""
        if self._mcp is None:
            return ""

        try:
            result = await self._mcp.handle_tool_call(
                "xce_search",
                {
                    "query": state.problem_statement,
                    "repo_id": state.repo_id,
                    "search_type": "semantic",
                },
            )
            # In a real implementation, this would call the coding agent
            # with the context to generate a patch
            return f"# Patch attempt {state.iteration + 1}"
        except Exception as exc:
            logger.warning("Patch generation failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # 16.5  _run_tests
    # ------------------------------------------------------------------

    async def _run_tests(
        self,
        patch: str,
        test_patch: str,
        repo_id: str,
    ) -> TestResult:
        """Apply patch and run tests. Returns TestResult."""
        if self._test_runner is None:
            return TestResult(passed=False, failed_tests=["no_test_runner"])

        try:
            return await self._test_runner.run(patch, test_patch, repo_id)
        except Exception as exc:
            logger.warning("Test execution failed: %s", exc)
            return TestResult(
                passed=False,
                failed_tests=["execution_error"],
                error_messages=[str(exc)],
            )

    # ------------------------------------------------------------------
    # 16.6  _analyze_failure
    # ------------------------------------------------------------------

    async def _analyze_failure(
        self,
        test_result: TestResult,
        current_context: Any,
        patch: str,
    ) -> str:
        """Use Impact Analysis Agent to diagnose test failures."""
        if self._impact is None:
            return f"Tests failed: {test_result.failed_tests}"

        try:
            # Query impact agent for failure analysis
            failed_info = ", ".join(test_result.failed_tests[:5])
            error_info = "; ".join(test_result.error_messages[:3])
            return f"Failure analysis: {failed_info}. Errors: {error_info}"
        except Exception as exc:
            logger.warning("Failure analysis failed: %s", exc)
            return f"Analysis unavailable: {exc}"

    # ------------------------------------------------------------------
    # 16.7  _refine_context
    # ------------------------------------------------------------------

    async def _refine_context(
        self,
        failure_analysis: str,
        current_context: Any,
        repo_id: str,
    ) -> Any:
        """Refine context based on failure analysis.

        Queries for additional context targeting failure points,
        merges with existing context.
        """
        if self._mcp is None or self._summarizer is None:
            return current_context

        try:
            additional = await self._mcp.handle_tool_call(
                "xce_search",
                {
                    "query": failure_analysis,
                    "repo_id": repo_id,
                    "search_type": "semantic",
                },
            )
            # In a real implementation, merge additional context
            return current_context
        except Exception as exc:
            logger.warning("Context refinement failed: %s", exc)
            return current_context

    # ------------------------------------------------------------------
    # 16.8  _should_stop
    # ------------------------------------------------------------------

    @staticmethod
    def _should_stop(state: RefinementState, prev_pass_rate: float) -> bool:
        """Stop if max iterations reached or no progress."""
        if state.iteration >= state.max_iterations:
            return True

        if state.iteration > 0 and len(state.test_results) >= 2:
            latest = state.test_results[-1]
            previous = state.test_results[-2]
            # No progress if same or more failures
            if len(latest.failed_tests) >= len(previous.failed_tests):
                return True

        return False
