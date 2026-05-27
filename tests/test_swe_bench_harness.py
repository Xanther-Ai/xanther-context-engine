"""Tests for SWE-bench test harness (Task 11).

Validates:
- Dataset loading and instance management
- Metrics computation (resolve rate, cost, latency, error rate)
- Baseline comparison
- Django subset filtering
"""

from __future__ import annotations

import pytest

from xce.swe_bench_harness import (
    BASELINES,
    EvalResult,
    SWEBenchInstance,
    SWEBenchTestHarness,
)


def _make_instance(instance_id: str, repo: str = "django/django") -> SWEBenchInstance:
    return SWEBenchInstance(
        instance_id=instance_id,
        repo=repo,
        base_commit="abc123",
        problem_statement="Fix the bug",
        patch="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
        test_patch="--- a/tests/test.py\n+++ b/tests/test.py\n@@ -1 +1 @@\n+def test_fix(): pass",
    )


class TestSWEBenchTestHarness:
    def test_load_dataset(self):
        harness = SWEBenchTestHarness()
        instances = [_make_instance("inst-1"), _make_instance("inst-2")]
        count = harness.load_dataset(instances)
        assert count == 2

    def test_load_empty_dataset(self):
        harness = SWEBenchTestHarness()
        count = harness.load_dataset([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_instance_no_agent(self):
        harness = SWEBenchTestHarness()
        inst = _make_instance("inst-1")
        result = await harness.run_instance(inst)
        assert result.instance_id == "inst-1"
        assert not result.resolved  # No agent → no patch → not resolved

    @pytest.mark.asyncio
    async def test_run_django_subset(self):
        harness = SWEBenchTestHarness()
        instances = [_make_instance(f"django-{i}") for i in range(5)]
        harness.load_dataset(instances)
        results = await harness.run_django_subset()
        assert len(results) == 5


class TestComputeMetrics:
    def test_empty_results(self):
        metrics = SWEBenchTestHarness.compute_metrics([])
        assert metrics["resolve_rate"] == 0.0
        assert metrics["total_instances"] == 0

    def test_all_resolved(self):
        results = [
            EvalResult(instance_id=f"i-{i}", resolved=True, latency_seconds=1.0)
            for i in range(10)
        ]
        metrics = SWEBenchTestHarness.compute_metrics(results)
        assert metrics["resolve_rate"] == 1.0
        assert metrics["error_rate"] == 0.0

    def test_mixed_results(self):
        results = [
            EvalResult(instance_id="i-0", resolved=True, latency_seconds=1.0),
            EvalResult(instance_id="i-1", resolved=False, latency_seconds=2.0),
            EvalResult(instance_id="i-2", resolved=True, latency_seconds=1.5),
            EvalResult(instance_id="i-3", resolved=False, latency_seconds=3.0, error="fail"),
        ]
        metrics = SWEBenchTestHarness.compute_metrics(results)
        assert metrics["resolve_rate"] == 0.5  # 2/4
        assert metrics["error_rate"] == 0.25  # 1/4

    def test_skipped_excluded_from_resolve_rate(self):
        results = [
            EvalResult(instance_id="i-0", resolved=True, latency_seconds=1.0),
            EvalResult(instance_id="i-1", resolved=False, skipped=True, error="skip"),
        ]
        metrics = SWEBenchTestHarness.compute_metrics(results)
        assert metrics["resolve_rate"] == 1.0  # 1/1 non-skipped


class TestCompareToBaseline:
    def test_beats_all_baselines(self):
        results = [
            EvalResult(instance_id=f"i-{i}", resolved=True)
            for i in range(10)
        ]
        comparison = SWEBenchTestHarness.compare_to_baseline(results)
        assert comparison["xce_resolve_rate"] == 1.0
        for name in BASELINES:
            assert comparison[name]["beats_baseline"] is True

    def test_below_baselines(self):
        results = [
            EvalResult(instance_id="i-0", resolved=False),
        ]
        comparison = SWEBenchTestHarness.compare_to_baseline(results)
        assert comparison["xce_resolve_rate"] == 0.0
        for name in BASELINES:
            assert comparison[name]["beats_baseline"] is False
