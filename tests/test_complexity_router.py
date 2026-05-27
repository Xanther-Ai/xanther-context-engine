"""Tests for complexity router (Task 17).

Validates:
- P19: Routing consistency (SIMPLE → cheap, COMPLEX → deep)
- Classification for known simple/moderate/complex problems
- Cost multiplier bounds
- Escalation behavior
"""

from __future__ import annotations

import pytest

from xce.utils.complexity_router import ComplexityRouter
from xce.models import ProblemComplexity, RoutingDecision, TestPatchSignal


class TestHeuristicClassify:
    def test_simple_single_file(self):
        result = ComplexityRouter._heuristic_classify(
            "Fix typo in utils.py",
            TestPatchSignal(tested_files=["utils.py"]),
        )
        assert result == ProblemComplexity.SIMPLE

    def test_simple_short_problem(self):
        result = ComplexityRouter._heuristic_classify("Fix a small bug")
        assert result == ProblemComplexity.SIMPLE

    def test_moderate_few_files(self):
        result = ComplexityRouter._heuristic_classify(
            "Fix the handler to call the correct validation method",
            TestPatchSignal(tested_files=["a.py", "b.py"]),
        )
        assert result == ProblemComplexity.MODERATE

    def test_complex_many_files(self):
        result = ComplexityRouter._heuristic_classify(
            "Refactor the entire module hierarchy with inheritance changes across multiple packages",
            TestPatchSignal(tested_files=["a.py", "b.py", "c.py", "d.py"]),
        )
        assert result == ProblemComplexity.COMPLEX

    def test_complex_long_problem(self):
        long_problem = "word " * 300  # 300 words
        result = ComplexityRouter._heuristic_classify(long_problem)
        assert result == ProblemComplexity.COMPLEX

    def test_no_signal(self):
        result = ComplexityRouter._heuristic_classify("Fix a bug")
        assert result == ProblemComplexity.SIMPLE


class TestBuildRouting:
    """P19: Routing consistency."""

    def test_simple_routing(self):
        decision = ComplexityRouter._build_routing(ProblemComplexity.SIMPLE)
        assert decision.pipeline_depth == "shallow"
        assert decision.model_tier == "fast"
        assert decision.estimated_cost_multiplier <= 0.5
        assert "architecture" in decision.skip_agents
        assert "traceability" in decision.skip_agents

    def test_moderate_routing(self):
        decision = ComplexityRouter._build_routing(ProblemComplexity.MODERATE)
        assert decision.pipeline_depth == "standard"
        assert decision.model_tier == "standard"
        assert decision.estimated_cost_multiplier <= 1.0
        assert "architecture" in decision.skip_agents

    def test_complex_routing(self):
        decision = ComplexityRouter._build_routing(ProblemComplexity.COMPLEX)
        assert decision.pipeline_depth == "deep"
        assert decision.model_tier == "reasoning"
        assert decision.skip_agents == []
        assert decision.estimated_cost_multiplier >= 1.0


class TestClassify:
    @pytest.mark.asyncio
    async def test_classify_simple(self):
        router = ComplexityRouter()
        decision = await router.classify("Fix typo in utils.py")
        assert decision.complexity == ProblemComplexity.SIMPLE

    @pytest.mark.asyncio
    async def test_classify_returns_routing_decision(self):
        router = ComplexityRouter()
        decision = await router.classify("Fix a bug")
        assert isinstance(decision, RoutingDecision)
        assert decision.reasoning  # non-empty


class TestEscalation:
    def test_simple_to_moderate(self):
        current = ComplexityRouter._build_routing(ProblemComplexity.SIMPLE)
        escalated = ComplexityRouter.escalate(current)
        assert escalated.complexity == ProblemComplexity.MODERATE

    def test_moderate_to_complex(self):
        current = ComplexityRouter._build_routing(ProblemComplexity.MODERATE)
        escalated = ComplexityRouter.escalate(current)
        assert escalated.complexity == ProblemComplexity.COMPLEX

    def test_complex_stays_complex(self):
        current = ComplexityRouter._build_routing(ProblemComplexity.COMPLEX)
        escalated = ComplexityRouter.escalate(current)
        assert escalated.complexity == ProblemComplexity.COMPLEX
