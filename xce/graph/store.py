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

        Accepts ``ComponentDescription``, ``ComponentDoc``, or ``ArchitectureDoc``
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
                    # ComponentDoc
                    cypher = (
                        "MATCH (d:ComponentDesc {node_id: $component_id}) "
                        "MERGE (l:ComponentDoc {component_id: $component_id}) "
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
                    # ArchitectureDoc
                    cypher = (
                        "MERGE (h:ArchitectureDoc {module_path: $module_path}) "
                        "SET h.architectural_role = $role, "
                        "    h.design_patterns = $patterns, "
                        "    h.integration_points = $integrations, "
                        "    h.quality_attributes = $quality "
                        "WITH h "
                        "MATCH (a:ASTNode) "
                        "WHERE a.filepath STARTS WITH $module_path "
                        "MERGE (a)-[:PART_OF_ARCHITECTURE]->(h) "
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
            rel_pattern = f"[:{rel_type}*1..{depth}]"
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

    # ------------------------------------------------------------------
    # 3.9  list_repositories
    # ------------------------------------------------------------------

    async def list_repositories(self) -> list[dict[str, Any]]:
        """List all indexed repositories with their statistics."""
        cypher = """
        MATCH (n:ASTNode)
        OPTIONAL MATCH (n)-[r]->(m:ASTNode)
        WITH n.repo_id AS repo_id, count(DISTINCT n) AS node_count, count(DISTINCT r) AS edge_count
        OPTIONAL MATCH (n2:ASTNode {repo_id: repo_id})
        WHERE n2.last_indexed IS NOT NULL
        WITH repo_id, node_count, edge_count, max(n2.last_indexed) AS last_indexed
        RETURN repo_id, node_count, edge_count, last_indexed
        ORDER BY last_indexed DESC
        """

        async with self._driver.session() as session:
            result = await session.run(cypher)
            records = [dict(r) async for r in result]

        return records

    # ------------------------------------------------------------------
    # 3.10  get_callers - Find nodes that call this symbol (up the call stack)
    # ------------------------------------------------------------------

    async def get_callers(
        self,
        symbol_id: str,
        depth: int = 1,
    ) -> list[dict[str, Any]]:
        """Find all callers of a symbol up the call stack.
        
        Args:
            symbol_id: The ID of the symbol to find callers for
            depth: Maximum depth to traverse (1-5)
            
        Returns:
            List of caller nodes with their properties
        """
        depth = max(1, min(depth, 5))  # Clamp depth between 1 and 5
        
        # Use string interpolation for depth (Cypher doesn't support params in MATCH patterns)
        # Simplified query without the problematic relationships() call
        cypher = f"""
        MATCH (caller:ASTNode)-[:CALLS*1..{depth}]->(target:ASTNode {{id: $symbol_id}})
        WHERE caller.id <> target.id
        RETURN DISTINCT 
            caller.id AS node_id, 
            caller.name AS name, 
            caller.kind AS kind,
            caller.filepath AS filepath,
            caller.start_line AS start_line,
            caller.end_line AS end_line,
            {depth} AS call_depth
        ORDER BY caller.name
        """
        
        async with self._driver.session() as session:
            result = await session.run(cypher, {"symbol_id": symbol_id, "depth": depth})
            records = [dict(r) async for r in result]
        
        return records

    # ------------------------------------------------------------------
    # 3.11  get_callees - Find nodes this symbol calls (down the call stack)
    # ------------------------------------------------------------------

    async def get_callees(
        self,
        symbol_id: str,
        depth: int = 1,
    ) -> list[dict[str, Any]]:
        """Find all callees of a symbol down the call stack.
        
        Args:
            symbol_id: The ID of the symbol to find callees for
            depth: Maximum depth to traverse (1-5)
            
        Returns:
            List of callee nodes with their properties
        """
        depth = max(1, min(depth, 5))  # Clamp depth between 1 and 5
        
        # Use string interpolation for depth (Cypher doesn't support params in MATCH patterns)
        # Simplified query without the problematic relationships() call
        cypher = f"""
        MATCH (source:ASTNode {{id: $symbol_id}})-[:CALLS*1..{depth}]->(callee:ASTNode)
        WHERE source.id <> callee.id
        RETURN DISTINCT 
            callee.id AS node_id, 
            callee.name AS name, 
            callee.kind AS kind,
            callee.filepath AS filepath,
            callee.start_line AS start_line,
            callee.end_line AS end_line,
            {depth} AS call_depth
        ORDER BY callee.name
        """
        
        async with self._driver.session() as session:
            result = await session.run(cypher, {"symbol_id": symbol_id, "depth": depth})
            records = [dict(r) async for r in result]
        
        return records

    # ------------------------------------------------------------------
    # 3.12  get_impact_analysis - Calculate risk and find affected files
    # ------------------------------------------------------------------

    async def get_impact_analysis(
        self,
        symbol_id: str,
    ) -> dict[str, Any]:
        """Analyze the impact of changes to a symbol.
        
        Calculates risk score based on fan-in (callers) and identifies:
        - Direct dependents
        - Test files that exercise this symbol
        
        Args:
            symbol_id: The ID of the symbol to analyze
            
        Returns:
            Dictionary with risk_score, direct_dependents, test_files, propagation_depth
        """
        # Get callers at various depths for fan-in calculation
        callers_1 = await self.get_callers(symbol_id, depth=1)
        callers_2 = await self.get_callers(symbol_id, depth=2)
        callers_3 = await self.get_callers(symbol_id, depth=3)
        
        # Get callees for propagation depth
        callees_1 = await self.get_callees(symbol_id, depth=1)
        
        # Determine propagation depth (how far down the call chain)
        propagation_depth = 0
        if callees_1:
            propagation_depth = 1
            # Check deeper levels
            callees_2 = await self.get_callees(symbol_id, depth=2)
            if callees_2:
                propagation_depth = 2
                callees_3 = await self.get_callees(symbol_id, depth=3)
                if callees_3:
                    propagation_depth = 3
        
        # Calculate fan-in (number of direct callers)
        direct_callers_count = len(callers_1)
        total_callers = len(callers_1) + len(callers_2) + len(callers_3)
        
        # Calculate fan-out (number of direct callees)
        direct_callees_count = len(callees_1)
        
        # Risk score: higher when many things depend on this symbol
        # Normalized to 0-1 range
        risk_score = min(1.0, direct_callers_count * 0.1 + total_callers * 0.02)
        
        # Calculate total callers count for return
        total_callers_count = total_callers
        
        # Find test files - look for test-related paths
        all_dependents = callers_1 + callers_2 + callers_3
        test_files = [
            {
                "node_id": d["node_id"],
                "name": d["name"],
                "filepath": d["filepath"],
                "kind": d["kind"]
            }
            for d in all_dependents
            if d.get("filepath") and any(
                test_pattern in d["filepath"].lower() 
                for test_pattern in ["test", "spec", "__tests__", ".test.", ".spec."]
            )
        ]
        
        # Direct dependents (excluding test files)
        test_file_node_ids = {d["node_id"] for d in test_files}
        direct_dependents = [
            {
                "node_id": d["node_id"],
                "name": d["name"],
                "filepath": d["filepath"],
                "kind": d["kind"]
            }
            for d in callers_1
            if d["node_id"] not in test_file_node_ids and d.get("filepath") and not any(
                test_pattern in d["filepath"].lower()
                for test_pattern in ["test", "spec", "__tests__", ".test.", ".spec."]
            )
        ]
        
        return {
            "symbol_id": symbol_id,
            "risk_score": round(risk_score, 2),
            "direct_callers_count": direct_callers_count,
            "total_callers_count": total_callers_count,
            "direct_callees_count": direct_callees_count,
            "propagation_depth": propagation_depth,
            "direct_dependents": direct_dependents[:20],  # Limit to 20
            "test_files": test_files[:20],  # Limit to 20
            "all_callers": [
                {
                    "node_id": d["node_id"],
                    "name": d["name"],
                    "filepath": d["filepath"],
                    "kind": d["kind"],
                    "depth": d.get("call_depth", 1)
                }
                for d in callers_1 + callers_2 + callers_3
            ][:50]  # Limit total
        }

    # ------------------------------------------------------------------
    # 3.13  get_traceability - Get requirement links
    # ------------------------------------------------------------------

    async def get_traceability(
        self,
        symbol_id: str,
    ) -> dict[str, Any]:
        """Get traceability links for a symbol.
        
        Finds:
        - DESCRIBED_BY edges: ComponentDescription nodes
        - DETAILED_IN edges: ComponentDoc nodes  
        - PART_OF_ARCHITECTURE edges: ArchitectureDoc nodes
        
        Args:
            symbol_id: The ID of the symbol to trace
            
        Returns:
            Dictionary with requirement_links, test_coverage, architecture_context
        """
        cypher_describes = """
        MATCH (a:ASTNode {id: $symbol_id})-[r:DESCRIBED_BY]->(d:ComponentDesc)
        RETURN d.summary AS summary, d.responsibilities AS responsibilities, 
               d.dependencies AS dependencies, type(r) AS edge_type
        """
        
        cypher_detail = """
        MATCH (a:ASTNode {id: $symbol_id})-[:DESCRIBED_BY]->(d:ComponentDesc)-[r:DETAILED_IN]->(doc:ComponentDoc)
        RETURN doc.algorithm_description AS algorithm, doc.data_flow AS data_flow,
               doc.error_handling AS error_handling, doc.edge_cases AS edge_cases,
               type(r) AS edge_type
        """
        
        cypher_arch = """
        MATCH (a:ASTNode {id: $symbol_id})-[r:PART_OF_ARCHITECTURE]->(h:ArchitectureDoc)
        RETURN h.architectural_role AS role, h.design_patterns AS patterns,
               h.integration_points AS integrations, h.quality_attributes AS quality,
               h.module_path AS module_path, type(r) AS edge_type
        """
        
        async with self._driver.session() as session:
            # Get DESCRIBED_BY links
            result = await session.run(cypher_describes, {"symbol_id": symbol_id})
            described_by = [dict(r) async for r in result]
            
            # Get DETAILED_IN links
            result = await session.run(cypher_detail, {"symbol_id": symbol_id})
            detailed_in = [dict(r) async for r in result]
            
            # Get PART_OF_ARCHITECTURE links
            result = await session.run(cypher_arch, {"symbol_id": symbol_id})
            part_of_arch = [dict(r) async for r in result]
        
        requirement_links = []
        for desc in described_by:
            requirement_links.append({
                "type": "ComponentDescription",
                "summary": desc.get("summary", ""),
                "responsibilities": desc.get("responsibilities", []),
                "dependencies": desc.get("dependencies", []),
                "edge_type": desc.get("edge_type", "DESCRIBED_BY")
            })
        
        for detail in detailed_in:
            requirement_links.append({
                "type": "ComponentDoc",
                "algorithm_description": detail.get("algorithm", ""),
                "data_flow": detail.get("data_flow", ""),
                "error_handling": detail.get("error_handling", ""),
                "edge_cases": detail.get("edge_cases", []),
                "edge_type": detail.get("edge_type", "DETAILED_IN")
            })
        
        architecture_context = []
        for arch in part_of_arch:
            architecture_context.append({
                "module_path": arch.get("module_path", ""),
                "architectural_role": arch.get("role", ""),
                "design_patterns": arch.get("patterns", []),
                "integration_points": arch.get("integrations", []),
                "quality_attributes": arch.get("quality", []),
                "edge_type": arch.get("edge_type", "PART_OF_ARCHITECTURE")
            })
        
        # Check for test coverage (test files that import or reference this symbol)
        cypher_tests = """
        MATCH (test:ASTNode)-[:CALLS|IMPORTS]->(target:ASTNode {id: $symbol_id})
        WHERE test.name CONTAINS 'test' OR test.name CONTAINS 'spec' 
              OR test.filepath CONTAINS 'test' OR test.filepath CONTAINS 'spec'
        RETURN DISTINCT test.id AS node_id, test.name AS name, test.filepath AS filepath
        LIMIT 20
        """
        
        async with self._driver.session() as session:
            result = await session.run(cypher_tests, {"symbol_id": symbol_id})
            test_coverage = [dict(r) async for r in result]
        
        return {
            "symbol_id": symbol_id,
            "requirement_links": requirement_links,
            "test_coverage": [
                {
                    "node_id": t["node_id"],
                    "name": t["name"],
                    "filepath": t["filepath"]
                }
                for t in test_coverage
            ],
            "architecture_context": architecture_context,
            "has_documentation": len(requirement_links) > 0,
            "has_test_coverage": len(test_coverage) > 0,
            "has_architecture_context": len(architecture_context) > 0
        }
