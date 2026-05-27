"""Unit and integration tests for xce.indexer.

Tests verify:
- index_repository orchestration (6.1)
- Incremental indexing via file hash (6.2)
- group_by_module grouping (6.3)
- Integration: index a small test repo, verify graph operations (6.4)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xce.doc_generator import DocGenerator
from xce.embedding_service import EmbeddingService
from xce.indexer import (
    IndexResult,
    _compute_file_hash,
    _detect_changed_files,
    group_by_module,
    index_repository,
)
from xce.models import ASTNode, ComponentDescription, HLDDocument, LLDDocument, NodeKind
from xce.parser import ASTParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    name: str = "func",
    kind: NodeKind = NodeKind.FUNCTION,
    filepath: str = "src/foo.py",
) -> ASTNode:
    return ASTNode(
        id=f"repo:{filepath}:{kind.value}:{name}",
        kind=kind,
        name=name,
        filepath=filepath,
        start_line=1,
        end_line=3,
        source_text=f"def {name}(): pass",
    )


# ---------------------------------------------------------------------------
# 6.3: group_by_module
# ---------------------------------------------------------------------------

class TestGroupByModule:
    def test_groups_by_directory(self):
        nodes = [
            _make_node(name="a", filepath="src/views/main.py"),
            _make_node(name="b", filepath="src/views/utils.py"),
            _make_node(name="c", filepath="src/models/user.py"),
            _make_node(name="d", filepath="root.py"),
        ]
        groups = group_by_module(nodes)
        assert "src/views" in groups
        assert "src/models" in groups
        assert "." in groups
        assert len(groups["src/views"]) == 2
        assert len(groups["src/models"]) == 1
        assert len(groups["."]) == 1

    def test_single_file_at_root(self):
        nodes = [_make_node(name="x", filepath="main.py")]
        groups = group_by_module(nodes)
        assert "." in groups
        assert len(groups["."]) == 1

    def test_empty_list(self):
        groups = group_by_module([])
        assert groups == {}


# ---------------------------------------------------------------------------
# 6.2: Incremental indexing — file hash detection
# ---------------------------------------------------------------------------

class TestIncrementalIndexing:
    def test_compute_file_hash_deterministic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            h1 = _compute_file_hash(f.name)
            h2 = _compute_file_hash(f.name)
        os.unlink(f.name)
        assert h1 == h2

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f1:
            f1.write("x = 1\n")
            f1.flush()
            h1 = _compute_file_hash(f1.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f2:
            f2.write("x = 2\n")
            f2.flush()
            h2 = _compute_file_hash(f2.name)
        os.unlink(f1.name)
        os.unlink(f2.name)
        assert h1 != h2

    def test_detect_changed_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("x = 1\n")
            (Path(tmpdir) / "b.py").write_text("y = 2\n")

            py_files = [
                os.path.join(tmpdir, "a.py"),
                os.path.join(tmpdir, "b.py"),
            ]

            # First run: all files are "changed"
            changed, hashes = _detect_changed_files(tmpdir, py_files, {})
            assert len(changed) == 2

            # Second run with same hashes: no changes
            changed2, hashes2 = _detect_changed_files(tmpdir, py_files, hashes)
            assert len(changed2) == 0

            # Modify one file
            (Path(tmpdir) / "b.py").write_text("y = 999\n")
            changed3, hashes3 = _detect_changed_files(tmpdir, py_files, hashes)
            assert len(changed3) == 1
            assert changed3[0].endswith("b.py")



# ---------------------------------------------------------------------------
# 6.1 / 6.4: Integration test — index a small test repository
# ---------------------------------------------------------------------------

class TestIndexRepository:
    @pytest.mark.asyncio
    async def test_index_small_repo(self):
        """Integration test: index a small repo, verify all pipeline stages
        are called with expected data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a small test repo
            pkg = Path(tmpdir) / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "core.py").write_text(
                "def compute(x):\n"
                "    \"\"\"Compute something.\"\"\"\n"
                "    return x * 2\n"
            )
            (Path(tmpdir) / "main.py").write_text(
                "from pkg.core import compute\n"
                "\n"
                "def run():\n"
                "    return compute(42)\n"
            )

            parser = ASTParser(repo_id="test-repo")

            # Mock DocGenerator
            doc_gen = MagicMock(spec=DocGenerator)
            doc_gen.batch_size = 10

            async def mock_generate_batch(nodes):
                return [
                    ComponentDescription(
                        node_id=n.id,
                        summary=f"Description of {n.name}",
                        responsibilities=["compute"],
                        dependencies=[],
                    )
                    for n in nodes
                ]

            async def mock_generate_lld(node, desc, callees=None):
                return LLDDocument(
                    component_id=node.id,
                    algorithm_description=f"Algorithm for {node.name}",
                    data_flow="in -> out",
                    error_handling="none",
                    edge_cases=[],
                )

            async def mock_generate_hld(module_nodes, descs):
                fp = module_nodes[0].filepath if module_nodes else ""
                mp = fp.rsplit("/", 1)[0] if "/" in fp else "."
                return HLDDocument(
                    module_path=mp,
                    architectural_role="utility",
                    design_patterns=[],
                    integration_points=[],
                    quality_attributes=[],
                )

            doc_gen.generate_batch = mock_generate_batch
            doc_gen.generate_lld = mock_generate_lld
            doc_gen.generate_hld = mock_generate_hld

            # Mock EmbeddingService
            embed_svc = MagicMock(spec=EmbeddingService)

            def mock_build_text(node):
                return f"{node.kind.value}: {node.name}"

            async def mock_encode_batch(texts, batch_size=100):
                return [[0.1, 0.2, 0.3] for _ in texts]

            embed_svc.build_embedding_text = mock_build_text
            embed_svc.encode_batch = mock_encode_batch

            # Mock GraphStore
            graph_store = AsyncMock()
            graph_store.upsert_ast_nodes = AsyncMock(return_value=5)
            graph_store.upsert_edges = AsyncMock(return_value=3)
            graph_store.upsert_documentation = AsyncMock(return_value=1)
            graph_store.upsert_embeddings = AsyncMock(return_value=5)

            # Run indexing
            result, hashes = await index_repository(
                repo_path=tmpdir,
                repo_id="test-repo",
                parser=parser,
                doc_generator=doc_gen,
                embedding_service=embed_svc,
                graph_store=graph_store,
                incremental=False,
            )

            # Verify results
            assert result.nodes_count == 5  # from mock
            assert result.edges_count == 3
            assert result.embeddings_count == 5

            # Verify graph_store was called
            graph_store.upsert_ast_nodes.assert_called_once()
            graph_store.upsert_edges.assert_called_once()
            assert graph_store.upsert_documentation.call_count >= 1
            graph_store.upsert_embeddings.assert_called_once()

            # Verify hashes were computed
            assert len(hashes) >= 2  # at least main.py and pkg/core.py

    @pytest.mark.asyncio
    async def test_incremental_skips_unchanged(self):
        """Verify incremental indexing skips unchanged files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("x = 1\n")
            (Path(tmpdir) / "b.py").write_text("y = 2\n")

            parser = ASTParser(repo_id="test-repo")

            doc_gen = MagicMock(spec=DocGenerator)
            doc_gen.batch_size = 10

            async def mock_generate_batch(nodes):
                return [
                    ComponentDescription(node_id=n.id, summary="desc")
                    for n in nodes
                ]

            async def mock_generate_lld(node, desc, callees=None):
                return LLDDocument(
                    component_id=node.id,
                    algorithm_description="algo",
                    data_flow="",
                    error_handling="",
                )

            async def mock_generate_hld(module_nodes, descs):
                return HLDDocument(module_path=".", architectural_role="util")

            doc_gen.generate_batch = mock_generate_batch
            doc_gen.generate_lld = mock_generate_lld
            doc_gen.generate_hld = mock_generate_hld

            embed_svc = MagicMock(spec=EmbeddingService)
            embed_svc.build_embedding_text = lambda n: n.name
            embed_svc.encode_batch = AsyncMock(return_value=[[0.1] * 3])

            graph_store = AsyncMock()
            graph_store.upsert_ast_nodes = AsyncMock(return_value=2)
            graph_store.upsert_edges = AsyncMock(return_value=0)
            graph_store.upsert_documentation = AsyncMock(return_value=1)
            graph_store.upsert_embeddings = AsyncMock(return_value=2)

            # First index
            result1, hashes1 = await index_repository(
                repo_path=tmpdir,
                repo_id="test-repo",
                parser=parser,
                doc_generator=doc_gen,
                embedding_service=embed_svc,
                graph_store=graph_store,
                incremental=True,
                previous_hashes=None,
            )
            assert result1.nodes_count > 0

            # Reset mocks
            graph_store.reset_mock()

            # Second index with same hashes — should skip
            result2, hashes2 = await index_repository(
                repo_path=tmpdir,
                repo_id="test-repo",
                parser=parser,
                doc_generator=doc_gen,
                embedding_service=embed_svc,
                graph_store=graph_store,
                incremental=True,
                previous_hashes=hashes1,
            )
            assert result2.nodes_count == 0
            graph_store.upsert_ast_nodes.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_contains_expected_nodes_and_edges(self):
        """Verify the parser produces expected nodes and edges for the
        graph_store to receive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "lib.py").write_text(
                "def helper():\n    return 1\n"
            )
            (Path(tmpdir) / "app.py").write_text(
                "from lib import helper\n\ndef main():\n    helper()\n"
            )

            parser = ASTParser(repo_id="test-repo")

            doc_gen = MagicMock(spec=DocGenerator)
            doc_gen.batch_size = 10

            async def mock_generate_batch(nodes):
                return [
                    ComponentDescription(node_id=n.id, summary="desc")
                    for n in nodes
                ]

            async def mock_generate_lld(node, desc, callees=None):
                return LLDDocument(
                    component_id=node.id,
                    algorithm_description="algo",
                    data_flow="",
                    error_handling="",
                )

            async def mock_generate_hld(module_nodes, descs):
                return HLDDocument(module_path=".", architectural_role="util")

            doc_gen.generate_batch = mock_generate_batch
            doc_gen.generate_lld = mock_generate_lld
            doc_gen.generate_hld = mock_generate_hld

            embed_svc = MagicMock(spec=EmbeddingService)
            embed_svc.build_embedding_text = lambda n: n.name
            embed_svc.encode_batch = AsyncMock(return_value=[[0.1] * 3])

            # Capture what gets passed to graph_store
            captured_nodes = []
            captured_edges = []

            async def capture_nodes(nodes):
                captured_nodes.extend(nodes)
                return len(nodes)

            async def capture_edges(edges):
                captured_edges.extend(edges)
                return len(edges)

            graph_store = AsyncMock()
            graph_store.upsert_ast_nodes = capture_nodes
            graph_store.upsert_edges = capture_edges
            graph_store.upsert_documentation = AsyncMock(return_value=1)
            graph_store.upsert_embeddings = AsyncMock(return_value=1)

            await index_repository(
                repo_path=tmpdir,
                repo_id="test-repo",
                parser=parser,
                doc_generator=doc_gen,
                embedding_service=embed_svc,
                graph_store=graph_store,
                incremental=False,
            )

            # Verify expected nodes
            node_names = {n.name for n in captured_nodes}
            assert "helper" in node_names
            assert "main" in node_names  # function
            assert "lib" in node_names  # module
            assert "app" in node_names  # module

            # Verify expected edges
            edge_relations = {e.relation for e in captured_edges}
            assert "contains" in edge_relations
            # Should have imports edge from cross-file resolution
            assert "imports" in edge_relations
