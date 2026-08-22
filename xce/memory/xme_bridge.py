"""XCE → XME Bridge: Sync indexed code knowledge into XME memory layers.

After XCE completes a repository index, this bridge:
1. Writes code facts (symbols, descriptions, edges) into XME's temporal fact graph (Neo4j)
2. Writes file-level episodes into XME's episodic store (OpenSearch or SQLite)

This makes XCE's code graph the "long-term fact memory" for coding agents,
while episodic sessions capture the actual code content for retrieval.

Usage:
    from xce.memory.xme_bridge import XMEBridge

    bridge = XMEBridge(xme_settings, neo4j_driver)
    await bridge.sync_index(
        repo_id="my-repo",
        nodes=state.all_nodes,
        edges=state.all_edges,
        descriptions=state.all_descriptions,
        user_id="agent",
        index_date=datetime.now().isoformat(),
    )
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from xce.models import ASTNode, ASTEdge, ComponentDescription
    from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fact type constants — mirror XME's fact_type taxonomy
# ---------------------------------------------------------------------------
_FT_SYMBOL = "code_symbol"
_FT_DESCRIPTION = "code_description"
_FT_DEPENDENCY = "code_dependency"
_FT_ARCHITECTURE = "code_architecture"


class XMEBridge:
    """Bridges XCE indexed data into XME memory layers.

    Args:
        xme_db_path:  Path to XME's SQLite db (episodic fallback).
        neo4j_driver: Shared Neo4j driver (same instance used by XCE's GraphStore).
                      The bridge stores XME PersonalFact nodes in the same database
                      as XCE ASTNodes — different labels, no collision.
        embedder:     Optional XME LocalEmbedder for fact embeddings.
                      If None, embeddings are skipped (facts still stored).
    """

    def __init__(
        self,
        xme_db_path: str = ".xanther/xme.db",
        neo4j_driver: Optional[Any] = None,
        embedder: Optional[Any] = None,
        opensearch_url: Optional[str] = None,
    ) -> None:
        self._xme_db_path = xme_db_path
        self._driver = neo4j_driver
        self._embedder = embedder
        self._opensearch_url = opensearch_url
        self._tfg: Optional[Any] = None   # TemporalFactGraph (lazy init)
        self._episodic: Optional[Any] = None  # EpisodicStore (lazy init)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _init_layers(self) -> None:
        """Lazily initialise XME layers on first use."""
        if self._tfg is None and self._driver is not None:
            try:
                import sys, os
                # Try to import XME if it's on the path
                xme_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "xanther-memory-engine")
                if os.path.isdir(xme_path) and xme_path not in sys.path:
                    sys.path.insert(0, xme_path)
                from xme.layers.temporal_graph import TemporalFactGraph
                self._tfg = TemporalFactGraph(self._driver)
                await self._tfg.init_schema()
                logger.info("XME TemporalFactGraph initialised")
            except ImportError as e:
                logger.warning("XME not available, fact sync disabled: %s", e)

        if self._episodic is None:
            try:
                import sys, os
                xme_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "xanther-memory-engine")
                if os.path.isdir(xme_path) and xme_path not in sys.path:
                    sys.path.insert(0, xme_path)
                from xme.layers.episodic import EpisodicStore
                self._episodic = EpisodicStore(
                    opensearch_url=self._opensearch_url or "http://localhost:9200",
                    sqlite_path=self._xme_db_path,
                    opensearch_enabled=bool(self._opensearch_url),
                    embedding_dims=384,
                )
                self._episodic.connect()
                logger.info("XME EpisodicStore initialised (opensearch=%s)", bool(self._opensearch_url))
            except ImportError as e:
                logger.warning("XME EpisodicStore not available: %s", e)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def sync_index(
        self,
        repo_id: str,
        nodes: list["ASTNode"],
        edges: list["ASTEdge"],
        descriptions: list["ComponentDescription"],
        user_id: str = "xce_agent",
        index_date: Optional[str] = None,
    ) -> dict[str, int]:
        """Sync a completed XCE index into XME memory.

        Returns a dict with counts: facts_written, episodes_written.
        """
        await self._init_layers()
        date = index_date or datetime.now(timezone.utc).isoformat()

        # Build lookup maps
        desc_by_node: dict[str, Any] = {d.node_id: d for d in descriptions}

        facts_written = 0
        if self._tfg is not None:
            facts_written = await self._sync_facts(
                repo_id, nodes, edges, desc_by_node, user_id, date
            )

        episodes_written = 0
        if self._episodic is not None:
            episodes_written = await self._sync_episodes(
                repo_id, nodes, desc_by_node, date
            )

        logger.info(
            "XME sync complete: %d facts, %d episodes (repo=%s)",
            facts_written, episodes_written, repo_id,
        )
        return {"facts_written": facts_written, "episodes_written": episodes_written}

    # ------------------------------------------------------------------
    # Fact sync → Neo4j PersonalFact nodes (via TemporalFactGraph)
    # ------------------------------------------------------------------

    async def _sync_facts(
        self,
        repo_id: str,
        nodes: list["ASTNode"],
        edges: list["ASTEdge"],
        desc_by_node: dict[str, Any],
        user_id: str,
        date: str,
    ) -> int:
        """Write code symbols and descriptions as XME PersonalFact nodes."""
        from xce.models import NodeKind
        written = 0

        # Only store meaningful symbols (not imports/args/decorators)
        symbol_kinds = {NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.MODULE}

        for node in nodes:
            if node.kind not in symbol_kinds:
                continue

            # Build a rich value string: signature + docstring summary
            parts = []
            if node.signature:
                parts.append(node.signature)
            desc = desc_by_node.get(node.id)
            if desc and hasattr(desc, "summary") and desc.summary:
                parts.append(desc.summary)
            elif node.docstring:
                parts.append(node.docstring[:200])
            if not parts:
                parts.append(f"{node.kind.value} in {node.filepath}")

            value = " — ".join(parts)[:400]
            attribute = f"{node.kind.value}.{node.name}"[:80]

            # Get embedding if available
            emb = None
            if self._embedder is not None:
                try:
                    emb = self._embedder.embed(f"{attribute}: {value}")
                except Exception:
                    pass

            try:
                await self._tfg.upsert_fact(
                    user_id=user_id,
                    attribute=attribute,
                    value=value,
                    fact_type=_FT_SYMBOL,
                    session_id=f"index:{repo_id}:{node.filepath}",
                    session_date=date,
                    embedding=emb,
                    project_id=repo_id,
                )
                written += 1
            except Exception as e:
                logger.debug("Failed to write fact for %s: %s", node.id, e)

        # Write dependency edges as facts (top-level CALLS and IMPORTS only)
        dep_counts: dict[str, int] = {}
        for edge in edges:
            if edge.relation in ("calls", "imports", "inherits"):
                src_name = edge.source_id.split(":")[-1] if ":" in edge.source_id else edge.source_id
                tgt_name = edge.target_id.split(":")[-1] if ":" in edge.target_id else edge.target_id
                key = f"{edge.relation}:{src_name}"
                dep_counts[key] = dep_counts.get(key, 0) + 1
                if dep_counts[key] > 3:
                    continue  # Cap per-source deps to avoid noise

                attribute = f"{edge.relation}_dependency"[:80]
                value = f"{src_name} → {tgt_name}"[:200]

                try:
                    await self._tfg.upsert_fact(
                        user_id=user_id,
                        attribute=attribute,
                        value=value,
                        fact_type=_FT_DEPENDENCY,
                        session_id=f"index:{repo_id}:edges",
                        session_date=date,
                        embedding=None,
                        project_id=repo_id,
                    )
                    written += 1
                except Exception:
                    pass

        logger.debug("Facts written: %d (repo=%s)", written, repo_id)
        return written

    # ------------------------------------------------------------------
    # Episode sync → OpenSearch / SQLite episodic store
    # ------------------------------------------------------------------

    async def _sync_episodes(
        self,
        repo_id: str,
        nodes: list["ASTNode"],
        desc_by_node: dict[str, Any],
        date: str,
    ) -> int:
        """Write file-level code content as XME episodic episodes.

        One episode per file, containing: all symbols + descriptions + source snippets.
        This enables FTS/vector search over actual code content.
        """
        from collections import defaultdict
        from xce.models import NodeKind

        # Group nodes by filepath
        by_file: dict[str, list[Any]] = defaultdict(list)
        for node in nodes:
            by_file[node.filepath].append(node)

        written = 0
        for filepath, file_nodes in by_file.items():
            # Build a rich text transcript for this file
            parts = [f"FILE: {filepath}", ""]

            for node in sorted(file_nodes, key=lambda n: n.start_line):
                if node.kind not in {NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD}:
                    continue
                desc = desc_by_node.get(node.id)
                summary = ""
                if desc and hasattr(desc, "summary"):
                    summary = desc.summary

                sig = node.signature or f"{node.kind.value} {node.name}"
                doc = node.docstring or summary or ""
                parts.append(f"{sig}")
                if doc:
                    parts.append(f"  # {doc[:150]}")
                parts.append("")

            transcript = "\n".join(parts)
            if len(transcript) < 50:
                continue

            episode_id = f"{repo_id}:file:{filepath.replace('/', '_').replace('.', '_')}"

            try:
                from xme.layers.episodic import Episode, Turn
                import uuid
                ep = Episode(
                    episode_id=str(uuid.uuid5(uuid.NAMESPACE_URL, episode_id)),
                    session_id=f"index:{repo_id}",
                    project_id=repo_id,
                    user_id="xce_agent",
                    summary=f"Code file: {filepath}",
                    outcome="indexed",
                )
                # Store transcript as a single assistant turn — this makes it
                # searchable via FTS since full_transcript is built from turns
                ep.turns.append(Turn(role="assistant", content=transcript))
                await self._episodic.save_episode(ep)
                written += 1
            except Exception as e:
                logger.debug("Failed to write episode for %s: %s", filepath, e)

        logger.debug("Episodes written: %d (repo=%s)", written, repo_id)
        return written

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._episodic is not None:
            try:
                await self._episodic.close()
            except Exception:
                pass
