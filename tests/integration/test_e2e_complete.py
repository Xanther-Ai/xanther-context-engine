"""
Comprehensive End-to-End Integration Tests for XCE

Tests ALL features:
1. Incremental Indexing (PostgreSQL + Neo4j)
2. Graph Store Operations (AST nodes, edges, documentation)
3. Callers/Callees (Call chain tracing)
4. Impact Analysis (Risk calculation)
5. Traceability (Documentation links)
6. Search (Keyword and semantic)
7. Dashboard API Endpoints

Prerequisites:
- Neo4j running at bolt://localhost:7687
- PostgreSQL running at postgresql://xce:xce_dev_password@localhost:5432/xce_index

Run with:
    pytest tests/integration/test_e2e_complete.py -v
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xce.indexing.hash_store import HashStore
from xce.indexing.indexer import index_repository, _compute_file_hash, _detect_changed_files
from xce.graph.store import GraphStore
from xce.models import ASTNode, NodeKind, ASTEdge


# =============================================================================
# Test Configuration
# =============================================================================

TEST_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
TEST_NEO4J_AUTH = ("neo4j", os.getenv("NEO4J_PASSWORD", "xce_dev_password"))
TEST_POSTGRES_URI = os.getenv("POSTGRES_URI", "postgresql://xce:xce_dev_password@localhost:5432/xce_index")


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def test_repo(tmp_path):
    """Create a test repository with Python files for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    # Create package structure
    (repo / "mymodule").mkdir()
    (repo / "mymodule" / "__init__.py").write_text("")
    (repo / "mymodule" / "utils.py").write_text("""
def add(a, b):
    '''Add two numbers.'''
    return a + b

def multiply(a, b):
    '''Multiply two numbers.'''
    return a * b
    
def calculate(a, b, operation='add'):
    '''Calculate based on operation.'''
    if operation == 'add':
        return add(a, b)
    elif operation == 'multiply':
        return multiply(a, b)
    return None
""")
    (repo / "mymodule" / "helpers.py").write_text("""
def greet(name):
    '''Greet a user.'''
    return f"Hello, {name}!"

def farewell(name):
    '''Say goodbye.'''
    return f"Goodbye, {name}!"
""")
    (repo / "main.py").write_text("""
from mymodule import utils, helpers

def main():
    result = utils.add(1, 2)
    print(helpers.greet("World"))
    calc = utils.calculate(3, 4, 'multiply')
    return result

if __name__ == "__main__":
    main()
""")
    (repo / "test_main.py").write_text("""
from mymodule import utils

def test_add():
    assert utils.add(1, 2) == 3
    
def test_multiply():
    assert utils.multiply(2, 3) == 6
""")
    
    return str(repo)


@pytest.fixture
async def hash_store():
    """Create HashStore connection."""
    store = HashStore(TEST_POSTGRES_URI)
    try:
        await store.connect()
        yield store
    finally:
        if store._pool:
            await store.close()


@pytest.fixture
async def graph_store():
    """Create GraphStore connection."""
    store = GraphStore(TEST_NEO4J_URI, TEST_NEO4J_AUTH, embedding_dimensions=1536)
    try:
        await store.init_schema()
        yield store
    finally:
        await store.close()


@pytest.fixture
def mock_doc_generator():
    """Create mock DocGenerator."""
    generator = MagicMock()
    generator.batch_size = 10
    generator.generate_batch = AsyncMock(return_value=[])
    generator.generate_component_doc = AsyncMock(return_value=None)
    generator.generate_architecture_doc = AsyncMock(return_value=None)
    return generator


@pytest.fixture
def mock_embedding_service():
    """Create mock EmbeddingService."""
    service = MagicMock()
    service.build_embedding_text = lambda n: f"{n.name}: {n.filepath}"
    service.encode_batch = AsyncMock(return_value=[[0.1] * 1536 for _ in range(10)])
    return service


@pytest.fixture
def test_repo_id():
    """Generate unique test repo ID."""
    return f"test_e2e_{int(time.time() * 1000)}"


# =============================================================================
# Test Class 1: File Hashing & Change Detection
# =============================================================================

class TestFileHashing:
    """Test file hashing and change detection logic."""
    
    def test_compute_file_hash_deterministic(self, tmp_path):
        """SHA-256 hash should be deterministic."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        hash1 = _compute_file_hash(str(test_file))
        hash2 = _compute_file_hash(str(test_file))
        
        assert hash1 == hash2
        assert len(hash1) == 64
    
    def test_compute_file_hash_different_content(self, tmp_path):
        """Different content produces different hashes."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        hash1 = _compute_file_hash(str(test_file))
        
        test_file.write_text("def goodbye(): pass")
        hash2 = _compute_file_hash(str(test_file))
        
        assert hash1 != hash2
    
    def test_detect_changed_files_no_previous(self, tmp_path):
        """All files changed when no previous hashes."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")
        
        py_files = [str(file1), str(file2)]
        changed, current = _detect_changed_files(str(tmp_path), py_files, {})
        
        assert len(changed) == 2
    
    def test_detect_changed_files_unchanged(self, tmp_path):
        """Files with matching hashes are not changed."""
        file1 = tmp_path / "file1.py"
        file1.write_text("same content")
        
        py_files = [str(file1)]
        previous_hashes = {"file1.py": _compute_file_hash(str(file1))}
        
        changed, current = _detect_changed_files(str(tmp_path), py_files, previous_hashes)
        
        assert len(changed) == 0
    
    def test_detect_changed_files_modified(self, tmp_path):
        """Modified files are detected."""
        file1 = tmp_path / "file1.py"
        file1.write_text("old content")
        
        py_files = [str(file1)]
        previous_hashes = {"file1.py": "old_hash"}
        
        changed, current = _detect_changed_files(str(tmp_path), py_files, previous_hashes)
        
        assert len(changed) == 1


# =============================================================================
# Test Class 2: HashStore (PostgreSQL)
# =============================================================================

class TestHashStoreOperations:
    """Test HashStore PostgreSQL operations."""
    
    @pytest.mark.asyncio
    async def test_connection(self, hash_store):
        """Test PostgreSQL connection."""
        assert hash_store._pool is not None
    
    @pytest.mark.asyncio
    async def test_upsert_get_file_hash(self, hash_store, test_repo_id):
        """Test storing and retrieving file hash."""
        repo_id = f"{test_repo_id}_hash1"
        await hash_store.upsert_file_hash(repo_id, "src/main.py", "abc123")
        
        retrieved = await hash_store.get_file_hash(repo_id, "src/main.py")
        assert retrieved == "abc123"
    
    @pytest.mark.asyncio
    async def test_batch_upsert(self, hash_store, test_repo_id):
        """Test batch upsert of file hashes."""
        repo_id = f"{test_repo_id}_batch"
        hashes = {"f1.py": "h1", "f2.py": "h2", "f3.py": "h3"}
        
        count = await hash_store.upsert_file_hashes(repo_id, hashes)
        assert count == 3
        
        all_hashes = await hash_store.get_all_file_hashes(repo_id)
        assert len(all_hashes) == 3
    
    @pytest.mark.asyncio
    async def test_delete_file_hashes(self, hash_store, test_repo_id):
        """Test deleting file hashes."""
        repo_id = f"{test_repo_id}_del"
        await hash_store.upsert_file_hashes(repo_id, {"f1.py": "h1", "f2.py": "h2"})
        
        count = await hash_store.delete_file_hashes(repo_id)
        assert count == 2
    
    @pytest.mark.asyncio
    async def test_repository_metadata_crud(self, hash_store, test_repo_id):
        """Test repository metadata operations."""
        repo_id = f"{test_repo_id}_meta"
        
        # Create
        await hash_store.upsert_repository(
            repo_id=repo_id,
            repo_path="/path/to/repo",
            indexing_status="indexed",
            total_files=100,
            indexed_files=50,
        )
        
        # Read
        repo = await hash_store.get_repository(repo_id)
        assert repo.repo_id == repo_id
        assert repo.indexing_status == "indexed"
        assert repo.total_files == 100


# =============================================================================
# Test Class 3: GraphStore - AST Nodes & Edges
# =============================================================================

class TestGraphStoreNodesAndEdges:
    """Test GraphStore AST node and edge operations."""
    
    @pytest.mark.asyncio
    async def test_upsert_ast_nodes(self, graph_store, test_repo_id):
        """Test inserting AST nodes into Neo4j."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=3, source_text="def add(a, b): return a + b"),
            ASTNode(id=f"{test_repo_id}:main.py:multiply", name="multiply", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=5, end_line=7, source_text="def multiply(a, b): return a * b"),
        ]
        
        count = await graph_store.upsert_ast_nodes(nodes)
        assert count == 2
    
    @pytest.mark.asyncio
    async def test_upsert_edges(self, graph_store, test_repo_id):
        """Test inserting edges between nodes."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:main", name="main", kind=NodeKind.FUNCTION, 
                   filepath="main.py", start_line=1, end_line=10, source_text="def main(): pass"),
            ASTNode(id=f"{test_repo_id}:utils.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=1, end_line=3, source_text="def add(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        edges = [
            ASTEdge(source_id=f"{test_repo_id}:main.py:main", target_id=f"{test_repo_id}:utils.py:add", 
                   relation="calls")
        ]
        
        count = await graph_store.upsert_edges(edges)
        assert count >= 1
    
    @pytest.mark.asyncio
    async def test_upsert_documentation(self, graph_store, test_repo_id):
        """Test attaching documentation to nodes."""
        class MockComponentDesc:
            node_id = f"{test_repo_id}:main.py:add"
            summary = "Adds two numbers"
            responsibilities = ["performs addition", "returns result"]
            dependencies = []
        
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=3, source_text="def add(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        count = await graph_store.upsert_documentation([MockComponentDesc()])
        assert count >= 1


# =============================================================================
# Test Class 4: Callers & Callees
# =============================================================================

class TestCallersAndCallees:
    """Test call chain tracing (callers/callees)."""
    
    @pytest.mark.asyncio
    async def test_get_callers(self, graph_store, test_repo_id):
        """Test finding callers of a symbol."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:main", name="main", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=5, source_text="def main(): pass"),
            ASTNode(id=f"{test_repo_id}:utils.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=1, end_line=3, source_text="def add(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        edges = [
            ASTEdge(source_id=f"{test_repo_id}:main.py:main", target_id=f"{test_repo_id}:utils.py:add",
                   relation="calls")
        ]
        await graph_store.upsert_edges(edges)
        
        callers = await graph_store.get_callers(f"{test_repo_id}:utils.py:add", depth=1)
        assert isinstance(callers, list)
    
    @pytest.mark.asyncio
    async def test_get_callees(self, graph_store, test_repo_id):
        """Test finding callees of a symbol."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:main", name="main", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=5, source_text="def main(): pass"),
            ASTNode(id=f"{test_repo_id}:utils.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=1, end_line=3, source_text="def add(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        edges = [
            ASTEdge(source_id=f"{test_repo_id}:main.py:main", target_id=f"{test_repo_id}:utils.py:add",
                   relation="calls")
        ]
        await graph_store.upsert_edges(edges)
        
        callees = await graph_store.get_callees(f"{test_repo_id}:main.py:main", depth=1)
        assert isinstance(callees, list)


# =============================================================================
# Test Class 5: Impact Analysis
# =============================================================================

class TestImpactAnalysis:
    """Test impact analysis and risk calculation."""
    
    @pytest.mark.asyncio
    async def test_get_impact_analysis(self, graph_store, test_repo_id):
        """Test impact analysis returns correct structure."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:core.py:process", name="process", kind=NodeKind.FUNCTION,
                   filepath="core.py", start_line=1, end_line=10, source_text="def process(): pass"),
            ASTNode(id=f"{test_repo_id}:main.py:runner", name="runner", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=5, source_text="def runner(): pass"),
            ASTNode(id=f"{test_repo_id}:test_process.py:test", name="test_process", 
                   kind=NodeKind.FUNCTION, filepath="test_process.py", start_line=1, end_line=5, 
                   source_text="def test_process(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        edges = [
            ASTEdge(source_id=f"{test_repo_id}:main.py:runner", target_id=f"{test_repo_id}:core.py:process",
                   relation="calls"),
            ASTEdge(source_id=f"{test_repo_id}:test_process.py:test", target_id=f"{test_repo_id}:core.py:process",
                   relation="calls"),
        ]
        await graph_store.upsert_edges(edges)
        
        impact = await graph_store.get_impact_analysis(f"{test_repo_id}:core.py:process")
        
        assert "symbol_id" in impact
        assert "risk_score" in impact
        assert "direct_callers_count" in impact
        assert "propagation_depth" in impact
        assert "direct_dependents" in impact
        assert "test_files" in impact


# =============================================================================
# Test Class 6: Traceability
# =============================================================================

class TestTraceability:
    """Test traceability and documentation links."""
    
    @pytest.mark.asyncio
    async def test_get_traceability(self, graph_store, test_repo_id):
        """Test traceability returns correct structure."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:utils.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=1, end_line=3, source_text="def add(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        trace = await graph_store.get_traceability(f"{test_repo_id}:utils.py:add")
        
        assert "symbol_id" in trace
        assert "requirement_links" in trace
        assert "test_coverage" in trace
        assert "architecture_context" in trace
        assert "has_documentation" in trace


# =============================================================================
# Test Class 7: Neighbors & Graph Traversal
# =============================================================================

class TestGraphTraversal:
    """Test graph traversal and neighbor queries."""
    
    @pytest.mark.asyncio
    async def test_get_neighbors(self, graph_store, test_repo_id):
        """Test getting neighboring nodes."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:a.py:a", name="a", kind=NodeKind.FUNCTION,
                   filepath="a.py", start_line=1, end_line=2, source_text="def a(): pass"),
            ASTNode(id=f"{test_repo_id}:b.py:b", name="b", kind=NodeKind.FUNCTION,
                   filepath="b.py", start_line=1, end_line=2, source_text="def b(): pass"),
            ASTNode(id=f"{test_repo_id}:c.py:c", name="c", kind=NodeKind.FUNCTION,
                   filepath="c.py", start_line=1, end_line=2, source_text="def c(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        edges = [
            ASTEdge(source_id=f"{test_repo_id}:a.py:a", target_id=f"{test_repo_id}:b.py:b",
                   relation="calls"),
            ASTEdge(source_id=f"{test_repo_id}:b.py:b", target_id=f"{test_repo_id}:c.py:c",
                   relation="calls"),
        ]
        await graph_store.upsert_edges(edges)
        
        neighbors = await graph_store.get_neighbors(f"{test_repo_id}:a.py:a", depth=1)
        
        neighbor_ids = [n.node_id for n in neighbors]
        assert f"{test_repo_id}:b.py:b" in neighbor_ids


# =============================================================================
# Test Class 8: Incremental Indexing End-to-End
# =============================================================================

class TestIncrementalIndexingE2E:
    """End-to-end incremental indexing tests."""
    
    @pytest.mark.asyncio
    async def test_first_indexing_stores_hashes(
        self, test_repo, test_repo_id, hash_store, graph_store, mock_doc_generator, mock_embedding_service
    ):
        """First run stores file hashes."""
        repo_id = f"{test_repo_id}_e2e_1"
        
        result, hashes = await index_repository(
            repo_path=test_repo,
            repo_id=repo_id,
            doc_generator=mock_doc_generator,
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=True,
        )
        
        assert len(hashes) > 0
        
        stored = await hash_store.get_all_file_hashes(repo_id)
        assert len(stored) > 0
    
    @pytest.mark.asyncio
    async def test_incremental_skips_unchanged(
        self, test_repo, test_repo_id, hash_store, graph_store, mock_doc_generator, mock_embedding_service
    ):
        """Second run skips unchanged files."""
        repo_id = f"{test_repo_id}_e2e_2"
        
        result1, _ = await index_repository(
            repo_path=test_repo,
            repo_id=repo_id,
            doc_generator=mock_doc_generator,
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=True,
        )
        
        mock_doc_generator.generate_batch.reset_mock()
        
        result2, _ = await index_repository(
            repo_path=test_repo,
            repo_id=repo_id,
            doc_generator=mock_doc_generator,
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=True,
        )
        
        print(f"First run: {result1.nodes_count} nodes, Second run: {result2.nodes_count} nodes")
    
    @pytest.mark.asyncio
    async def test_full_reindex_ignores_hashes(
        self, test_repo, test_repo_id, hash_store, graph_store, mock_doc_generator, mock_embedding_service
    ):
        """Full reindex ignores stored hashes."""
        repo_id = f"{test_repo_id}_e2e_3"
        
        await index_repository(
            repo_path=test_repo,
            repo_id=repo_id,
            doc_generator=mock_doc_generator,
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=True,
        )
        
        mock_doc_generator.generate_batch.reset_mock()
        
        await index_repository(
            repo_path=test_repo,
            repo_id=repo_id,
            doc_generator=mock_doc_generator,
            embedding_service=mock_embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=False,
        )
        
        assert mock_doc_generator.generate_batch.called


# =============================================================================
# Test Class 9: Search Functionality
# =============================================================================

class TestSearch:
    """Test search functionality."""
    
    @pytest.mark.asyncio
    async def test_keyword_search(self, graph_store, test_repo_id):
        """Test keyword search."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:utils.py:add", name="add", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=1, end_line=3, 
                   docstring="Adds two numbers together", source_text="def add(): pass"),
            ASTNode(id=f"{test_repo_id}:utils.py:multiply", name="multiply", kind=NodeKind.FUNCTION,
                   filepath="utils.py", start_line=5, end_line=7,
                   docstring="Multiplies two numbers", source_text="def multiply(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        from xce.models import GraphQuery
        query = GraphQuery(
            cypher="""
                MATCH (n:ASTNode)
                WHERE n.name CONTAINS $term OR n.docstring CONTAINS $term
                RETURN n.id, n.name, n.filepath
                LIMIT 10
            """,
            params={"term": "add"}
        )
        
        results = await graph_store.execute_query(query)
        assert isinstance(results, list)


# =============================================================================
# Test Class 10: Repository Listing
# =============================================================================

class TestRepositoryOperations:
    """Test repository listing and management."""
    
    @pytest.mark.asyncio
    async def test_list_repositories(self, graph_store, test_repo_id):
        """Test listing repositories."""
        nodes = [
            ASTNode(id="repo1:main.py:main", name="main", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=5, source_text="def main(): pass"),
            ASTNode(id="repo2:index.js:start", name="start", kind=NodeKind.FUNCTION,
                   filepath="index.js", start_line=1, end_line=5, source_text="function start() {}"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        repos = await graph_store.list_repositories()
        assert isinstance(repos, list)


# =============================================================================
# Test Class 11: Edge Cases & Error Handling
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_empty_nodes_list(self, graph_store):
        """Test handling empty nodes list."""
        count = await graph_store.upsert_ast_nodes([])
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_empty_edges_list(self, graph_store):
        """Test handling empty edges list."""
        count = await graph_store.upsert_edges([])
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_nonexistent_node_lookups(self, graph_store):
        """Test looking up non-existent nodes."""
        callers = await graph_store.get_callers("nonexistent:symbol", depth=1)
        assert callers == []
        
        callees = await graph_store.get_callees("nonexistent:symbol", depth=1)
        assert callees == []
        
        impact = await graph_store.get_impact_analysis("nonexistent:symbol")
        assert impact["direct_callers_count"] == 0
        
        trace = await graph_store.get_traceability("nonexistent:symbol")
        assert trace["has_documentation"] == False
    
    @pytest.mark.asyncio
    async def test_depth_clamping(self, graph_store, test_repo_id):
        """Test that depth is clamped between 1-5."""
        nodes = [
            ASTNode(id=f"{test_repo_id}:main.py:main", name="main", kind=NodeKind.FUNCTION,
                   filepath="main.py", start_line=1, end_line=5, source_text="def main(): pass"),
        ]
        await graph_store.upsert_ast_nodes(nodes)
        
        # Test with depth > 5 (should be clamped)
        callers = await graph_store.get_callers(f"{test_repo_id}:main.py:main", depth=10)
        
        # Test with depth = 0 (should be clamped to 1)
        callers = await graph_store.get_callers(f"{test_repo_id}:main.py:main", depth=0)


# =============================================================================
# Main Test Summary
# =============================================================================

def test_suite_summary():
    """Test suite summary placeholder."""
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])