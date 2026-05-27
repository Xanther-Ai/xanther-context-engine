"""Multi-hop reasoning chain builder for the Xanther Context Engine.

Constructs 3-4 step reasoning chains from traversal results,
generating narratives that explain how code elements connect.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from xce.models import (
    ChainStep,
    GraphQuery,
    ReasoningChain,
    TraversalResult,
)

logger = logging.getLogger(__name__)


class ReasoningChainBuilder:
    """Build multi-hop reasoning chains from traversal results."""

    # ------------------------------------------------------------------
    # 13.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        graph_store: Any,
        llm_client: Any = None,
        max_chain_length: int = 4,
    ) -> None:
        self._gs = graph_store
        self._llm = llm_client
        self._max_chain_length = max_chain_length

    # ------------------------------------------------------------------
    # 13.3  _find_connected_paths
    # ------------------------------------------------------------------

    async def _find_connected_paths(
        self,
        contexts: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """Find paths of 3-4 connected nodes within traversal results.

        Queries Neo4j for paths using CALLS/IMPORTS/INHERITS/CONTAINS edges.
        """
        node_ids = [ctx.get("node_id", "") for ctx in contexts if ctx.get("node_id")]
        if len(node_ids) < 3:
            return []

        node_data_map = {ctx["node_id"]: ctx for ctx in contexts if ctx.get("node_id")}
        candidate_paths: list[list[dict[str, Any]]] = []

        for nid in node_ids[:10]:  # Limit to avoid excessive queries
            try:
                results = await self._gs.execute_query(GraphQuery(
                    cypher=(
                        "MATCH path = (start:ASTNode {id: $nid})"
                        "-[:CALLS|IMPORTS|INHERITS|CONTAINS*2..3]->"
                        "(end:ASTNode) "
                        "WHERE end.id IN $node_ids "
                        "RETURN [n IN nodes(path) | n.id] AS node_chain, "
                        "[r IN relationships(path) | type(r)] AS rel_chain "
                        "LIMIT 10"
                    ),
                    params={"nid": nid, "node_ids": node_ids},
                ))
            except Exception as exc:
                logger.warning("Path query failed for %s: %s", nid, exc)
                continue

            for record in results:
                chain = record.get("node_chain", [])
                rels = record.get("rel_chain", [])
                if len(chain) >= 3:
                    path_data = []
                    for i, node_id in enumerate(chain):
                        rel = rels[i] if i < len(rels) else ""
                        ctx = node_data_map.get(node_id, {"node_id": node_id})
                        path_data.append({
                            "node_id": node_id,
                            "relationship": rel,
                            "data": ctx.get("data", {}),
                        })
                    candidate_paths.append(path_data)

        return candidate_paths

    # ------------------------------------------------------------------
    # 13.4  build_chains
    # ------------------------------------------------------------------

    async def build_chains(
        self,
        traversal_results: list[TraversalResult],
        query: str,
        max_chains: int = 5,
    ) -> list[ReasoningChain]:
        """Build reasoning chains from traversal results.

        Scores paths by relevance, selects top-k, generates narratives.
        Falls back to empty list if fewer than 3 connected nodes.
        """
        # Collect all contexts
        all_contexts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in traversal_results:
            for ctx in result.contexts:
                nid = ctx.get("node_id", "")
                if nid and nid not in seen:
                    seen.add(nid)
                    all_contexts.append(ctx)

        if len(all_contexts) < 3:
            logger.warning("Fewer than 3 nodes — cannot build chains")
            return []

        # Find connected paths
        paths = await self._find_connected_paths(all_contexts)
        if not paths:
            logger.warning("No connected paths found — falling back to flat context")
            return []

        # Score and rank paths
        scored: list[tuple[list[dict[str, Any]], float]] = []
        for path in paths:
            score = self._score_path(path, query)
            scored.append((path, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        # Build chains for top-k
        chains: list[ReasoningChain] = []
        for path, score in scored[:max_chains]:
            steps = self._path_to_steps(path)
            if len(steps) < 3:
                continue
            # Truncate to max chain length
            steps = steps[: self._max_chain_length]

            narrative = await self._narrate_chain(path, query)

            chains.append(ReasoningChain(
                chain_id=f"chain-{uuid.uuid4().hex[:8]}",
                steps=steps,
                narrative=narrative,
                confidence=score,
                entry_node_id=steps[0].node_id,
            ))

        return chains

    def _score_path(self, path: list[dict[str, Any]], query: str) -> float:
        """Score a path by simple heuristic relevance to query."""
        score = 0.0
        query_lower = query.lower()
        for step in path:
            data = step.get("data", {})
            name = str(data.get("name", step.get("node_id", ""))).lower()
            if name in query_lower or query_lower in name:
                score += 0.5
            score += 0.1  # base score per step
        return min(1.0, score)

    @staticmethod
    def _path_to_steps(path: list[dict[str, Any]]) -> list[ChainStep]:
        """Convert a path of dicts to ChainStep objects."""
        steps: list[ChainStep] = []
        for item in path:
            data = item.get("data", {})
            steps.append(ChainStep(
                node_id=item.get("node_id", ""),
                node_name=data.get("name", item.get("node_id", "unknown")),
                relationship=item.get("relationship", ""),
                insight="",
                source_snippet=data.get("source_text"),
            ))
        return steps

    # ------------------------------------------------------------------
    # 13.5  _narrate_chain
    # ------------------------------------------------------------------

    async def _narrate_chain(
        self,
        path: list[dict[str, Any]],
        query: str,
    ) -> str:
        """Generate a narrative for a chain via LLM.

        Falls back to a simple arrow-joined description on LLM failure.
        """
        names = [
            p.get("data", {}).get("name", p.get("node_id", "?"))
            for p in path
        ]
        rels = [p.get("relationship", "→") for p in path]

        fallback = " → ".join(
            f"{names[i]} ({rels[i]})" if i < len(rels) else names[i]
            for i in range(len(names))
        )

        if self._llm is None:
            return fallback

        try:
            prompt = (
                f"Given the query '{query}', explain in 1-2 sentences how these "
                f"code elements connect: {fallback}"
            )
            response = await self._llm.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
            )
            return response.choices[0].message.content or fallback
        except Exception as exc:
            logger.warning("Narrative generation failed: %s", exc)
            return fallback
