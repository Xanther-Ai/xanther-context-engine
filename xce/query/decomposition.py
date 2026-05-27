"""Problem decomposition agent for the Xanther Context Engine.

Breaks problem statements into targeted sub-tasks, validates them
against the graph, and executes them through appropriate agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from xce.models import (
    DecompositionResult,
    GraphQuery,
    SubTask,
    TestPatchSignal,
    TraversalResult,
)

logger = logging.getLogger(__name__)

_VALID_AGENTS = frozenset({"architecture", "trace", "impact", "search"})


class ProblemDecompositionAgent:
    """Decompose problems into targeted sub-tasks for focused traversal."""

    # ------------------------------------------------------------------
    # 18.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        llm_client: Any = None,
        graph_store: Any = None,
    ) -> None:
        self._llm = llm_client
        self._gs = graph_store

    # ------------------------------------------------------------------
    # 18.3  decompose
    # ------------------------------------------------------------------

    async def decompose(
        self,
        problem_statement: str,
        test_patch_signal: Optional[TestPatchSignal] = None,
        repo_id: Optional[str] = None,
    ) -> DecompositionResult:
        """Break a problem into 3-5 sub-tasks.

        Falls back to a single search query on LLM failure.
        """
        sub_tasks: list[SubTask] = []

        # Try LLM decomposition
        if self._llm:
            try:
                sub_tasks = await self._llm_decompose(problem_statement)
            except Exception as exc:
                logger.warning("LLM decomposition failed: %s", exc)

        # Validate sub-tasks against graph
        if sub_tasks and self._gs and repo_id:
            sub_tasks = await self._validate_subtasks(sub_tasks, repo_id)

        # Inject test patch signals (18.8)
        if test_patch_signal:
            sub_tasks = self._inject_test_signals(sub_tasks, test_patch_signal)

        # Fallback (18.9): if no valid sub-tasks, create a single search task
        if not sub_tasks:
            sub_tasks = [SubTask(
                task_id="subtask-fallback",
                description=f"Search for: {problem_statement[:200]}",
                search_queries=[problem_statement[:200]],
                target_agent="search",
                priority=1,
            )]

        # Clamp to 3-5 sub-tasks
        if len(sub_tasks) > 5:
            sub_tasks = sorted(sub_tasks, key=lambda t: t.priority)[:5]

        # Build execution plan
        execution_plan = self.build_execution_plan(sub_tasks)

        return DecompositionResult(
            original_problem=problem_statement,
            sub_tasks=sub_tasks,
            execution_plan=execution_plan,
            estimated_traversals=len(sub_tasks),
        )

    async def _llm_decompose(self, problem_statement: str) -> list[SubTask]:
        """Use LLM to decompose the problem into sub-tasks."""
        prompt = (
            "Given this bug report, identify 3-5 distinct things we need to find "
            "in the codebase. For each, provide a JSON object with:\n"
            '- "description": what to find\n'
            '- "search_query": specific symbol or concept to search\n'
            '- "agent": one of "architecture", "trace", "impact", "search"\n'
            '- "depends_on": list of task indices (0-based) this depends on\n\n'
            f"Problem: {problem_statement[:1000]}\n\n"
            'Respond with a JSON array of objects.'
        )

        response = await self._llm.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
        )

        content = response.choices[0].message.content or "[]"
        # Try to extract JSON from response
        try:
            items = json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON array in the response
            import re
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                items = json.loads(match.group())
            else:
                return []

        sub_tasks: list[SubTask] = []
        for i, item in enumerate(items[:5]):
            agent = item.get("agent", "search")
            if agent not in _VALID_AGENTS:
                agent = "search"

            depends = item.get("depends_on", [])
            dep_ids = [f"subtask-{d}" for d in depends if isinstance(d, int)]

            sub_tasks.append(SubTask(
                task_id=f"subtask-{i}",
                description=item.get("description", ""),
                search_queries=[item.get("search_query", "")],
                target_agent=agent,
                priority=i + 1,
                depends_on=dep_ids,
            ))

        return sub_tasks

    # ------------------------------------------------------------------
    # 18.4  _validate_subtasks
    # ------------------------------------------------------------------

    async def _validate_subtasks(
        self,
        sub_tasks: list[SubTask],
        repo_id: str,
    ) -> list[SubTask]:
        """Validate sub-tasks against the graph.

        Remove sub-tasks referencing non-existent symbols,
        except "search" agent tasks which can search for anything.
        """
        if not self._gs:
            return sub_tasks

        validated: list[SubTask] = []
        for st in sub_tasks:
            if st.target_agent == "search":
                validated.append(st)
                continue

            # Check if any search query matches something in the graph
            found = False
            for query in st.search_queries:
                if not query:
                    continue
                try:
                    results = await self._gs.execute_query(GraphQuery(
                        cypher=(
                            "MATCH (n:ASTNode) "
                            "WHERE n.name CONTAINS $query AND n.repo_id = $rid "
                            "RETURN count(n) AS cnt"
                        ),
                        params={"query": query, "rid": repo_id},
                    ))
                    if results and results[0].get("cnt", 0) > 0:
                        found = True
                        break
                except Exception:
                    found = True  # On error, keep the task
                    break

            if found:
                validated.append(st)

        return validated

    # ------------------------------------------------------------------
    # 18.5  _build_state_graph (LangGraph state machine)
    # ------------------------------------------------------------------

    def _build_state_graph(self) -> Any:
        """Build LangGraph state machine for decomposition.

        States: analyze_problem → generate_subtasks → validate → plan → END.
        """
        try:
            from langgraph.graph import END, StateGraph
            from typing import TypedDict

            class DecompState(TypedDict):
                problem: str
                sub_tasks: list[dict[str, Any]]
                validated: bool
                plan: list[list[str]]

            workflow = StateGraph(DecompState)

            async def analyze(state: DecompState) -> dict[str, Any]:
                return {"problem": state["problem"]}

            async def generate(state: DecompState) -> dict[str, Any]:
                return {"sub_tasks": state.get("sub_tasks", [])}

            async def validate(state: DecompState) -> dict[str, Any]:
                return {"validated": True}

            async def plan(state: DecompState) -> dict[str, Any]:
                return {"plan": state.get("plan", [])}

            workflow.add_node("analyze", analyze)
            workflow.add_node("generate", generate)
            workflow.add_node("validate", validate)
            workflow.add_node("plan", plan)

            workflow.set_entry_point("analyze")
            workflow.add_edge("analyze", "generate")
            workflow.add_edge("generate", "validate")
            workflow.add_edge("validate", "plan")
            workflow.add_edge("plan", END)

            return workflow.compile()
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # 18.6  execute_plan
    # ------------------------------------------------------------------

    async def execute_plan(
        self,
        decomposition: DecompositionResult,
        agents: dict[str, Any],
        repo_id: str,
    ) -> list[TraversalResult]:
        """Execute the decomposition plan through appropriate agents.

        Respects dependencies and parallelizes independent tasks.
        """
        results: list[TraversalResult] = []
        completed: set[str] = set()

        for group in decomposition.execution_plan:
            # Execute tasks in this group in parallel
            tasks = []
            for task_id in group:
                st = next(
                    (t for t in decomposition.sub_tasks if t.task_id == task_id),
                    None,
                )
                if st is None:
                    continue
                tasks.append(self._execute_subtask(st, agents, repo_id))

            group_results = await asyncio.gather(*tasks, return_exceptions=True)

            for task_id, result in zip(group, group_results):
                completed.add(task_id)
                if isinstance(result, TraversalResult):
                    results.append(result)
                elif isinstance(result, Exception):
                    logger.warning("Sub-task %s failed: %s", task_id, result)

        return results

    async def _execute_subtask(
        self,
        sub_task: SubTask,
        agents: dict[str, Any],
        repo_id: str,
    ) -> TraversalResult:
        """Execute a single sub-task through its target agent."""
        agent = agents.get(sub_task.target_agent)
        if agent is None:
            return TraversalResult(
                contexts=[],
                reasoning=[f"Agent '{sub_task.target_agent}' not available"],
                confidence=0.0,
                nodes_visited=0,
            )

        query = sub_task.search_queries[0] if sub_task.search_queries else sub_task.description

        if sub_task.target_agent == "architecture":
            return await agent.query(query, repo_id)
        elif sub_task.target_agent == "trace":
            return await agent.trace(query, "architecture", repo_id)
        elif sub_task.target_agent == "impact":
            return await agent.analyze([query], repo_id)
        elif sub_task.target_agent == "search":
            return await agent.search(query, repo_id)

        return TraversalResult(
            contexts=[],
            reasoning=[f"Unknown agent: {sub_task.target_agent}"],
            confidence=0.0,
            nodes_visited=0,
        )

    # ------------------------------------------------------------------
    # 18.7  build_execution_plan
    # ------------------------------------------------------------------

    @staticmethod
    def build_execution_plan(sub_tasks: list[SubTask]) -> list[list[str]]:
        """Build execution plan with topological sort.

        Groups independent sub-tasks for parallel execution.
        Handles circular dependencies by breaking ties with priority.
        """
        if not sub_tasks:
            return []

        task_ids = {st.task_id for st in sub_tasks}
        dep_graph: dict[str, set[str]] = {}
        for st in sub_tasks:
            # Only keep dependencies that reference existing tasks
            deps = {d for d in st.depends_on if d in task_ids}
            dep_graph[st.task_id] = deps

        priority_map = {st.task_id: st.priority for st in sub_tasks}
        plan: list[list[str]] = []
        remaining = set(dep_graph.keys())
        completed: set[str] = set()

        while remaining:
            # Find tasks with all dependencies satisfied
            ready = {
                tid for tid in remaining
                if dep_graph[tid].issubset(completed)
            }

            if not ready:
                # Circular dependency — break by taking highest priority
                ready = {min(remaining, key=lambda tid: priority_map.get(tid, 999))}

            plan.append(sorted(ready))
            completed.update(ready)
            remaining -= ready

        return plan

    # ------------------------------------------------------------------
    # 18.8  Test patch signal injection
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_test_signals(
        sub_tasks: list[SubTask],
        signal: TestPatchSignal,
    ) -> list[SubTask]:
        """Add tested symbols as high-priority sub-tasks."""
        existing_queries = set()
        for st in sub_tasks:
            existing_queries.update(st.search_queries)

        injected = list(sub_tasks)
        for symbol in signal.tested_symbols[:3]:
            if symbol not in existing_queries:
                injected.append(SubTask(
                    task_id=f"subtask-test-{symbol}",
                    description=f"Find implementation of tested symbol: {symbol}",
                    search_queries=[symbol],
                    target_agent="search",
                    priority=0,  # Highest priority
                ))

        return injected
