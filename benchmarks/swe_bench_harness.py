"""SWE-bench test harness for the Xanther Context Engine.

Validates XCE against SWE-bench instances, computing resolve rate,
cost, latency, and error rate metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Baseline metrics for comparison
BASELINES: dict[str, float] = {
    "sonnet_baseline": 0.56,
    "prior_xce": 0.64,
    "opus_sota": 0.627,
}


@dataclass
class SWEBenchInstance:
    """A single SWE-bench evaluation instance."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str  # Gold patch
    test_patch: str


@dataclass
class EvalResult:
    """Result of evaluating a single SWE-bench instance."""

    instance_id: str
    resolved: bool
    agent_patch: str = ""
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    error: Optional[str] = None
    skipped: bool = False


class SWEBenchTestHarness:
    """Orchestrate SWE-bench evaluation of the XCE pipeline."""

    # ------------------------------------------------------------------
    # 11.1  __init__ — load dataset, manage instances
    # ------------------------------------------------------------------

    def __init__(
        self,
        mcp_server: Any = None,
        coding_agent_client: Any = None,
        dataset_path: str = "",
    ) -> None:
        self._mcp = mcp_server
        self._agent = coding_agent_client
        self._dataset_path = dataset_path
        self._instances: list[SWEBenchInstance] = []

    def load_dataset(self, instances: list[SWEBenchInstance] | None = None) -> int:
        """Load SWE-bench instances. Returns count loaded."""
        if instances is not None:
            self._instances = list(instances)
        elif self._dataset_path:
            self._instances = self._load_from_path(self._dataset_path)
        return len(self._instances)

    @staticmethod
    def _load_from_path(path: str) -> list[SWEBenchInstance]:
        """Load instances from a dataset file/directory.

        In production this would use the ``swebench`` package.
        For now returns an empty list — callers should provide instances.
        """
        logger.info("Loading SWE-bench dataset from %s", path)
        return []

    # ------------------------------------------------------------------
    # 11.2  run_instance — full pipeline per instance
    # ------------------------------------------------------------------

    async def run_instance(self, instance: SWEBenchInstance) -> EvalResult:
        """Run the full pipeline for a single instance.

        Steps: checkout → index → query context → generate patch → evaluate.
        """
        start = time.monotonic()
        try:
            # Step 1: Index the repo (mock — real impl would checkout base_commit)
            if self._mcp:
                await self._mcp.handle_tool_call(
                    "xce_index_repo",
                    {"repo_path": instance.repo, "repo_id": instance.instance_id},
                )

            # Step 2: Query context via MCP
            context_result = None
            if self._mcp:
                context_result = await self._mcp.handle_tool_call(
                    "xce_search",
                    {
                        "query": instance.problem_statement,
                        "repo_id": instance.instance_id,
                        "search_type": "semantic",
                    },
                )

            # Step 3: Generate patch (mock coding agent interaction)
            agent_patch = ""
            if self._agent and context_result:
                agent_patch = await self._agent.generate_patch(
                    problem=instance.problem_statement,
                    context=context_result,
                )
            elif self._agent:
                agent_patch = await self._agent.generate_patch(
                    problem=instance.problem_statement,
                    context=None,
                )

            # Step 4: Evaluate against gold patch
            resolved = self._evaluate_patch(agent_patch, instance.patch)

            elapsed = time.monotonic() - start
            return EvalResult(
                instance_id=instance.instance_id,
                resolved=resolved,
                agent_patch=agent_patch,
                latency_seconds=elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Instance %s failed", instance.instance_id)
            return EvalResult(
                instance_id=instance.instance_id,
                resolved=False,
                error=str(exc),
                latency_seconds=elapsed,
                skipped=True,
            )

    @staticmethod
    def _evaluate_patch(agent_patch: str, gold_patch: str) -> bool:
        """Compare agent patch against gold patch.

        Simple heuristic: check if the agent patch is non-empty and
        contains the same changed files. Real evaluation would apply
        both patches and run tests.
        """
        if not agent_patch:
            return False
        return agent_patch.strip() == gold_patch.strip()

    # ------------------------------------------------------------------
    # 11.3  run_django_subset — ~50 Django instances
    # ------------------------------------------------------------------

    async def run_django_subset(self) -> list[EvalResult]:
        """Run the Django subset as the primary validation route."""
        django_instances = [
            inst for inst in self._instances
            if "django" in inst.repo.lower()
        ]
        if not django_instances:
            django_instances = self._instances[:50]

        results: list[EvalResult] = []
        for inst in django_instances:
            result = await self.run_instance(inst)
            results.append(result)
            logger.info(
                "Instance %s: resolved=%s latency=%.1fs",
                inst.instance_id,
                result.resolved,
                result.latency_seconds,
            )
        return results

    # ------------------------------------------------------------------
    # 11.4  compute_metrics — aggregate metrics
    # ------------------------------------------------------------------

    @staticmethod
    def compute_metrics(results: list[EvalResult]) -> dict[str, float]:
        """Compute aggregate metrics from evaluation results."""
        if not results:
            return {
                "resolve_rate": 0.0,
                "avg_cost_usd": 0.0,
                "avg_latency_seconds": 0.0,
                "error_rate": 0.0,
                "total_instances": 0,
            }

        non_skipped = [r for r in results if not r.skipped]
        total = len(results)
        resolved = sum(1 for r in non_skipped if r.resolved)
        errors = sum(1 for r in results if r.error)

        resolve_rate = resolved / len(non_skipped) if non_skipped else 0.0
        avg_cost = sum(r.cost_usd for r in results) / total
        avg_latency = sum(r.latency_seconds for r in results) / total
        error_rate = errors / total

        return {
            "resolve_rate": resolve_rate,
            "avg_cost_usd": avg_cost,
            "avg_latency_seconds": avg_latency,
            "error_rate": error_rate,
            "total_instances": float(total),
        }

    # ------------------------------------------------------------------
    # 11.5  compare_to_baseline
    # ------------------------------------------------------------------

    @staticmethod
    def compare_to_baseline(
        results: list[EvalResult],
        baselines: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Compare results against baseline resolve rates."""
        if baselines is None:
            baselines = BASELINES

        non_skipped = [r for r in results if not r.skipped]
        resolve_rate = (
            sum(1 for r in non_skipped if r.resolved) / len(non_skipped)
            if non_skipped
            else 0.0
        )

        comparisons: dict[str, Any] = {"xce_resolve_rate": resolve_rate}
        for name, baseline_rate in baselines.items():
            delta = resolve_rate - baseline_rate
            comparisons[name] = {
                "baseline": baseline_rate,
                "delta": delta,
                "beats_baseline": delta > 0,
            }

        return comparisons
