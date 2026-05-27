"""Complexity router for the Xanther Context Engine.

Classifies problem complexity and routes to the appropriate
pipeline depth and model tier.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from xce.models import ProblemComplexity, RoutingDecision, TestPatchSignal

logger = logging.getLogger(__name__)

# Cross-file indicator keywords
_CROSS_FILE_KEYWORDS = frozenset({
    "import", "dependency", "inheritance", "inherits", "extends",
    "cross-file", "multiple files", "across files", "module",
    "package", "refactor", "migration",
})


class ComplexityRouter:
    """Classify problem complexity and route to appropriate pipeline."""

    # ------------------------------------------------------------------
    # 17.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        graph_store: Any = None,
        llm_client: Any = None,
    ) -> None:
        self._gs = graph_store
        self._llm = llm_client

    # ------------------------------------------------------------------
    # 17.3  _heuristic_classify
    # ------------------------------------------------------------------

    @staticmethod
    def _heuristic_classify(
        problem_statement: str,
        test_signal: Optional[TestPatchSignal] = None,
    ) -> ProblemComplexity:
        """Fast heuristic classification.

        Based on: number of files in test patch signal, presence of
        cross-file keywords, problem statement length/complexity.
        """
        file_count = 0
        if test_signal:
            file_count = len(test_signal.tested_files)

        # Count cross-file keywords
        problem_lower = problem_statement.lower()
        keyword_hits = sum(1 for kw in _CROSS_FILE_KEYWORDS if kw in problem_lower)

        # Problem statement length as complexity indicator
        word_count = len(problem_statement.split())

        # Classification rules
        if file_count <= 1 and keyword_hits == 0 and word_count < 100:
            return ProblemComplexity.SIMPLE
        if file_count >= 4 or keyword_hits >= 3 or word_count >= 300:
            return ProblemComplexity.COMPLEX
        return ProblemComplexity.MODERATE

    # ------------------------------------------------------------------
    # 17.4  classify
    # ------------------------------------------------------------------

    async def classify(
        self,
        problem_statement: str,
        test_patch_signal: Optional[TestPatchSignal] = None,
        repo_id: Optional[str] = None,
    ) -> RoutingDecision:
        """Classify problem complexity and determine routing.

        Combines heuristic classification with optional LLM confirmation
        for borderline cases.
        """
        heuristic = self._heuristic_classify(problem_statement, test_patch_signal)

        # For borderline cases, optionally use LLM confirmation
        if self._llm and heuristic == ProblemComplexity.MODERATE:
            try:
                llm_complexity = await self._llm_classify(problem_statement)
                if llm_complexity is not None:
                    heuristic = llm_complexity
            except Exception as exc:
                logger.warning("LLM classification failed, using heuristic: %s", exc)

        return self._build_routing(heuristic)

    async def _llm_classify(self, problem_statement: str) -> Optional[ProblemComplexity]:
        """Lightweight LLM classification for borderline cases."""
        if self._llm is None:
            return None

        try:
            response = await self._llm.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify this bug report as SIMPLE (single file fix), "
                            "MODERATE (2-3 files), or COMPLEX (multi-file, deep deps). "
                            "Reply with just the word."
                        ),
                    },
                    {"role": "user", "content": problem_statement[:500]},
                ],
                max_tokens=10,
            )
            text = (response.choices[0].message.content or "").strip().upper()
            if "SIMPLE" in text:
                return ProblemComplexity.SIMPLE
            if "COMPLEX" in text:
                return ProblemComplexity.COMPLEX
            if "MODERATE" in text:
                return ProblemComplexity.MODERATE
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 17.5  _build_routing
    # ------------------------------------------------------------------

    @staticmethod
    def _build_routing(complexity: ProblemComplexity) -> RoutingDecision:
        """Map complexity to pipeline configuration."""
        if complexity == ProblemComplexity.SIMPLE:
            return RoutingDecision(
                complexity=complexity,
                pipeline_depth="shallow",
                model_tier="fast",
                skip_agents=["architecture", "traceability"],
                estimated_cost_multiplier=0.3,
                reasoning="Single-file fix — shallow pipeline with fast model",
            )
        if complexity == ProblemComplexity.MODERATE:
            return RoutingDecision(
                complexity=complexity,
                pipeline_depth="standard",
                model_tier="standard",
                skip_agents=["architecture"],
                estimated_cost_multiplier=0.7,
                reasoning="Multi-file with some deps — standard pipeline",
            )
        # COMPLEX
        return RoutingDecision(
            complexity=complexity,
            pipeline_depth="deep",
            model_tier="reasoning",
            skip_agents=[],
            estimated_cost_multiplier=1.5,
            reasoning="Complex multi-file problem — full pipeline with reasoning model",
        )

    # ------------------------------------------------------------------
    # 17.6  Escalation logic
    # ------------------------------------------------------------------

    @staticmethod
    def escalate(current: RoutingDecision) -> RoutingDecision:
        """Escalate to the next complexity tier when current pipeline fails."""
        if current.complexity == ProblemComplexity.SIMPLE:
            return ComplexityRouter._build_routing(ProblemComplexity.MODERATE)
        if current.complexity == ProblemComplexity.MODERATE:
            return ComplexityRouter._build_routing(ProblemComplexity.COMPLEX)
        # Already at COMPLEX — return as-is
        return current
