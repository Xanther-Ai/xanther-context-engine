"""Graph storage layer backed by Neo4j.

Provides async CRUD operations for AST nodes, edges, documentation,
and vector embeddings, plus semantic search via Neo4j vector indexes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

import neo4j
from neo4j import AsyncGraphDatabase

from xce.models import ASTEdge, ASTNode, GraphQuery, NodeKind, SearchResult

logger = logging.getLogger(__name__)

# Relationship type mapping from edge relation strings to Neo4j types.
_RELATION_MAP: dict[str, str] = {
    "contains": "CONTAINS",
    "calls": "CALLS",
    "imports": "IMPORTS",
    "inherits": "INHERITS",
    "decorates": "DECORATES",
}


def _build_schema_constraints(embedding_dimensions: int) -> list[str]:
    """Return the list of Cypher statements that initialise the schema."""
    return [
        "CREATE CONSTRAINT ast_node_id IF NOT EXISTS FOR (n:ASTNode) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repository) REQUIRE r.repo_id IS UNIQUE",
        "CREATE INDEX ast_kind_idx IF NOT EXISTS FOR (n:ASTNode) ON (n.kind)",
        "CREATE INDEX ast_filepath_idx IF NOT EXISTS FOR (n:ASTNode) ON (n.filepath)",
        "CREATE INDEX ast_name_idx IF NOT EXISTS FOR (n:ASTNode) ON (n.name)",
        (
            "CREATE VECTOR INDEX embedding_idx IF NOT EXISTS "
            "FOR (n:Embedding) ON (n.vector) "
            "OPTIONS {indexConfig: {`vector.dimensions`: "
            f"{embedding_dimensions}"
            ", `vector.similarity_function`: 'cosine'}}"
        ),
    ]


class GraphStore:
    """Async Neo4j-backed graph store for XCE knowledge graph."""

    # ------------------------------------------------------------------
    # 3.1  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_auth: tuple[str, str],
        *,
        embedding_dimensions: int = 512,
    ) -> None:
        self._driver: neo4j.AsyncDriver = AsyncGraphDatabase.driver(
            neo4j_uri,
            auth=neo4j_auth,
        )
        self._embedding_dimensions = embedding_dimensions

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying driver and release resources."""
        await self._driver.close()

    # ------------------------------------------------------------------
    # 3.2  Schema initialisation
    # ------------------------------------------------------------------

    async def init_schema(self) -> None:
        """Create uniqueness constraints, indexes, and vector index."""
        stmts = _build_schema_constraints(self._embedding_dimensions)
        async with self._driver.session() as session:
            for stmt in stmts:
                await session.run(stmt)

    # ------------------------------------------------------------------
    # 3.3  upsert_ast_nodes
    # ------------------------------------------------------------------

    async def upsert_ast_nodes(self, nodes: list[ASTNode]) -> int:
        """MERGE AST nodes into the graph. Returns count of nodes written."""
        if not nodes:
            return 0

        cypher = (
            "UNWIND $nodes AS n "
            "MERGE (a:ASTNode {id: n.id}) "
            "SET a.kind = n.kind, "
            "    a.name = n.name, "
            "    a.filepath = n.filepath, "
            "    a.start_line = n.start_line, "
            "    a.end_line = n.end_line, "
            "    a.source_text = n.source_text, "
            "    a.docstring = n.docstring, "
            "    a.signature = n.signature, "
            "    a.parent_id = n.parent_id, "
            "    a.repo_id = n.repo_id "
            "RETURN count(a) AS cnt"
        )

        params = [
            {
                "id": n.id,
                "kind": n.kind.value,
                "name": n.name,
                "filepath": n.filepath,
                "start_line": n.start_line,
                "end_line": n.end_line,
                "source_text": n.source_text,
                "docstring": n.docstring,
                "signature": n.signature,
                "parent_id": n.parent_id,
                "repo_id": n.id.split(":")[0] if ":" in n.id else "",
            }
            for n in nodes
        ]

        async with self._driver.session() as session:
            result = await session.run(cypher, {"nodes": params})
            record = await result.single()
            return record["cnt"] if record else 0

    # ------------------------------------------------------------------
    # 3.4  upsert_edges
    # ------------------------------------------------------------------

    async def upsert_edges(self, edges: list[ASTEdge]) -> int:
        """MERGE relationships between AST nodes. Returns count written."""
        if not edges:
            return 0

        count = 0
        # Group edges by relation type so we can use typed relationships.
        by_type: dict[str, list[ASTEdge]] = {}
        for e in edges:
            by_type.setdefault(e.relation, []).append(e)

        async with self._driver.session() as session:
            for relation, group in by_type.items():
                rel_type = _RELATION_MAP.get(relation, relation.upper())
                cypher = (
                    "UNWIND $edges AS e "
                    "MATCH (src:ASTNode {id: e.source_id}) "
                    "MATCH (tgt:ASTNode {id: e.target_id}) "
                    f"MERGE (src)-[r:{rel_type}]->(tgt) "
                    "RETURN count(r) AS cnt"
                )
                params = [
                    {"source_id": e.source_id, "target_id": e.target_id}
                    for e in group
                ]
                result = await session.run(cypher, {"edges": params})
                record = await result.single()
                count += record["cnt"] if record else 0
        return count

    # ------------------------------------------------------------------
    # 3.5  upsert_documentation
    # ------------------------------------------------------------------

    async def upsert_documentation(
        self,
        docs: list[Any],
    ) -> int:
        """Attach documentation nodes to their AST nodes.

        Accepts ``ComponentDescription``, ``LLDDocument``, or ``HLDDocument``
        objects (duck-typed by attribute inspection).
        """
        if not docs:
            return 0

        count = 0
        async with self._driver.session() as session:
            for doc in docs:
                if hasattr(doc, "summary"):
                    # ComponentDescription
                    cypher = (
                        "MATCH (a:ASTNode {id: $node_id}) "
                        "MERGE (d:ComponentDesc {node_id: $node_id}) "
                        "SET d.summary = $summary, "
                        "    d.responsibilities = $responsibilities, "
                        "    d.dependencies = $dependencies "
                        "MERGE (a)-[:DESCRIBED_BY]->(d) "
                        "RETURN count(d) AS cnt"
                    )
                    result = await session.run(cypher, {
                        "node_id": doc.node_id,
                        "summary": doc.summary,
                        "responsibilities": doc.responsibilities,
                        "dependencies": doc.dependencies,
                    })
                    record = await result.single()
                    count += record["cnt"] if record else 0

                elif hasattr(doc, "algorithm_description"):
                    # LLDDocument
                    cypher = (
                        "MATCH (d:ComponentDesc {node_id: $component_id}) "
                        "MERGE (l:LLDDoc {component_id: $component_id}) "
                        "SET l.algorithm_description = $algo, "
                        "    l.data_flow = $data_flow, "
                        "    l.error_handling = $error_handling, "
                        "    l.edge_cases = $edge_cases "
                        "MERGE (d)-[:DETAILED_IN]->(l) "
                        "RETURN count(l) AS cnt"
                    )
                    result = await session.run(cypher, {
                        "component_id": doc.component_id,
                        "algo": doc.algorithm_description,
                        "data_flow": doc.data_flow,
                        "error_handling": doc.error_handling,
                        "edge_cases": doc.edge_cases,
                    })
                    record = await result.single()
                    count += record["cnt"] if record else 0

                elif hasattr(doc, "architectural_role"):
                    # HLDDocument
                    cypher = (
                        "MERGE (h:HLDDoc {module_path: $module_path}) "
                        "SET h.architectural_role = $role, "
                        "    h.design_patterns = $patterns, "
                        "    h.integration_points = $integrations, "
                        "    h.quality_attributes = $quality "
                        "WITH h "
                        "MATCH (a:ASTNode) "
                        "WHERE a.filepath STARTS WITH $module_path "
                        "MERGE (a)-[:PART_OF_HLD]->(h) "
                        "RETURN count(h) AS cnt"
                    )
                    result = await session.run(cypher, {
                        "module_path": doc.module_path,
                        "role": doc.architectural_role,
                        "patterns": doc.design_patterns,
                        "integrations": doc.integration_points,
                        "quality": doc.quality_attributes,
                    })
                    record = await result.single()
                    count += record["cnt"] if record else 0

        return count

    # ------------------------------------------------------------------
    # 3.6  upsert_embeddings
    # ------------------------------------------------------------------

    async def upsert_embeddings(
        self,
        node_ids: list[str],
        embeddings: list[list[float]],
    ) -> int:
        """Store vector embeddings on Embedding nodes linked to ASTNodes.

        Raises ``ValueError`` if any embedding has the wrong dimensionality.
        """
        if not node_ids:
            return 0
        if len(node_ids) != len(embeddings):
            raise ValueError("node_ids and embeddings must have the same length")

        # Validate dimensions
        for i, emb in enumerate(embeddings):
            if len(emb) != self._embedding_dimensions:
                raise ValueError(
                    f"Embedding for {node_ids[i]} has {len(emb)} dimensions, "
                    f"expected {self._embedding_dimensions}"
                )

        cypher = (
            "UNWIND $items AS item "
            "MATCH (a:ASTNode {id: item.node_id}) "
            "MERGE (e:Embedding {node_id: item.node_id}) "
            "SET e.vector = item.vector "
            "MERGE (a)-[:HAS_EMBEDDING]->(e) "
            "RETURN count(e) AS cnt"
        )
        params = [
            {"node_id": nid, "vector": emb}
            for nid, emb in zip(node_ids, embeddings)
        ]

        async with self._driver.session() as session:
            result = await session.run(cypher, {"items": params})
            record = await result.single()
            return record["cnt"] if record else 0

    # ------------------------------------------------------------------
    # 3.7  semantic_search
    # ------------------------------------------------------------------

    async def semantic_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        node_kinds: Optional[list[NodeKind]] = None,
        repo_id: Optional[str] = None,
    ) -> list[SearchResult]:
        """Vector similarity search over Embedding nodes.

        Returns results sorted by descending cosine similarity, bounded
        by *top_k*.  Optionally filters by ``node_kinds`` and ``repo_id``.
        """
        if len(query_embedding) != self._embedding_dimensions:
            raise ValueError(
                f"Query embedding has {len(query_embedding)} dimensions, "
                f"expected {self._embedding_dimensions}"
            )

        # Build the base vector search query
        cypher = (
            "CALL db.index.vector.queryNodes('embedding_idx', $top_k, $embedding) "
            "YIELD node AS emb, score "
            "MATCH (a:ASTNode {id: emb.node_id}) "
        )

        where_clauses: list[str] = []
        params: dict[str, Any] = {
            "top_k": top_k,
            "embedding": query_embedding,
        }

        if repo_id is not None:
            where_clauses.append("a.repo_id = $repo_id")
            params["repo_id"] = repo_id

        if node_kinds:
            where_clauses.append("a.kind IN $kinds")
            params["kinds"] = [k.value for k in node_kinds]

        if where_clauses:
            cypher += "WHERE " + " AND ".join(where_clauses) + " "

        cypher += (
            "RETURN a.id AS node_id, score, properties(a) AS node_data "
            "ORDER BY score DESC "
            "LIMIT $limit"
        )
        params["limit"] = top_k

        async with self._driver.session() as session:
            result = await session.run(cypher, params)
            records = [r async for r in result]

        return [
            SearchResult(
                node_id=r["node_id"],
                score=r["score"],
                node_data=dict(r["node_data"]),
            )
            for r in records
        ]

    # ------------------------------------------------------------------
    # 3.8  execute_query & get_neighbors
    # ------------------------------------------------------------------

    async def execute_query(self, query: GraphQuery) -> list[dict[str, Any]]:
        """Execute a raw Cypher query and return the result records as dicts."""
        async with self._driver.session() as session:
            result = await session.run(query.cypher, query.params)
            return [dict(r) async for r in result]

    async def get_neighbors(
        self,
        node_id: str,
        relation: Optional[str] = None,
        depth: int = 1,
    ) -> list[SearchResult]:
        """Return neighbouring nodes up to *depth* hops away.

        If *relation* is given, only edges of that type are traversed.
        """
        if relation:
            rel_type = _RELATION_MAP.get(relation, relation.upper())
            rel_pattern = f"[*1..{depth}:{rel_type}]"
        else:
            rel_pattern = f"[*1..{depth}]"

        # Use undirected traversal so we find neighbours in both directions.
        cypher = (
            f"MATCH (start:ASTNode {{id: $nid}})-{rel_pattern}-(neighbor) "
            "WHERE neighbor.id <> $nid "
            "RETURN DISTINCT neighbor.id AS node_id, properties(neighbor) AS node_data"
        )

        async with self._driver.session() as session:
            result = await session.run(cypher, {"nid": node_id})
            records = [r async for r in result]

        return [
            SearchResult(
                node_id=r["node_id"],
                score=1.0 / depth,  # simple distance-based score
                node_data=dict(r["node_data"]) if r["node_data"] else {},
            )
            for r in records
        ]
