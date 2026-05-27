"""Unit tests for xce.graph_store.GraphStore.

Since we cannot run a real Neo4j instance in unit tests, we mock the
neo4j async driver and verify Cypher query construction, parameter
passing, result transformation, and idempotency logic.

Integration tests that need a live Neo4j are marked with
``@pytest.mark.integration``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xce.graph_store import GraphStore, _RELATION_MAP, _build_schema_constraints
from xce.models import ASTEdge, ASTNode, GraphQuery, NodeKind, SearchResult


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_node(
    repo_id: str = "repo1",
    filepath: str = "src/foo.py",
    kind: NodeKind = NodeKind.FUNCTION,
    name: str = "my_func",
    **overrides: Any,
) -> ASTNode:
    defaults = dict(
        id=f"{repo_id}:{filepath}:{kind.value}:{name}",
        kind=kind,
        name=name,
        filepath=filepath,
        start_line=1,
        end_line=10,
        source_text="def my_func(): pass",
    )
    defaults.update(overrides)
    return ASTNode(**defaults)


def _make_edge(
    src_id: str = "repo1:a.py:function:foo",
    tgt_id: str = "repo1:a.py:function:bar",
    relation: str = "calls",
) -> ASTEdge:
    return ASTEdge(source_id=src_id, target_id=tgt_id, relation=relation)


# ---------------------------------------------------------------------------
# Mock driver helpers
# ---------------------------------------------------------------------------

class _FakeRecord(dict):
    """Minimal dict-like record returned by the mock driver."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


class _FakeResult:
    """Async-iterable result set returned by session.run()."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = [_FakeRecord(r) for r in (records or [])]
        self._idx = 0

    async def single(self) -> _FakeRecord | None:
        return self._records[0] if self._records else None

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._records):
            raise StopAsyncIteration
        rec = self._records[self._idx]
        self._idx += 1
        return rec


class _AsyncContextManager:
    """A simple async context manager wrapping a session mock."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _mock_driver(run_side_effect=None, default_records=None):
    """Return a patched AsyncGraphDatabase.driver that captures queries."""
    driver = MagicMock()
    session = AsyncMock()

    if run_side_effect is not None:
        session.run = AsyncMock(side_effect=run_side_effect)
    elif default_records is not None:
        session.run = AsyncMock(return_value=_FakeResult(default_records))
    else:
        session.run = AsyncMock(return_value=_FakeResult([{"cnt": 1}]))

    # driver.session() must return an async context manager (not a coroutine)
    driver.session.return_value = _AsyncContextManager(session)
    driver.close = AsyncMock()
    return driver, session


# ===================================================================
# Test: Schema constraints (3.2)
# ===================================================================

class TestSchemaConstraints:
    def test_default_dimensions(self):
        stmts = _build_schema_constraints(512)
        assert len(stmts) == 6
        # Uniqueness constraints
        assert any("ASTNode" in s and "UNIQUE" in s for s in stmts)
        assert any("Repository" in s and "UNIQUE" in s for s in stmts)
        # Indexes
        assert any("ast_kind_idx" in s for s in stmts)
        assert any("ast_filepath_idx" in s for s in stmts)
        assert any("ast_name_idx" in s for s in stmts)
        # Vector index with correct dimensions
        vec_stmt = [s for s in stmts if "VECTOR" in s][0]
        assert "512" in vec_stmt
        assert "cosine" in vec_stmt

    def test_custom_dimensions(self):
        stmts = _build_schema_constraints(1536)
        vec_stmt = [s for s in stmts if "VECTOR" in s][0]
        assert "1536" in vec_stmt

    @pytest.mark.asyncio
    async def test_init_schema_runs_all_statements(self):
        driver, session = _mock_driver()
        with patch("xce.graph_store.AsyncGraphDatabase.driver", return_value=driver):
            store = GraphStore.__new__(GraphStore)
            store._driver = driver
            store._embedding_dimensions = 512
            await store.init_schema()
        assert session.run.call_count == 6


# ===================================================================
# Test: upsert_ast_nodes (3.3)
# ===================================================================

class TestUpsertASTNodes:
    @pytest.mark.asyncio
    async def test_upsert_returns_count(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        node = _make_node()
        count = await store.upsert_ast_nodes([node])
        assert count == 1
        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_empty_list(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        count = await store.upsert_ast_nodes([])
        assert count == 0
        session.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_passes_correct_params(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        node = _make_node(name="hello", kind=NodeKind.CLASS)
        await store.upsert_ast_nodes([node])

        call_args = session.run.call_args
        params = call_args[0][1]["nodes"]
        assert len(params) == 1
        assert params[0]["name"] == "hello"
        assert params[0]["kind"] == "class"
        assert params[0]["repo_id"] == "repo1"

    @pytest.mark.asyncio
    async def test_upsert_uses_merge(self):
        """Verify the Cypher uses MERGE (not CREATE) for idempotency."""
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        await store.upsert_ast_nodes([_make_node()])
        cypher = session.run.call_args[0][0]
        assert "MERGE" in cypher
        assert "CREATE" not in cypher.replace("CREATE CONSTRAINT", "")


# ===================================================================
# Test: upsert_edges (3.4)
# ===================================================================

class TestUpsertEdges:
    @pytest.mark.asyncio
    async def test_upsert_edges_returns_count(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        edge = _make_edge()
        count = await store.upsert_edges([edge])
        assert count == 1

    @pytest.mark.asyncio
    async def test_upsert_edges_empty(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        count = await store.upsert_edges([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_edges_grouped_by_relation(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        edges = [
            _make_edge(relation="calls"),
            _make_edge(relation="imports"),
            _make_edge(relation="calls"),
        ]
        await store.upsert_edges(edges)
        # Two distinct relation types → two session.run calls
        assert session.run.call_count == 2

    @pytest.mark.asyncio
    async def test_edge_relation_mapping(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        await store.upsert_edges([_make_edge(relation="inherits")])
        cypher = session.run.call_args[0][0]
        assert "INHERITS" in cypher
        assert "MERGE" in cypher


# ===================================================================
# Test: upsert_documentation (3.5)
# ===================================================================

@dataclass
class _FakeComponentDesc:
    node_id: str
    summary: str
    responsibilities: list[str]
    dependencies: list[str]


@dataclass
class _FakeLLDDoc:
    component_id: str
    algorithm_description: str
    data_flow: str
    error_handling: str
    edge_cases: list[str]


@dataclass
class _FakeHLDDoc:
    module_path: str
    architectural_role: str
    design_patterns: list[str]
    integration_points: list[str]
    quality_attributes: list[str]


class TestUpsertDocumentation:
    @pytest.mark.asyncio
    async def test_component_desc(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        doc = _FakeComponentDesc(
            node_id="repo1:a.py:function:foo",
            summary="Does stuff",
            responsibilities=["compute"],
            dependencies=["bar"],
        )
        count = await store.upsert_documentation([doc])
        assert count == 1
        cypher = session.run.call_args[0][0]
        assert "DESCRIBED_BY" in cypher
        assert "ComponentDesc" in cypher

    @pytest.mark.asyncio
    async def test_lld_doc(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        doc = _FakeLLDDoc(
            component_id="repo1:a.py:function:foo",
            algorithm_description="BFS",
            data_flow="in -> out",
            error_handling="raises ValueError",
            edge_cases=["empty input"],
        )
        count = await store.upsert_documentation([doc])
        assert count == 1
        cypher = session.run.call_args[0][0]
        assert "DETAILED_IN" in cypher
        assert "LLDDoc" in cypher

    @pytest.mark.asyncio
    async def test_hld_doc(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        doc = _FakeHLDDoc(
            module_path="src/views",
            architectural_role="controller",
            design_patterns=["MVC"],
            integration_points=["REST API"],
            quality_attributes=["testable"],
        )
        count = await store.upsert_documentation([doc])
        assert count == 1
        cypher = session.run.call_args[0][0]
        assert "PART_OF_HLD" in cypher
        assert "HLDDoc" in cypher

    @pytest.mark.asyncio
    async def test_empty_docs(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        count = await store.upsert_documentation([])
        assert count == 0


# ===================================================================
# Test: upsert_embeddings (3.6)
# ===================================================================

class TestUpsertEmbeddings:
    @pytest.mark.asyncio
    async def test_upsert_embeddings_returns_count(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        count = await store.upsert_embeddings(
            ["repo1:a.py:function:foo"],
            [[0.1, 0.2, 0.3]],
        )
        assert count == 1
        cypher = session.run.call_args[0][0]
        assert "HAS_EMBEDDING" in cypher
        assert "MERGE" in cypher

    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises(self):
        driver, _ = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        with pytest.raises(ValueError, match="dimensions"):
            await store.upsert_embeddings(
                ["repo1:a.py:function:foo"],
                [[0.1, 0.2]],  # wrong dim
            )

    @pytest.mark.asyncio
    async def test_length_mismatch_raises(self):
        driver, _ = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        with pytest.raises(ValueError, match="same length"):
            await store.upsert_embeddings(
                ["id1", "id2"],
                [[0.1, 0.2, 0.3]],
            )

    @pytest.mark.asyncio
    async def test_empty_embeddings(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        count = await store.upsert_embeddings([], [])
        assert count == 0
        session.run.assert_not_called()


# ===================================================================
# Test: semantic_search (3.7)
# ===================================================================

class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_returns_search_results(self):
        records = [
            {"node_id": "repo1:a.py:function:foo", "score": 0.95, "node_data": {"name": "foo", "kind": "function"}},
            {"node_id": "repo1:a.py:function:bar", "score": 0.80, "node_data": {"name": "bar", "kind": "function"}},
        ]
        driver, session = _mock_driver(default_records=records)
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        results = await store.semantic_search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises(self):
        driver, _ = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        with pytest.raises(ValueError, match="dimensions"):
            await store.semantic_search([0.1, 0.2], top_k=5)

    @pytest.mark.asyncio
    async def test_node_kinds_filter(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        await store.semantic_search(
            [0.1, 0.2, 0.3],
            top_k=5,
            node_kinds=[NodeKind.FUNCTION, NodeKind.CLASS],
        )
        cypher = session.run.call_args[0][0]
        assert "a.kind IN $kinds" in cypher
        params = session.run.call_args[0][1]
        assert params["kinds"] == ["function", "class"]

    @pytest.mark.asyncio
    async def test_repo_id_filter(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        await store.semantic_search(
            [0.1, 0.2, 0.3],
            top_k=5,
            repo_id="my_repo",
        )
        cypher = session.run.call_args[0][0]
        assert "a.repo_id = $repo_id" in cypher

    @pytest.mark.asyncio
    async def test_results_sorted_descending(self):
        records = [
            {"node_id": "a", "score": 0.5, "node_data": {}},
            {"node_id": "b", "score": 0.9, "node_data": {}},
            {"node_id": "c", "score": 0.7, "node_data": {}},
        ]
        driver, session = _mock_driver(default_records=records)
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        results = await store.semantic_search([0.1, 0.2, 0.3], top_k=10)
        # The mock returns records in order; the Cypher has ORDER BY score DESC
        # so we verify the query includes the ordering clause.
        cypher = session.run.call_args[0][0]
        assert "ORDER BY score DESC" in cypher


# ===================================================================
# Test: execute_query & get_neighbors (3.8)
# ===================================================================

class TestExecuteQuery:
    @pytest.mark.asyncio
    async def test_returns_records(self):
        records = [{"n": {"id": "x", "name": "x_func"}}]
        driver, session = _mock_driver(default_records=records)
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        result = await store.execute_query(
            GraphQuery(cypher="MATCH (n) RETURN n", params={})
        )
        assert len(result) == 1
        assert result[0]["n"]["id"] == "x"

    @pytest.mark.asyncio
    async def test_passes_params(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        await store.execute_query(
            GraphQuery(cypher="MATCH (n {id: $nid}) RETURN n", params={"nid": "abc"})
        )
        call_args = session.run.call_args
        assert call_args[0][1] == {"nid": "abc"}


class TestGetNeighbors:
    @pytest.mark.asyncio
    async def test_returns_search_results(self):
        records = [
            {"node_id": "repo1:a.py:function:bar", "node_data": {"name": "bar"}},
        ]
        driver, session = _mock_driver(default_records=records)
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        results = await store.get_neighbors("repo1:a.py:function:foo")
        assert len(results) == 1
        assert results[0].node_id == "repo1:a.py:function:bar"

    @pytest.mark.asyncio
    async def test_relation_filter(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        await store.get_neighbors("nid", relation="calls", depth=2)
        cypher = session.run.call_args[0][0]
        assert "CALLS" in cypher

    @pytest.mark.asyncio
    async def test_no_relation_filter(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        await store.get_neighbors("nid", depth=3)
        cypher = session.run.call_args[0][0]
        assert "*1..3" in cypher


# ===================================================================
# Test: Data isolation by repo_id (Req 3.4)
# ===================================================================

class TestDataIsolation:
    @pytest.mark.asyncio
    async def test_upsert_stores_repo_id(self):
        """Verify that upsert_ast_nodes includes repo_id in the params."""
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        node = _make_node(repo_id="alpha")
        await store.upsert_ast_nodes([node])
        params = session.run.call_args[0][1]["nodes"]
        assert params[0]["repo_id"] == "alpha"

    @pytest.mark.asyncio
    async def test_semantic_search_scoped_to_repo(self):
        driver, session = _mock_driver(default_records=[])
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        await store.semantic_search([0.1, 0.2, 0.3], top_k=5, repo_id="beta")
        cypher = session.run.call_args[0][0]
        assert "a.repo_id = $repo_id" in cypher
        params = session.run.call_args[0][1]
        assert params["repo_id"] == "beta"


# ===================================================================
# Test: Upsert idempotency (P11)
# ===================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_double_upsert_nodes_uses_merge(self):
        """Calling upsert twice should use MERGE, not CREATE."""
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        node = _make_node()
        await store.upsert_ast_nodes([node])
        await store.upsert_ast_nodes([node])

        # Both calls should use MERGE
        for call in session.run.call_args_list:
            cypher = call[0][0]
            assert "MERGE" in cypher

    @pytest.mark.asyncio
    async def test_double_upsert_edges_uses_merge(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        edge = _make_edge()
        await store.upsert_edges([edge])
        await store.upsert_edges([edge])

        for call in session.run.call_args_list:
            cypher = call[0][0]
            assert "MERGE" in cypher

    @pytest.mark.asyncio
    async def test_double_upsert_embeddings_uses_merge(self):
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        await store.upsert_embeddings(["id1"], [[0.1, 0.2, 0.3]])
        await store.upsert_embeddings(["id1"], [[0.4, 0.5, 0.6]])

        for call in session.run.call_args_list:
            cypher = call[0][0]
            assert "MERGE" in cypher


# ===================================================================
# Property-based tests
# ===================================================================

# Strategy: generate a list of SearchResult-like records with random scores
_score_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


class TestPropertySemanticSearch:
    """**Validates: Requirements 3.3** — P9: Semantic search results bounded
    by top_k and sorted by descending score."""

    @given(
        scores=st.lists(_score_st, min_size=0, max_size=30),
        top_k=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_results_bounded_and_sorted(self, scores: list[float], top_k: int):
        """P9: len(results) <= top_k AND results sorted descending by score."""
        # Build mock records sorted descending (simulating Neo4j ORDER BY)
        sorted_scores = sorted(scores, reverse=True)[:top_k]
        records = [
            {"node_id": f"n{i}", "score": s, "node_data": {"name": f"n{i}"}}
            for i, s in enumerate(sorted_scores)
        ]

        driver, session = _mock_driver(default_records=records)
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 3

        results = await store.semantic_search([0.1, 0.2, 0.3], top_k=top_k)

        # Bounded by top_k
        assert len(results) <= top_k
        # Sorted descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


class TestPropertyIdempotentUpsert:
    """**Validates: Requirements 3.2** — P11: Idempotent indexing
    (upsert twice = same result)."""

    @given(
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
            min_size=1,
            max_size=20,
        ),
        kind=st.sampled_from(list(NodeKind)),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_upsert_always_uses_merge(self, name: str, kind: NodeKind):
        """P11: Every upsert call uses MERGE, guaranteeing idempotency."""
        driver, session = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512

        node = _make_node(name=name, kind=kind)
        await store.upsert_ast_nodes([node])
        await store.upsert_ast_nodes([node])

        for call in session.run.call_args_list:
            cypher = call[0][0]
            assert "MERGE" in cypher
            # Ensure no raw CREATE (which would duplicate)
            assert "CREATE (" not in cypher


# ===================================================================
# Test: GraphStore __init__ (3.1)
# ===================================================================

class TestGraphStoreInit:
    def test_init_creates_driver(self):
        with patch("xce.graph_store.AsyncGraphDatabase.driver") as mock_driver_fn:
            mock_driver_fn.return_value = MagicMock()
            store = GraphStore(
                neo4j_uri="bolt://localhost:7687",
                neo4j_auth=("neo4j", "password"),
            )
            mock_driver_fn.assert_called_once_with(
                "bolt://localhost:7687",
                auth=("neo4j", "password"),
            )

    def test_init_custom_dimensions(self):
        with patch("xce.graph_store.AsyncGraphDatabase.driver") as mock_driver_fn:
            mock_driver_fn.return_value = MagicMock()
            store = GraphStore(
                neo4j_uri="bolt://localhost:7687",
                neo4j_auth=("neo4j", "password"),
                embedding_dimensions=1536,
            )
            assert store._embedding_dimensions == 1536

    @pytest.mark.asyncio
    async def test_close(self):
        driver, _ = _mock_driver()
        store = GraphStore.__new__(GraphStore)
        store._driver = driver
        store._embedding_dimensions = 512
        await store.close()
        driver.close.assert_awaited_once()
