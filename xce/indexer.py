"""Repository indexing pipeline.

Orchestrates AST parsing, documentation generation, graph storage,
and embedding generation for an entire repository.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xce.doc_generator import DocGenerator
from xce.embedding_service import EmbeddingService
from xce.graph_store import GraphStore
from xce.models import ASTNode, NodeKind
from xce.parsers import ParserRegistry, get_default_registry

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    """Summary of an indexing run."""

    nodes_count: int = 0
    edges_count: int = 0
    docs_count: int = 0
    embeddings_count: int = 0


# ---------------------------------------------------------------------------
# 6.3  group_by_module
# ---------------------------------------------------------------------------

def group_by_module(nodes: list[ASTNode]) -> dict[str, list[ASTNode]]:
    """Group AST nodes by their directory/package path.

    Nodes are grouped by the directory portion of their ``filepath``.
    Files at the root level are grouped under ``"."``.
    """
    groups: dict[str, list[ASTNode]] = defaultdict(list)
    for node in nodes:
        if "/" in node.filepath:
            module_path = node.filepath.rsplit("/", 1)[0]
        else:
            module_path = "."
        groups[module_path].append(node)
    return dict(groups)


# ---------------------------------------------------------------------------
# 6.2  Incremental indexing helpers
# ---------------------------------------------------------------------------

def _compute_file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_changed_files(
    repo_path: str,
    py_files: list[str],
    previous_hashes: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Return files whose SHA-256 hash differs from the previous index.

    Returns (changed_files, current_hashes).
    """
    current_hashes: dict[str, str] = {}
    changed: list[str] = []

    for abs_path in py_files:
        rel_path = os.path.relpath(abs_path, repo_path)
        file_hash = _compute_file_hash(abs_path)
        current_hashes[rel_path] = file_hash
        if previous_hashes.get(rel_path) != file_hash:
            changed.append(abs_path)

    return changed, current_hashes


# ---------------------------------------------------------------------------
# 6.1  index_repository orchestrator
# ---------------------------------------------------------------------------

async def index_repository(
    repo_path: str,
    repo_id: str,
    *,
    registry: ParserRegistry | None = None,
    parser: Any | None = None,
    doc_generator: DocGenerator,
    embedding_service: EmbeddingService,
    graph_store: GraphStore,
    incremental: bool = True,
    previous_hashes: dict[str, str] | None = None,
) -> tuple[IndexResult, dict[str, str]]:
    """Orchestrate the full indexing pipeline.

    Sequence: parse → store nodes/edges → generate docs → generate embeddings.

    Uses the ParserRegistry to auto-detect the correct parser for each file
    based on its extension. Files with no registered parser are silently skipped.

    Args:
        registry: ParserRegistry instance. If None, uses get_default_registry().
        parser: Deprecated. Legacy ASTParser instance for backward compatibility.
            If provided and registry is None, a registry wrapping this parser is used.

    Returns ``(IndexResult, current_file_hashes)`` so callers can persist
    hashes for the next incremental run.
    """
    if registry is None:
        registry = get_default_registry()

    result = IndexResult()

    # Step 1: Discover source files for all registered extensions
    source_files = _discover_source_files(repo_path, registry)

    # Step 2: Incremental filtering
    if incremental and previous_hashes is not None:
        changed_files, current_hashes = _detect_changed_files(
            repo_path, source_files, previous_hashes,
        )
    else:
        changed_files = source_files
        current_hashes = {}
        for abs_path in source_files:
            rel_path = os.path.relpath(abs_path, repo_path)
            current_hashes[rel_path] = _compute_file_hash(abs_path)

    if not changed_files:
        logger.info("No changed files detected, skipping indexing.")
        return result, current_hashes

    # Step 3: Parse AST using registry-based parser selection
    all_nodes: list[ASTNode] = []
    all_edges = []

    for abs_path in changed_files:
        rel_path = os.path.relpath(abs_path, repo_path)
        parser = registry.get_parser(rel_path)
        if parser is None:
            # No registered parser for this extension — skip silently
            continue
        try:
            source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", abs_path, exc)
            continue
        nodes, edges = parser.parse_file(rel_path, source, repo_id)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    # Cross-file import resolution
    from xce.parser import resolve_cross_file_imports
    cross_edges = resolve_cross_file_imports(all_nodes)
    all_edges.extend(cross_edges)

    # Step 4: Store AST in graph
    result.nodes_count = await graph_store.upsert_ast_nodes(all_nodes)
    result.edges_count = await graph_store.upsert_edges(all_edges)

    # Step 5: Generate documentation in batches
    batch_size = doc_generator.batch_size
    all_descs = []
    for i in range(0, len(all_nodes), batch_size):
        batch = all_nodes[i : i + batch_size]
        descs = await doc_generator.generate_batch(batch)
        all_descs.extend(descs)
        await graph_store.upsert_documentation(descs)

    # Generate LLD for functions/methods
    desc_map = {d.node_id: d for d in all_descs}
    func_nodes = [n for n in all_nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
    for node in func_nodes:
        desc = desc_map.get(node.id)
        if desc:
            lld = await doc_generator.generate_lld(node, desc)
            await graph_store.upsert_documentation([lld])
            result.docs_count += 1

    # Step 6: Generate HLD per module
    modules = group_by_module(all_nodes)
    for module_path, module_nodes in modules.items():
        module_descs = [desc_map[n.id] for n in module_nodes if n.id in desc_map]
        hld = await doc_generator.generate_hld(module_nodes, module_descs)
        await graph_store.upsert_documentation([hld])
        result.docs_count += 1

    result.docs_count += len(all_descs)

    # Step 7: Generate and store embeddings
    texts = [embedding_service.build_embedding_text(n) for n in all_nodes]
    if texts:
        embeddings = await embedding_service.encode_batch(texts)
        node_ids = [n.id for n in all_nodes]
        result.embeddings_count = await graph_store.upsert_embeddings(node_ids, embeddings)

    logger.info(
        "Indexed %d nodes, %d edges, %d docs, %d embeddings",
        result.nodes_count, result.edges_count, result.docs_count, result.embeddings_count,
    )
    return result, current_hashes


def _discover_source_files(repo_path: str, registry: ParserRegistry) -> list[str]:
    """Recursively find all source files under *repo_path* with registered extensions."""
    registered_exts = set(registry.supported_extensions)
    result: list[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
            "__pycache__", "node_modules", "vendor", ".git",
        )]
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in registered_exts:
                result.append(os.path.join(root, f))
    return result


def _discover_py_files(repo_path: str) -> list[str]:
    """Recursively find all ``.py`` files under *repo_path*.

    Kept for backward compatibility with callers that only need Python files.
    """
    result: list[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                result.append(os.path.join(root, f))
    return result
