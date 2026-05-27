"""Patch pattern index for the Xanther Context Engine.

Indexes gold patches from solved SWE-bench instances and retrieves
structurally similar patches for few-shot prompting.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

from xce.models import GraphQuery, PatchPattern, SimilarPatch

logger = logging.getLogger(__name__)


class PatchPatternIndex:
    """Index and retrieve similar gold patches."""

    # ------------------------------------------------------------------
    # 15.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        graph_store: Any,
        embedding_service: Any = None,
    ) -> None:
        self._gs = graph_store
        self._embed = embedding_service
        self._patterns: dict[str, PatchPattern] = {}  # instance_id → pattern

    # ------------------------------------------------------------------
    # 15.3  index_gold_patches
    # ------------------------------------------------------------------

    async def index_gold_patches(
        self,
        instances: list[Any],
    ) -> int:
        """Index gold patches from solved SWE-bench instances.

        Each instance should have: instance_id, repo, patch, problem_statement, test_patch.
        Returns count of patches indexed.
        """
        count = 0
        for inst in instances:
            instance_id = getattr(inst, "instance_id", "")
            if not instance_id:
                continue

            diff_text = getattr(inst, "patch", "")
            changed_files = self._extract_changed_files(diff_text)
            changed_symbols = self._extract_changed_symbols(diff_text)
            problem_statement = getattr(inst, "problem_statement", "")

            signature = self._compute_structural_signature(
                changed_files, changed_symbols, "bugfix",
            )

            # Generate embedding for problem statement
            embedding: Optional[list[float]] = None
            if self._embed and problem_statement:
                try:
                    embedding = await self._embed.encode(problem_statement)
                except Exception as exc:
                    logger.warning("Embedding failed for %s: %s", instance_id, exc)

            pattern = PatchPattern(
                instance_id=instance_id,
                repo=getattr(inst, "repo", ""),
                changed_files=changed_files,
                changed_symbols=changed_symbols,
                patch_type="bugfix",
                diff_text=diff_text,
                problem_statement=problem_statement,
                structural_signature=signature,
                embedding=embedding,
            )

            # Upsert — update if already exists
            self._patterns[instance_id] = pattern
            count += 1

        return count

    # ------------------------------------------------------------------
    # 15.4  _compute_structural_signature
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_structural_signature(
        changed_files: list[str],
        changed_symbols: list[str],
        patch_type: str = "bugfix",
    ) -> str:
        """Deterministic hash of (sorted changed_files, sorted changed_symbols, patch_type)."""
        key = "|".join([
            ",".join(sorted(changed_files)),
            ",".join(sorted(changed_symbols)),
            patch_type,
        ])
        return hashlib.sha256(key.encode()).hexdigest()

    # ------------------------------------------------------------------
    # 15.5  find_similar — hybrid structural + semantic matching
    # ------------------------------------------------------------------

    async def find_similar(
        self,
        problem_statement: str,
        changed_files: list[str],
        top_k: int = 3,
    ) -> list[SimilarPatch]:
        """Find similar past patches using hybrid matching.

        Combined score = 0.4 * structural + 0.6 * semantic.
        """
        if not self._patterns:
            return []

        # Generate query embedding
        query_embedding: Optional[list[float]] = None
        if self._embed and problem_statement:
            try:
                query_embedding = await self._embed.encode(problem_statement)
            except Exception as exc:
                logger.warning("Query embedding failed: %s", exc)

        scored: list[tuple[PatchPattern, float]] = []
        for pattern in self._patterns.values():
            sim = self._compute_similarity(
                pattern, query_embedding, changed_files,
            )
            scored.append((pattern, sim))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[SimilarPatch] = []
        for pattern, score in scored[:top_k]:
            results.append(SimilarPatch(
                pattern=pattern,
                similarity_score=score,
                relevance_explanation=(
                    f"Similar patch from {pattern.instance_id}: "
                    f"shared files={set(pattern.changed_files) & set(changed_files)}"
                ),
            ))

        return results

    # ------------------------------------------------------------------
    # 15.6  _compute_similarity
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_similarity(
        candidate: PatchPattern,
        problem_embedding: Optional[list[float]],
        target_files: list[str],
    ) -> float:
        """Combined similarity: 0.4 * structural + 0.6 * semantic.

        Structural = Jaccard similarity of changed files.
        Semantic = cosine similarity of problem embeddings.
        """
        # Structural: Jaccard similarity of files
        cand_set = set(candidate.changed_files)
        target_set = set(target_files)
        union = cand_set | target_set
        structural = len(cand_set & target_set) / len(union) if union else 0.0

        # Semantic: cosine similarity
        semantic = 0.0
        if problem_embedding and candidate.embedding:
            semantic = _cosine_similarity(problem_embedding, candidate.embedding)

        return 0.4 * structural + 0.6 * semantic

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_changed_files(diff_text: str) -> list[str]:
        """Extract file paths from a unified diff."""
        files: list[str] = []
        for line in diff_text.splitlines():
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                path = line.split("/", 1)[1] if "/" in line else ""
                if path and path not in files:
                    files.append(path)
        return files

    @staticmethod
    def _extract_changed_symbols(diff_text: str) -> list[str]:
        """Extract function/class names from diff hunk headers."""
        symbols: list[str] = []
        pattern = re.compile(r"@@.*@@\s*(?:def|class)\s+(\w+)")
        for match in pattern.finditer(diff_text):
            name = match.group(1)
            if name not in symbols:
                symbols.append(name)
        return symbols


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
