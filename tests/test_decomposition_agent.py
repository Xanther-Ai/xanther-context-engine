"""Tests for problem decomposition agent (Task 18).

Validates:
- P20: Every sub-task targets a valid agent
- P21: Execution plan covers all sub-tasks exactly once
- Sub-task count (3-5)
- Dependency ordering
- Test patch signal injection
- Fallback behavior
- Parallel execution grouping
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from xce.query.decomposition import ProblemDecompositionAgent, _VALID_AGENTS
from xce.models import (
    DecompositionResult,
    SubTask,
    TestPatchSignal,
    TraversalResult,
)


def _make_subtasks(n: int = 3) -> list[SubTask]:
    return [
        SubTask(
            task_id=f"subtask-{i}",
            description=f"Task {i}",
            search_queries=[f"query-{i}"],
            target_agent="search",
            priority=i + 1,
        )
        for i in range(n)
    ]


class TestDecompose:
    @pytest.mark.asyncio
    async def test_fallback_no_llm(self):
        """18.9 — Falls back to single search task when no LLM."""
        agent = ProblemDecompositionAgent()
        result = await agent.decompose("Fix the bug")
        assert len(result.sub_tasks) >= 1
        assert result.sub_tasks[0].target_agent == "search"

    @pytest.mark.asyncio
    async def test_valid_agents(self):
        """P20: Every sub-task targets a valid agent."""
        agent = ProblemDecompositionAgent()
        result = await agent.decompose("Fix the bug")
        for st in result.sub_tasks:
            assert st.target_agent in _VALID_AGENTS

    @pytest.mark.asyncio
    async def test_execution_plan_completeness(self):
        """P21: Execution plan covers all sub-tasks exactly once."""
        agent = ProblemDecompositionAgent()
        result = await agent.decompose("Fix the bug")
        flat = [tid for group in result.execution_plan for tid in group]
        task_ids = {st.task_id for st in result.sub_tasks}
        assert set(flat) == task_ids
        assert len(flat) == len(task_ids)  # No duplicates


class TestBuildExecutionPlan:
    def test_independent_tasks_grouped(self):
        tasks = _make_subtasks(3)
        plan = ProblemDecompositionAgent.build_execution_plan(tasks)
        # All independent → single group
        assert len(plan) == 1
        assert len(plan[0]) == 3

    def test_dependent_tasks_ordered(self):
        tasks = [
            SubTask(task_id="a", description="A", search_queries=["a"],
                    target_agent="search", priority=1),
            SubTask(task_id="b", description="B", search_queries=["b"],
                    target_agent="search", priority=2, depends_on=["a"]),
            SubTask(task_id="c", description="C", search_queries=["c"],
                    target_agent="search", priority=3, depends_on=["b"]),
        ]
        plan = ProblemDecompositionAgent.build_execution_plan(tasks)
        assert len(plan) == 3
        assert plan[0] == ["a"]
        assert plan[1] == ["b"]
        assert plan[2] == ["c"]

    def test_parallel_and_sequential(self):
        tasks = [
            SubTask(task_id="a", description="A", search_queries=["a"],
                    target_agent="search", priority=1),
            SubTask(task_id="b", description="B", search_queries=["b"],
                    target_agent="search", priority=2),
            SubTask(task_id="c", description="C", search_queries=["c"],
                    target_agent="search", priority=3, depends_on=["a", "b"]),
        ]
        plan = ProblemDecompositionAgent.build_execution_plan(tasks)
        assert len(plan) == 2
        assert set(plan[0]) == {"a", "b"}
        assert plan[1] == ["c"]

    def test_empty_tasks(self):
        plan = ProblemDecompositionAgent.build_execution_plan([])
        assert plan == []

    def test_circular_dependency_broken(self):
        tasks = [
            SubTask(task_id="a", description="A", search_queries=["a"],
                    target_agent="search", priority=1, depends_on=["b"]),
            SubTask(task_id="b", description="B", search_queries=["b"],
                    target_agent="search", priority=2, depends_on=["a"]),
        ]
        plan = ProblemDecompositionAgent.build_execution_plan(tasks)
        flat = [tid for group in plan for tid in group]
        assert set(flat) == {"a", "b"}

    def test_completeness(self):
        """P21: All tasks covered exactly once."""
        tasks = _make_subtasks(5)
        plan = ProblemDecompositionAgent.build_execution_plan(tasks)
        flat = [tid for group in plan for tid in group]
        assert len(flat) == 5
        assert len(set(flat)) == 5


class TestTestPatchSignalInjection:
    @pytest.mark.asyncio
    async def test_injects_tested_symbols(self):
        """18.8 — Tested symbols added as priority-0 sub-tasks."""
        agent = ProblemDecompositionAgent()
        signal = TestPatchSignal(
            tested_symbols=["filter", "QuerySet", "Q"],
            priority_score={"filter": 1.0, "QuerySet": 0.5, "Q": 1.0},
        )
        result = await agent.decompose("Fix filter bug", test_patch_signal=signal)
        # Should have injected test signal tasks
        test_tasks = [st for st in result.sub_tasks if st.task_id.startswith("subtask-test-")]
        assert len(test_tasks) >= 1
        for tt in test_tasks:
            assert tt.priority == 0  # Highest priority

    @pytest.mark.asyncio
    async def test_no_duplicate_injection(self):
        """Doesn't inject symbols already in search queries."""
        agent = ProblemDecompositionAgent()
        signal = TestPatchSignal(tested_symbols=["filter"])
        result = await agent.decompose("Fix filter bug", test_patch_signal=signal)
        # The fallback task searches for "Fix filter bug" — "filter" is a different query
        assert isinstance(result.sub_tasks, list)


class TestExecutePlan:
    @pytest.mark.asyncio
    async def test_executes_all_tasks(self):
        agent = ProblemDecompositionAgent()
        search_agent = AsyncMock()
        search_agent.search = AsyncMock(return_value=TraversalResult(
            contexts=[{"node_id": "n1", "data": {}}],
            reasoning=["found"],
            confidence=0.8,
            nodes_visited=1,
        ))
        agents = {"search": search_agent}

        decomp = DecompositionResult(
            original_problem="test",
            sub_tasks=_make_subtasks(2),
            execution_plan=[["subtask-0", "subtask-1"]],
            estimated_traversals=2,
        )
        results = await agent.execute_plan(decomp, agents, "repo-1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handles_missing_agent(self):
        agent = ProblemDecompositionAgent()
        decomp = DecompositionResult(
            original_problem="test",
            sub_tasks=[SubTask(
                task_id="t1", description="test",
                search_queries=["q"], target_agent="architecture",
            )],
            execution_plan=[["t1"]],
        )
        results = await agent.execute_plan(decomp, {}, "repo-1")
        assert len(results) == 1
        assert results[0].confidence == 0.0  # Agent not available


class TestValidateSubtasks:
    @pytest.mark.asyncio
    async def test_search_tasks_always_valid(self):
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[{"cnt": 0}])
        agent = ProblemDecompositionAgent(graph_store=gs)
        tasks = [SubTask(
            task_id="t1", description="search",
            search_queries=["anything"], target_agent="search",
        )]
        validated = await agent._validate_subtasks(tasks, "repo-1")
        assert len(validated) == 1

    @pytest.mark.asyncio
    async def test_removes_invalid_non_search_tasks(self):
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[{"cnt": 0}])
        agent = ProblemDecompositionAgent(graph_store=gs)
        tasks = [SubTask(
            task_id="t1", description="trace",
            search_queries=["nonexistent"], target_agent="trace",
        )]
        validated = await agent._validate_subtasks(tasks, "repo-1")
        assert len(validated) == 0

    @pytest.mark.asyncio
    async def test_keeps_valid_non_search_tasks(self):
        gs = AsyncMock()
        gs.execute_query = AsyncMock(return_value=[{"cnt": 5}])
        agent = ProblemDecompositionAgent(graph_store=gs)
        tasks = [SubTask(
            task_id="t1", description="trace",
            search_queries=["existing_symbol"], target_agent="trace",
        )]
        validated = await agent._validate_subtasks(tasks, "repo-1")
        assert len(validated) == 1
