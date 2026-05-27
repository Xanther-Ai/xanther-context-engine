"""LangGraph traversal agents for the Xanther Context Engine.

Implements four specialized agents:
- ArchitectureAgent: locate → expand → enrich → synthesize (LangGraph StateGraph)
- TraceabilityAgent: bidirectional trace chains
- ImpactAnalysisAgent: BFS reverse CALLS/IMPORTS, score = 1/(depth+1)
- SearchDiscoveryAgent: hybrid semantic + structural search
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from langgraph.graph import END, StateGraph

from xce.graph.store import GraphStore
from xce.models import GraphQuery, TraversalResult, TraversalState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAX_CONTEXT_ITEMS = 30


def _make_initial_state(
    query: str, repo_id: str, max_depth: int = 3,
) -> TraversalState:
    return TraversalState(
        query=query,
        repo_id=repo_id,
        visited_nodes=[],
        collected_context=[],
        current_depth=0,
        max_depth=max_depth,
        reasoning_trace=[],
    )


def _result_from_state(state: TraversalState, confidence: float = 0.5) -> TraversalResult:
    return TraversalResult(
        contexts=list(state["collected_context"]),
        reasoning=list(state["reasoning_trace"]),
        confidence=confidence,
        nodes_visited=len(set(state["visited_nodes"])),
    )


# ===================================================================
# 7.2  Architecture Agent  (LangGraph StateGraph)
# ===================================================================


class ArchitectureAgent:
    """Map files/symbols to Architecture components and explain architectural context.

    State machine: locate → expand → enrich → synthesize.
    Terminates at max_depth or 30 context items.
    """

    def __init__(self, graph_store: GraphStore) -> None:
        self._gs = graph_store
        self._graph = self._build_graph()

    # -- public API --------------------------------------------------

    async def query(self, file_or_symbol: str, repo_id: str, *, max_depth: int = 3) -> TraversalResult:
        state = _make_initial_state(file_or_symbol, repo_id, max_depth)
        final = await self._graph.ainvoke(state)
        visited = len(set(final["visited_nodes"]))
        ctx_count = len(final["collected_context"])
        confidence = min(1.0, ctx_count / MAX_CONTEXT_ITEMS) if ctx_count else 0.0
        return _result_from_state(final, confidence)

    # -- graph construction ------------------------------------------

    def _build_graph(self) -> Any:
        workflow = StateGraph(TraversalState)
        workflow.add_node("locate", self._locate)
        workflow.add_node("expand", self._expand)
        workflow.add_node("enrich", self._enrich)
        workflow.add_node("synthesize", self._synthesize)

        workflow.set_entry_point("locate")
        workflow.add_edge("locate", "expand")
        workflow.add_conditional_edges(
            "expand",
            self._should_continue,
            {"expand": "expand", "enrich": "enrich"},
        )
        workflow.add_edge("enrich", "synthesize")
        workflow.add_edge("synthesize", END)
        return workflow.compile()

    # -- node functions ----------------------------------------------

    async def _locate(self, state: TraversalState) -> dict[str, Any]:
        q = state["query"]
        rid = state["repo_id"]
        results = await self._gs.execute_query(GraphQuery(
            cypher=(
                "MATCH (n:ASTNode) "
                "WHERE (n.filepath CONTAINS $query OR n.name = $query) "
                "AND n.repo_id = $rid "
                "RETURN n.id AS nid LIMIT 10"
            ),
            params={"query": q, "rid": rid},
        ))
        found_ids = [r["nid"] for r in results if r.get("nid")]
        if not found_ids:
            # fallback: semantic search (requires embedding service externally)
            found_ids = []
        return {
            "visited_nodes": found_ids,
            "reasoning_trace": [f"Located {len(found_ids)} matching nodes"],
        }

    async def _expand(self, state: TraversalState) -> dict[str, Any]:
        new_ctx: list[dict[str, Any]] = list(state["collected_context"])
        visited = list(state["visited_nodes"])

        for nid in state["visited_nodes"][:5]:
            # parent module
            parents = await self._gs.get_neighbors(nid, relation="contains", depth=1)
            # Architecture component
            hld = await self._gs.get_neighbors(nid, relation="PART_OF_ARCHITECTURE", depth=1)
            for item in parents + hld:
                if item.node_id not in visited:
                    visited.append(item.node_id)
                    new_ctx.append({
                        "type": "architectural_context",
                        "node_id": item.node_id,
                        "data": item.node_data,
                    })

        return {
            "visited_nodes": visited,
            "collected_context": new_ctx,
            "current_depth": state["current_depth"] + 1,
            "reasoning_trace": state["reasoning_trace"]
            + [f"Expanded to {len(new_ctx)} context items (depth {state['current_depth'] + 1})"],
        }

    def _should_continue(self, state: TraversalState) -> str:
        if state["current_depth"] >= state["max_depth"]:
            return "enrich"
        if len(state["collected_context"]) >= MAX_CONTEXT_ITEMS:
            return "enrich"
        return "expand"

    async def _enrich(self, state: TraversalState) -> dict[str, Any]:
        enriched: list[dict[str, Any]] = []
        for ctx in state["collected_context"]:
            docs = await self._gs.execute_query(GraphQuery(
                cypher=(
                    "MATCH (n:ASTNode {id: $nid})-[:DESCRIBED_BY]->(desc) "
                    "OPTIONAL MATCH (desc)-[:DETAILED_IN]->(lld) "
                    "RETURN desc, lld"
                ),
                params={"nid": ctx["node_id"]},
            ))
            ctx_copy = dict(ctx)
            ctx_copy["documentation"] = docs
            enriched.append(ctx_copy)
        return {
            "collected_context": enriched,
            "reasoning_trace": state["reasoning_trace"]
            + [f"Enriched {len(enriched)} contexts with documentation"],
        }

    async def _synthesize(self, state: TraversalState) -> dict[str, Any]:
        return {
            "reasoning_trace": state["reasoning_trace"] + ["Synthesis complete"],
        }


# ===================================================================
# 7.3  Traceability Agent
# ===================================================================


class TraceabilityAgent:
    """Build bidirectional trace chains: ASTNode ↔ ComponentDesc ↔ ComponentDoc ↔ ArchitectureDoc."""

    def __init__(self, graph_store: GraphStore) -> None:
        self._gs = graph_store

    async def trace(
        self, source: str, target_level: str, repo_id: str, *, max_depth: int = 4,
    ) -> TraversalResult:
        state = _make_initial_state(source, repo_id, max_depth)

        # Locate source node
        results = await self._gs.execute_query(GraphQuery(
            cypher=(
                "MATCH (n:ASTNode) "
                "WHERE (n.name = $q OR n.filepath CONTAINS $q) AND n.repo_id = $rid "
                "RETURN n.id AS nid LIMIT 5"
            ),
            params={"q": source, "rid": repo_id},
        ))
        source_ids = [r["nid"] for r in results if r.get("nid")]
        state["visited_nodes"] = source_ids
        state["reasoning_trace"].append(f"Trace source: found {len(source_ids)} nodes")

        # Build trace chain per source node
        for nid in source_ids:
            chain = await self._build_chain(nid, target_level)
            for step in chain:
                if step["node_id"] not in state["visited_nodes"]:
                    state["visited_nodes"].append(step["node_id"])
                state["collected_context"].append(step)

        state["reasoning_trace"].append(
            f"Built trace chains to {target_level}, {len(state['collected_context'])} items"
        )
        confidence = min(1.0, len(state["collected_context"]) / 10) if state["collected_context"] else 0.0
        return _result_from_state(state, confidence)

    async def _build_chain(self, node_id: str, target_level: str) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []

        # ASTNode → ComponentDescription
        descs = await self._gs.execute_query(GraphQuery(
            cypher="MATCH (n:ASTNode {id: $nid})-[:DESCRIBED_BY]->(d) RETURN d, d.node_id AS did",
            params={"nid": node_id},
        ))
        for d in descs:
            chain.append({"type": "component_desc", "node_id": d.get("did", node_id), "data": d.get("d", {})})

        if target_level in ("component", "architecture"):
            # ComponentDescription → ComponentDoc
            llds = await self._gs.execute_query(GraphQuery(
                cypher=(
                    "MATCH (n:ASTNode {id: $nid})-[:DESCRIBED_BY]->(d)-[:DETAILED_IN]->(l) "
                    "RETURN l, l.component_id AS lid"
                ),
                params={"nid": node_id},
            ))
            for l in llds:
                chain.append({"type": "component", "node_id": l.get("lid", node_id), "data": l.get("l", {})})

        if target_level == "architecture":
            # ASTNode → ArchitectureDoc
            hlds = await self._gs.execute_query(GraphQuery(
                cypher=(
                    "MATCH (n:ASTNode {id: $nid})-[:PART_OF_ARCHITECTURE]->(h) "
                    "RETURN h, h.module_path AS hid"
                ),
                params={"nid": node_id},
            ))
            for h in hlds:
                chain.append({"type": "architecture", "node_id": h.get("hid", node_id), "data": h.get("h", {})})

        return chain


# ===================================================================
# 7.4  Impact Analysis Agent
# ===================================================================


class ImpactAnalysisAgent:
    """BFS walk of reverse CALLS/IMPORTS edges, score = 1/(depth+1)."""

    def __init__(self, graph_store: GraphStore) -> None:
        self._gs = graph_store

    async def analyze(
        self, changed_files: list[str], repo_id: str, *, max_depth: int = 3,
    ) -> TraversalResult:
        state = _make_initial_state(
            f"impact of changes to {changed_files}", repo_id, max_depth,
        )
        impact_set: dict[str, float] = {}  # node_id → best score

        for filepath in changed_files:
            file_nodes = await self._gs.execute_query(GraphQuery(
                cypher="MATCH (n:ASTNode {filepath: $fp}) WHERE n.repo_id = $rid RETURN n.id AS nid",
                params={"fp": filepath, "rid": repo_id},
            ))
            for rec in file_nodes:
                nid = rec.get("nid")
                if not nid:
                    continue
                state["visited_nodes"].append(nid)
                # Direct node gets score 1.0
                impact_set[nid] = 1.0

                # BFS reverse walk
                callers = await self._bfs_reverse(nid, max_depth, set(state["visited_nodes"]))
                for caller_id, depth in callers:
                    score = 1.0 / (depth + 1)
                    if caller_id in impact_set:
                        impact_set[caller_id] = max(impact_set[caller_id], score)
                    else:
                        impact_set[caller_id] = score
                    if caller_id not in state["visited_nodes"]:
                        state["visited_nodes"].append(caller_id)

        # Rank by impact score descending
        ranked = sorted(impact_set.items(), key=lambda x: x[1], reverse=True)
        for nid, score in ranked[:50]:
            state["collected_context"].append({
                "type": "impacted_node",
                "node_id": nid,
                "impact_score": score,
            })

        state["reasoning_trace"].append(
            f"Analyzed {len(changed_files)} files, found {len(impact_set)} impacted nodes"
        )
        confidence = min(1.0, len(impact_set) / 20) if impact_set else 0.0
        return _result_from_state(state, confidence)

    async def _bfs_reverse(
        self, start_id: str, max_depth: int, visited: set[str],
    ) -> list[tuple[str, int]]:
        """BFS walk of reverse CALLS/IMPORTS edges. Returns (node_id, depth)."""
        result: list[tuple[str, int]] = []
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            callers = await self._gs.execute_query(GraphQuery(
                cypher=(
                    "MATCH (caller:ASTNode)-[:CALLS|IMPORTS]->(target:ASTNode {id: $nid}) "
                    "RETURN caller.id AS cid"
                ),
                params={"nid": current_id},
            ))
            for rec in callers:
                cid = rec.get("cid")
                if cid and cid not in visited:
                    visited.add(cid)
                    result.append((cid, depth + 1))
                    queue.append((cid, depth + 1))

        return result


# ===================================================================
# 7.5  Search & Discovery Agent
# ===================================================================


class SearchDiscoveryAgent:
    """Hybrid semantic + structural search across the knowledge graph."""

    def __init__(self, graph_store: GraphStore, embedding_service: Any = None) -> None:
        self._gs = graph_store
        self._embed = embedding_service

    async def search(
        self,
        query: str,
        repo_id: str,
        *,
        search_type: str = "semantic",
        top_k: int = 10,
    ) -> TraversalResult:
        state = _make_initial_state(query, repo_id)

        if search_type == "symbol":
            results = await self._symbol_search(query, repo_id, top_k)
        elif search_type == "semantic":
            results = await self._semantic_search(query, repo_id, top_k)
        else:
            # tag or fallback — treat as symbol search
            results = await self._symbol_search(query, repo_id, top_k)

        # Collect results sorted by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:top_k]

        for r in results:
            state["visited_nodes"].append(r["node_id"])
            state["collected_context"].append(r)

        state["reasoning_trace"].append(
            f"Search ({search_type}): found {len(results)} results for '{query}'"
        )
        confidence = min(1.0, len(results) / top_k) if results else 0.0
        return _result_from_state(state, confidence)

    async def _symbol_search(
        self, query: str, repo_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        records = await self._gs.execute_query(GraphQuery(
            cypher=(
                "MATCH (n:ASTNode) "
                "WHERE (n.name CONTAINS $q OR n.filepath CONTAINS $q) "
                "AND n.repo_id = $rid "
                "RETURN n.id AS node_id, n.name AS name, properties(n) AS data "
                "LIMIT $limit"
            ),
            params={"q": query, "rid": repo_id, "limit": top_k},
        ))
        return [
            {
                "type": "search_result",
                "node_id": r["node_id"],
                "score": 1.0,  # exact/partial match
                "data": r.get("data", {}),
            }
            for r in records
            if r.get("node_id")
        ]

    async def _semantic_search(
        self, query: str, repo_id: str, top_k: int,
    ) -> list[dict[str, Any]]:
        if self._embed is None:
            # No embedding service — fall back to symbol search
            return await self._symbol_search(query, repo_id, top_k)

        query_emb = await self._embed.encode(query)
        search_results = await self._gs.semantic_search(
            query_emb, top_k=top_k, repo_id=repo_id,
        )
        return [
            {
                "type": "search_result",
                "node_id": sr.node_id,
                "score": sr.score,
                "data": sr.node_data,
            }
            for sr in search_results
        ]
