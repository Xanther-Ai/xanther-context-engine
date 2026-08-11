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
from typing import TYPE_CHECKING, Any, Optional

from xce.indexing.doc_generator import DocGenerator
from xce.indexing.embedding import EmbeddingService
from xce.graph.store import GraphStore
from xce.models import ASTNode, NodeKind
from xce.parsers import ParserRegistry, get_default_registry

if TYPE_CHECKING:
    from xce.indexing.hash_store import HashStore

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

def _is_worth_documenting(node: ASTNode, smart_docs: bool) -> bool:
    """Return True if this node should get LLM-generated docs.

    In smart mode:
    - Modules always get an ArchitectureDoc (handled at module level)
    - Functions/methods only if >= 10 lines of source
    - Classes always (they define structure)
    - Variables, imports, decorators, arguments: never
    """
    if not smart_docs:
        return True  # document everything (original behaviour)

    if node.kind in (NodeKind.VARIABLE, NodeKind.IMPORT, NodeKind.DECORATOR, NodeKind.ARGUMENT):
        return False
    if node.kind == NodeKind.MODULE:
        return False  # modules are handled separately via generate_architecture_doc
    if node.kind == NodeKind.CLASS:
        return True
    if node.kind in (NodeKind.FUNCTION, NodeKind.METHOD):
        source_lines = len((node.source_text or "").splitlines())
        return source_lines >= 10
    return False


async def index_repository(
    repo_path: str,
    repo_id: str,
    *,
    registry: ParserRegistry | None = None,
    parser: Any | None = None,
    doc_generator: DocGenerator,
    embedding_service: EmbeddingService,
    graph_store: GraphStore,
    hash_store: Optional["HashStore"] = None,
    incremental: bool = True,
    smart_docs: bool = False,  # Default False for backward compat; CLI uses True by default
) -> tuple[IndexResult, dict[str, str]]:
    """Orchestrate the full multi-layer indexing pipeline.

    Multi-Layer Architecture:
    - Layer 1: AST Parsing (tree-sitter) → ASTNode objects
    - Layer 2: Component Descriptions (LLD) → ComponentDescription nodes
    - Layer 3: Component Docs (LLD Detailed) → ComponentDoc nodes
    - Layer 4: Architecture Docs (HLD) → ArchitectureDoc nodes
    - Embeddings: Vector embeddings for semantic search
    - Graph Storage: Neo4j storage with relationships
    - Incremental: File hashes stored in PostgreSQL (via HashStore)

    Sequence: 
    1. Parse AST (Layer 1)
    2. Store nodes/edges in graph
    3. Generate component descriptions (Layer 2)
    4. Generate component docs (Layer 3)
    5. Generate architecture docs (Layer 4)
    6. Generate embeddings
    7. Store embeddings in graph
    8. Save file hashes to PostgreSQL for incremental indexing

    Uses the ParserRegistry to auto-detect the correct parser for each file
    based on its extension. Files with no registered parser are silently skipped.

    Args:
        repo_path: Path to the repository to index
        repo_id: Unique identifier for the repository
        registry: ParserRegistry instance. If None, uses get_default_registry().
        parser: Deprecated. Legacy ASTParser instance for backward compatibility.
            If provided and registry is None, a registry wrapping this parser is used.
        doc_generator: DocGenerator for Layers 2-4
        embedding_service: EmbeddingService for vector embeddings
        graph_store: GraphStore for Neo4j operations
        hash_store: HashStore for PostgreSQL (enables incremental indexing)
        incremental: Whether to use incremental indexing (default: True)
        smart_docs: Only generate docs for classes and functions/methods >= 10 lines.
            Skips variables, imports, decorators, and trivial functions.
            Reduces LLM cost by ~80% with minimal quality loss. (default: False)

    Returns ``(IndexResult, current_file_hashes)`` so callers can persist
    hashes for the next incremental run.
    """
    if registry is None:
        registry = get_default_registry()

    result = IndexResult()

    # Step 1: Discover source files for all registered extensions
    source_files = _discover_source_files(repo_path, registry)

    # Step 2: Incremental filtering
    # If hash_store is provided, use PostgreSQL for persistent hash storage
    previous_hashes: dict[str, str] = {}
    if hash_store is not None:
        try:
            previous_hashes = await hash_store.get_all_file_hashes(repo_id)
            logger.info(f"Retrieved {len(previous_hashes)} previous file hashes from PostgreSQL")
        except Exception as e:
            logger.warning(f"Failed to get previous hashes from PostgreSQL: {e}")
            previous_hashes = {}
    
    if incremental and previous_hashes:
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

    # Step 5: Generate documentation in batches (if doc_generator is available)
    all_descs = []
    if doc_generator is not None:
        # Apply smart filtering: skip trivial nodes to save LLM cost
        nodes_for_docs = [n for n in all_nodes if _is_worth_documenting(n, smart_docs)]
        skipped = len(all_nodes) - len(nodes_for_docs)
        if smart_docs and skipped:
            logger.info(
                f"smart_docs: skipping {skipped} trivial nodes "
                f"(variables/imports/short functions), documenting {len(nodes_for_docs)}"
            )

        batch_size = doc_generator.batch_size
        for i in range(0, len(nodes_for_docs), batch_size):
            batch = nodes_for_docs[i : i + batch_size]
            try:
                descs = await doc_generator.generate_batch(batch)
                all_descs.extend(descs)
                await graph_store.upsert_documentation(descs)
            except Exception as e:
                logger.warning(f"Doc generation failed for batch: {e}")

    # Generate ComponentDoc for functions/methods (Layer 3) — skip if no doc_generator
    source_by_id = {n.id: n.source_text or "" for n in all_nodes}
    desc_map = {d.node_id: d for d in all_descs}
    if doc_generator is not None:
        func_nodes = [n for n in all_nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
        for node in func_nodes:
            desc = desc_map.get(node.id)
            if desc:
                component_doc = await doc_generator.generate_component_doc(desc, source_by_id.get(node.id, ""))
                if component_doc:
                    await graph_store.upsert_documentation([component_doc])
                    result.docs_count += 1

    # Step 6: Generate ArchitectureDoc per module (Layer 4) — skip if no doc_generator
    modules = group_by_module(all_nodes)
    if doc_generator is not None:
        for module_path, module_nodes in modules.items():
            module_descs = [desc_map[n.id] for n in module_nodes if n.id in desc_map]
            if module_descs:
                arch_doc = await doc_generator.generate_architecture_doc(module_path, module_descs)
                if arch_doc:
                    await graph_store.upsert_documentation([arch_doc])
                    result.docs_count += 1

    result.docs_count += len(all_descs)

    # Step 7: Generate and store embeddings (if embedding_service is available)
    if embedding_service is not None:
        try:
            texts = [embedding_service.build_embedding_text(n) for n in all_nodes]
            if texts:
                embeddings = await embedding_service.encode_batch(texts)
                node_ids = [n.id for n in all_nodes]
                result.embeddings_count = await graph_store.upsert_embeddings(node_ids, embeddings)
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")

    # Step 8: Save file hashes to PostgreSQL for incremental indexing
    if hash_store is not None and current_hashes:
        try:
            await hash_store.upsert_file_hashes(repo_id, current_hashes)
            logger.info(f"Saved {len(current_hashes)} file hashes to PostgreSQL")
            
            # Update repository metadata
            await hash_store.upsert_repository(
                repo_id=repo_id,
                repo_path=repo_path,
                indexing_status="indexed",
                total_files=len(source_files),
                indexed_files=len(changed_files),
                total_nodes=result.nodes_count,
                total_edges=result.edges_count,
            )
            logger.info(f"Updated repository metadata in PostgreSQL")
        except Exception as e:
            logger.warning(f"Failed to save hashes to PostgreSQL: {e}")

    logger.info(
        "Indexed %d nodes, %d edges, %d docs, %d embeddings",
        result.nodes_count, result.edges_count, result.docs_count, result.embeddings_count,
    )

    # XME Bridge: sync indexed facts + episodes into XME memory layers
    # Enabled via XME_BRIDGE_ENABLED=true in .env
    try:
        import os as _os
        if _os.environ.get("XME_BRIDGE_ENABLED", "").lower() == "true":
            from xce.memory.xme_bridge import XMEBridge
            from datetime import datetime, timezone
            bridge = XMEBridge(
                xme_db_path=_os.environ.get("XME_BRIDGE_DB_PATH", ".xanther/xme.db"),
                neo4j_driver=graph_store._driver,
                opensearch_url=_os.environ.get("XME_BRIDGE_OPENSEARCH_URL") or None,
            )
            bridge_result = await bridge.sync_index(
                repo_id=repo_id,
                nodes=all_nodes,
                edges=all_edges,
                descriptions=all_descs,
                user_id=_os.environ.get("XME_BRIDGE_USER_ID", "xce_agent"),
                index_date=datetime.now(timezone.utc).isoformat(),
            )
            await bridge.close()
            logger.info(
                "XME bridge: %d facts + %d episodes synced",
                bridge_result["facts_written"], bridge_result["episodes_written"],
            )
    except Exception as _e:
        logger.debug("XME bridge sync skipped: %s", _e)

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
