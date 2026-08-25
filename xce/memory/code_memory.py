"""Coding Agent Memory Interface — XCE + XME unified query layer.

This is the primary interface for coding agents to query combined code
knowledge (XCE graph facts) and session memory (XME episodic store).

Example:
    from xce.memory.code_memory import CodeMemory

    mem = CodeMemory(neo4j_driver=driver, xme_db_path=".xanther/xme.db")
    await mem.init()

    # Ask a natural language question about the codebase
    ctx = await mem.query("How does the auth service handle JWT tokens?", repo_id="my-repo")
    # Returns structured context ready to inject into an LLM prompt

    # Record what the agent just did (episodic memory)
    await mem.record_action(
        repo_id="my-repo",
        action="modified auth.py: added JWT expiry validation",
        files=["xce/auth.py"],
        outcome="success",
    )

    # Look up past attempts on similar problems
    past = await mem.recall_similar("JWT token expiry", repo_id="my-repo")
"""
from __future__ import annotations

import logging
import sys
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# XME path injection
_XME_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "xanther-memory-engine")


def _ensure_xme() -> bool:
    """Add XME to path if available. Returns True if XME is importable."""
    if os.path.isdir(_XME_PATH) and _XME_PATH not in sys.path:
        sys.path.insert(0, _XME_PATH)
    try:
        import xme  # noqa: F401
        return True
    except ImportError:
        return False


class CodeMemory:
    """Unified XCE + XME memory for coding agents.

    Provides three query modes:
    - symbol_search: find code symbols by name/description (XCE graph)
    - context_query: hybrid search combining code facts + session episodes
    - recall_similar: find past agent actions on similar code problems

    And two write modes:
    - record_action: save what the agent just did as an episodic entry
    - record_decision: save an architectural decision to XME facts
    """

    def __init__(
        self,
        neo4j_driver: Any,
        xme_db_path: str = ".xanther/xme.db",
        opensearch_url: Optional[str] = None,
        embedder: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
    ) -> None:
        self._driver = neo4j_driver
        self._xme_db_path = xme_db_path
        self._opensearch_url = opensearch_url
        self._embedder = embedder
        self._embedding_service = embedding_service  # EmbeddingService for episode embeddings
        self._has_xme = _ensure_xme()
        self._tfg: Optional[Any] = None
        self._episodic: Optional[Any] = None
        self._ready = False

    async def init(self) -> None:
        """Initialise XME layers. Call once before querying."""
        if not self._has_xme:
            logger.warning("XME not found — code facts only (no episodic memory)")
            self._ready = True
            return

        try:
            from xme.layers.temporal_graph import TemporalFactGraph
            self._tfg = TemporalFactGraph(self._driver)
            await self._tfg.init_schema()
        except Exception as e:
            logger.warning("TemporalFactGraph init failed: %s", e)

        try:
            from xme.layers.episodic import EpisodicStore
            self._episodic = EpisodicStore(
                opensearch_url=self._opensearch_url or "http://localhost:9200",
                sqlite_path=self._xme_db_path,
                opensearch_enabled=bool(self._opensearch_url),
                embedding_dims=384,
            )
            # EpisodicStore uses synchronous connect()
            self._episodic.connect()
            logger.info("XME EpisodicStore initialised (opensearch=%s)", bool(self._opensearch_url))
        except Exception as e:
            logger.warning("EpisodicStore init failed: %s", e)

        # Initialize Neo4j vector index for episode embeddings
        await self._init_episode_vector_index()

        self._ready = True
        logger.info("CodeMemory ready (xme=%s, episodic=%s)", bool(self._tfg), bool(self._episodic))

    async def _init_episode_vector_index(self) -> None:
        """Create Neo4j vector index for episode embeddings (512-dim)."""
        try:
            async with self._driver.session() as session:
                await session.run(
                    "CREATE VECTOR INDEX episode_embedding_idx IF NOT EXISTS "
                    "FOR (e:EpisodeEmbedding) ON (e.vector) "
                    "OPTIONS {indexConfig: {`vector.dimensions`: 512, "
                    "`vector.similarity_function`: 'cosine'}}"
                )
                # Uniqueness constraint for episode nodes
                await session.run(
                    "CREATE CONSTRAINT episode_emb_id IF NOT EXISTS "
                    "FOR (e:EpisodeEmbedding) REQUIRE e.episode_id IS UNIQUE"
                )
            logger.info("Episode vector index ready (512-dim, cosine)")
        except Exception as e:
            logger.warning("Episode vector index creation failed: %s", e)

    # ------------------------------------------------------------------
    # Primary query interface
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        repo_id: str,
        top_k: int = 15,
        user_id: str = "xce_agent",
    ) -> dict[str, Any]:
        """Hybrid query: XCE code facts + XME episodic sessions.

        Returns a dict with:
          - facts: list of relevant code symbols/descriptions
          - episodes: list of relevant past sessions / file contents
          - context_str: pre-formatted string ready for LLM injection
        """
        assert self._ready, "Call await mem.init() first"

        facts = await self._query_code_facts(question, repo_id, top_k, user_id)
        episodes = await self._query_episodes(question, repo_id, top_k, user_id)
        context_str = self._format_context(question, facts, episodes)

        return {
            "facts": facts,
            "episodes": episodes,
            "context_str": context_str,
            "repo_id": repo_id,
            "query": question,
        }

    async def symbol_search(
        self,
        query: str,
        repo_id: str,
        kinds: Optional[list[str]] = None,
        top_k: int = 10,
        user_id: str = "xce_agent",
    ) -> list[dict[str, Any]]:
        """Search for code symbols by name/description.

        Args:
            query:  Natural language or symbol name
            repo_id: Repository to search
            kinds:  Filter by symbol kind: 'function', 'class', 'method', 'module'
            top_k:  Max results
        """
        assert self._ready
        return await self._query_code_facts(query, repo_id, top_k, user_id, kinds=kinds)

    async def recall_similar(
        self,
        problem: str,
        repo_id: str,
        user_id: str = "xce_agent",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Recall past agent actions and decisions similar to the current problem.

        Useful for: "have I solved this before?", "what changed last time?"
        """
        assert self._ready
        return await self._query_episodes(problem, repo_id, limit, user_id, agent_actions_only=True)

    # ------------------------------------------------------------------
    # Write interface
    # ------------------------------------------------------------------

    async def record_action(
        self,
        repo_id: str,
        action: str,
        files: Optional[list[str]] = None,
        outcome: str = "success",
        user_id: str = "xce_agent",
    ) -> Optional[str]:
        """Record what the coding agent just did as an episodic memory entry.

        Args:
            repo_id:  Repository being worked on
            action:   Description of what was done (e.g. "fixed null check in auth.py")
            files:    Files modified (optional)
            outcome:  "success", "failed", or "partial"
            user_id:  Agent identifier
        Returns:
            episode_id if stored, None if episodic store unavailable
        """
        if self._episodic is None:
            return None

        try:
            from xme.layers.episodic import Episode, Turn
            import uuid
            ts = datetime.now(timezone.utc).isoformat()
            files_str = ", ".join(files or [])
            transcript = f"Agent: {action}\nFiles: {files_str or 'none'}\nOutcome: {outcome}"
            ep = Episode(
                episode_id=str(uuid.uuid4()),
                session_id=f"agent:{repo_id}:{ts[:10]}",
                project_id=repo_id,
                user_id=user_id,
                summary=action[:200],
                outcome=outcome,
            )
            ep.turns.append(Turn(role="assistant", content=transcript))
            await self._episodic.save_episode(ep)
            logger.debug("Recorded agent action: %s", action[:60])

            # Store embedding in Neo4j for vector search
            await self._store_episode_embedding(
                episode_id=ep.episode_id,
                text=action,
                repo_id=repo_id,
                summary=action[:200],
                files=files,
                outcome=outcome,
            )

            return ep.episode_id
        except Exception as e:
            logger.warning("Failed to record action: %s", e)
            return None

    async def _store_episode_embedding(
        self,
        episode_id: str,
        text: str,
        repo_id: str,
        summary: str = "",
        files: Optional[list[str]] = None,
        outcome: str = "success",
    ) -> None:
        """Embed episode text and store as EpisodeEmbedding node in Neo4j."""
        if self._embedding_service is None:
            return

        try:
            vector = await self._embedding_service.encode(text)
            files_str = ",".join(files or [])
            ts = datetime.now(timezone.utc).isoformat()

            async with self._driver.session() as session:
                await session.run(
                    "MERGE (e:EpisodeEmbedding {episode_id: $eid}) "
                    "SET e.vector = $vector, "
                    "    e.repo_id = $repo_id, "
                    "    e.summary = $summary, "
                    "    e.files = $files, "
                    "    e.outcome = $outcome, "
                    "    e.created_at = $ts",
                    {
                        "eid": episode_id,
                        "vector": vector,
                        "repo_id": repo_id,
                        "summary": summary[:500],
                        "files": files_str,
                        "outcome": outcome,
                        "ts": ts,
                    },
                )
            logger.debug("Stored episode embedding: %s", episode_id[:8])
        except Exception as e:
            logger.warning("Failed to store episode embedding: %s", e)

    async def record_decision(
        self,
        repo_id: str,
        decision: str,
        rationale: str = "",
        affected_files: Optional[list[str]] = None,
        user_id: str = "xce_agent",
    ) -> None:
        """Record an architectural decision as an XME fact.

        These persist permanently and surface in future queries about
        why the codebase is structured a certain way.
        """
        if self._tfg is None:
            return
        try:
            ts = datetime.now(timezone.utc).isoformat()
            value = decision if not rationale else f"{decision} — {rationale}"
            await self._tfg.upsert_fact(
                user_id=user_id,
                attribute="architectural_decision",
                value=value[:400],
                fact_type="code_decision",
                session_id=f"agent:{repo_id}:{ts[:10]}",
                session_date=ts,
                embedding=None,
                project_id=repo_id,
            )
        except Exception as e:
            logger.warning("Failed to record decision: %s", e)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _query_code_facts(
        self,
        query: str,
        repo_id: str,
        top_k: int,
        user_id: str,
        kinds: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Query XME PersonalFact nodes for code symbols/descriptions."""
        if self._tfg is None:
            return await self._neo4j_symbol_search(query, repo_id, top_k, kinds)

        # Embed query if embedder available
        emb = None
        if self._embedder is not None:
            try:
                emb = self._embedder.embed(query)
            except Exception:
                pass

        try:
            # Search fact types: code_symbol, code_description, code_decision
            facts = await self._tfg.search_facts(
                query, user_id, repo_id, embedding=emb, top_k=top_k
            )
            # Filter by kind if requested
            if kinds:
                facts = [f for f in facts if any(
                    k in f.get("attr", "") for k in kinds
                )]
            return facts
        except Exception as e:
            logger.debug("Fact search failed, falling back to Neo4j: %s", e)
            return await self._neo4j_symbol_search(query, repo_id, top_k, kinds)

    async def _neo4j_symbol_search(
        self,
        query: str,
        repo_id: str,
        top_k: int,
        kinds: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Direct Neo4j keyword search over ASTNodes (XCE native)."""
        try:
            words = [w for w in query.lower().split() if len(w) > 3][:5]
            if not words:
                return []
            where = " OR ".join(
                f"toLower(n.name) CONTAINS '{w}' OR toLower(n.docstring) CONTAINS '{w}'"
                for w in words
            )
            kinds_filter = ""
            if kinds:
                kind_list = ", ".join(f"'{k}'" for k in kinds)
                kinds_filter = f" AND n.kind IN [{kind_list}]"
            async with self._driver.session() as s:
                r = await s.run(
                    f"MATCH (n:ASTNode) WHERE n.repo_id = $rid AND ({where}){kinds_filter} "
                    "RETURN n.name AS attr, coalesce(n.docstring, n.signature, n.kind) AS val, "
                    "n.kind AS ftype, n.filepath AS sdate, 1.0 AS score "
                    "LIMIT $k",
                    {"rid": repo_id, "k": top_k},
                )
                return [dict(rec) async for rec in r]
        except Exception as e:
            logger.debug("Neo4j symbol search failed: %s", e)
            return []

    async def _query_episodes(
        self,
        query: str,
        repo_id: str,
        top_k: int,
        user_id: str,
        agent_actions_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search XME episodic store for relevant code sessions/files.
        
        Uses Neo4j vector search when embedding_service is available (semantic),
        falls back to SQLite FTS5 (keyword) otherwise.
        """
        # Try vector search first (more accurate, no false positives)
        if self._embedding_service is not None:
            vector_results = await self._vector_episode_search(query, repo_id, top_k)
            if vector_results:
                return vector_results

        # Fallback to FTS5-based search
        if self._episodic is None:
            return []
        try:
            from xme.layers.episodic import MemorySearchResult
            results = await self._episodic.search(
                query=query,
                project_id=repo_id,
                user_id=user_id,
                limit=top_k,
            )
            out = []
            for r in results:
                meta = r.data.get("metadata", {})
                if agent_actions_only and meta.get("source") != "agent_action":
                    continue
                out.append({
                    "episode_id": r.item_id,
                    "summary": r.summary,
                    "score": r.score,
                    "source": meta.get("source", ""),
                    "filepath": meta.get("filepath", ""),
                    "outcome": meta.get("outcome", ""),
                    "snippet": r.data.get("full_transcript", "")[:400],
                })
            return out
        except Exception as e:
            logger.debug("Episode search failed: %s", e)
            return []

    async def _vector_episode_search(
        self,
        query: str,
        repo_id: str,
        top_k: int,
        min_score: float = 0.75,
    ) -> list[dict[str, Any]]:
        """Semantic vector search over episode embeddings in Neo4j.
        
        Returns episodes ranked by cosine similarity with minimum score threshold.
        This eliminates the false positive problem of FTS5 keyword matching.
        """
        try:
            query_vector = await self._embedding_service.encode(query)

            cypher = (
                "CALL db.index.vector.queryNodes('episode_embedding_idx', $top_k, $embedding) "
                "YIELD node AS emb, score "
                "WHERE emb.repo_id = $repo_id AND score >= $min_score "
                "RETURN emb.episode_id AS episode_id, "
                "       emb.summary AS summary, "
                "       score, "
                "       emb.files AS files, "
                "       emb.outcome AS outcome, "
                "       emb.created_at AS created_at "
                "ORDER BY score DESC "
                "LIMIT $limit"
            )

            async with self._driver.session() as session:
                result = await session.run(cypher, {
                    "top_k": top_k * 2,  # fetch extra, filter by score
                    "embedding": query_vector,
                    "repo_id": repo_id,
                    "min_score": min_score,
                    "limit": top_k,
                })
                records = [dict(r) async for r in result]

            return [
                {
                    "episode_id": r["episode_id"],
                    "summary": r["summary"] or "",
                    "score": r["score"],
                    "source": "vector_search",
                    "filepath": r.get("files", ""),
                    "outcome": r.get("outcome", ""),
                    "snippet": r["summary"] or "",
                }
                for r in records
            ]
        except Exception as e:
            logger.debug("Vector episode search failed (falling back to FTS5): %s", e)
            return []

    def _format_context(
        self,
        query: str,
        facts: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
        max_chars: int = 12000,
    ) -> str:
        """Format retrieved facts + episodes into an LLM-ready context string."""
        parts = [f"CODEBASE CONTEXT FOR: {query}\n"]

        if facts:
            parts.append("CODE SYMBOLS AND FACTS:")
            for f in facts[:20]:
                attr = f.get("attr") or f.get("name", "")
                val = f.get("val") or f.get("value", "")
                loc = f.get("sdate") or f.get("filepath", "")
                loc_str = f" [{loc}]" if loc else ""
                parts.append(f"  - {attr}: {str(val)[:200]}{loc_str}")
            parts.append("")

        if episodes:
            parts.append("RELEVANT CODE FILES / PAST ACTIONS:")
            for ep in episodes[:8]:
                src = ep.get("source", "")
                fp = ep.get("filepath", "")
                summary = ep.get("summary", "")
                snippet = ep.get("snippet", "")
                label = fp or summary or ep.get("episode_id", "")
                parts.append(f"\n--- {label} ({src}) ---")
                if snippet:
                    parts.append(snippet[:600])

        result = "\n".join(parts)
        return result[:max_chars]

    async def close(self) -> None:
        if self._episodic:
            try:
                await self._episodic.close()
            except Exception:
                pass
