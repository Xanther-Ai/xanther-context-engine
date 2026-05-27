"""Context summarizer for the Xanther Context Engine.

Merges, deduplicates, ranks, and summarizes traversal results into
a token-efficient context window using Kimi/GLM.
"""

from __future__ import annotations

import logging
from typing import Any

import tiktoken
from openai import AsyncOpenAI

from xce.models import SummarizationRequest, SummarizedContext, TraversalResult

logger = logging.getLogger(__name__)

RESERVED_FOR_SUMMARY = 800


class ContextSummarizer:
    """Summarize traversal results into a coherent context window."""

    # ------------------------------------------------------------------
    # 8.1  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "moonshot/kimi-k2.5",
        base_url: str = "https://openrouter.ai/api/v1",
        max_context_tokens: int = 4000,
    ) -> None:
        self._model = model
        self._max_tokens = max_context_tokens
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize(self, request: SummarizationRequest) -> SummarizedContext:
        """Full summarization pipeline."""
        max_tokens = request.max_tokens or self._max_tokens

        # 8.2 — merge & deduplicate
        merged = self._merge_and_deduplicate(request.traversal_results)

        # 8.3 — rank
        ranked = self._rank_contexts(merged, request.query)

        # 8.4 — token budget
        selected, token_count = self._select_within_budget(ranked, max_tokens)

        # 8.5 — LLM summarization
        summary_text = await self._llm_summarize(selected, request.query)

        # Extract code snippets (preserved verbatim)
        snippets = self._extract_code_snippets(selected)

        # Key facts from summary
        key_facts = self._extract_key_facts(summary_text)

        summary_tokens = self._count_tokens(summary_text)
        total_tokens = token_count + summary_tokens

        confidence = self._aggregate_confidence(request.traversal_results)

        return SummarizedContext(
            summary=summary_text,
            key_facts=key_facts,
            relevant_code_snippets=snippets,
            confidence=confidence,
            token_count=total_tokens,
        )

    # ------------------------------------------------------------------
    # 8.2  Merge & deduplicate
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_and_deduplicate(
        results: list[TraversalResult],
    ) -> list[dict[str, Any]]:
        """Merge contexts from multiple traversal results, deduplicate by node_id."""
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for result in results:
            for ctx in result.contexts:
                nid = ctx.get("node_id", "")
                if nid and nid not in seen:
                    seen.add(nid)
                    merged.append(ctx)
        return merged

    # ------------------------------------------------------------------
    # 8.3  Relevance ranking
    # ------------------------------------------------------------------

    @staticmethod
    def _rank_contexts(
        contexts: list[dict[str, Any]], query: str,
    ) -> list[dict[str, Any]]:
        """Rank by combined score: 0.6 * semantic_similarity + 0.4 * impact_score.

        When semantic_similarity is not pre-computed, defaults to 0.5.
        """
        def _score(ctx: dict[str, Any]) -> float:
            semantic = ctx.get("semantic_similarity", 0.5)
            impact = ctx.get("impact_score", 0.5)
            # Also use the generic "score" field if present
            if "score" in ctx and "semantic_similarity" not in ctx:
                semantic = ctx["score"]
            return 0.6 * semantic + 0.4 * impact

        scored = [(ctx, _score(ctx)) for ctx in contexts]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Attach computed score for downstream use
        ranked: list[dict[str, Any]] = []
        for ctx, s in scored:
            c = dict(ctx)
            c["_combined_score"] = s
            ranked.append(c)
        return ranked

    # ------------------------------------------------------------------
    # 8.4  Token budget enforcement
    # ------------------------------------------------------------------

    def _select_within_budget(
        self,
        ranked: list[dict[str, Any]],
        max_tokens: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Select contexts that fit within max_tokens - RESERVED_FOR_SUMMARY."""
        budget = max_tokens - RESERVED_FOR_SUMMARY
        if budget <= 0:
            return [], 0

        selected: list[dict[str, Any]] = []
        total = 0
        for ctx in ranked:
            text = self._context_to_text(ctx)
            tokens = self._count_tokens(text)
            if total + tokens <= budget:
                selected.append(ctx)
                total += tokens
            else:
                break
        return selected, total

    # ------------------------------------------------------------------
    # 8.5  LLM summarization
    # ------------------------------------------------------------------

    async def _llm_summarize(
        self, contexts: list[dict[str, Any]], query: str,
    ) -> str:
        """Call Kimi/GLM to produce a summary. Preserves code snippets verbatim."""
        if not contexts:
            return "No relevant context found."

        ctx_text = "\n---\n".join(self._context_to_text(c) for c in contexts)
        prompt = (
            f"Summarize the following code context to answer: {query}\n\n"
            "IMPORTANT: Preserve all code snippets verbatim. Do not paraphrase code.\n\n"
            f"{ctx_text}"
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=RESERVED_FOR_SUMMARY,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("LLM summarization failed: %s", exc)
            # Fallback: return concatenated context text
            return ctx_text[:2000]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text))

    @staticmethod
    def _context_to_text(ctx: dict[str, Any]) -> str:
        """Convert a context dict to a text representation."""
        parts: list[str] = []
        data = ctx.get("data", {})
        if isinstance(data, dict):
            if data.get("name"):
                parts.append(f"Name: {data['name']}")
            if data.get("filepath"):
                parts.append(f"File: {data['filepath']}")
            if data.get("source_text"):
                parts.append(f"Code:\n{data['source_text']}")
            if data.get("summary"):
                parts.append(f"Summary: {data['summary']}")
        nid = ctx.get("node_id", "")
        if nid and not parts:
            parts.append(f"Node: {nid}")
        ctype = ctx.get("type", "")
        if ctype:
            parts.insert(0, f"[{ctype}]")
        return "\n".join(parts) if parts else str(ctx)

    @staticmethod
    def _extract_code_snippets(contexts: list[dict[str, Any]]) -> list[dict[str, str]]:
        snippets: list[dict[str, str]] = []
        for ctx in contexts:
            data = ctx.get("data", {})
            if isinstance(data, dict) and data.get("source_text"):
                snippets.append({
                    "filepath": data.get("filepath", "unknown"),
                    "snippet": data["source_text"],
                })
        return snippets

    @staticmethod
    def _extract_key_facts(summary: str) -> list[str]:
        """Split summary into key fact sentences."""
        if not summary:
            return []
        sentences = [s.strip() for s in summary.replace("\n", ". ").split(". ") if s.strip()]
        return sentences[:10]

    @staticmethod
    def _aggregate_confidence(results: list[TraversalResult]) -> float:
        if not results:
            return 0.0
        return sum(r.confidence for r in results) / len(results)
