"""XME MemoryStore — warm (SQLite) storage layer for personal and team memory.

Storage tiers:
  Hot  → XMECache (in-process LRU, xce/memory/cache.py)
  Warm → SQLite at XME_DIR/xme.db  (this file)
  Cold → git-tracked JSON files at XME_DIR/team/ (see sync.py)

SQLite schema (created on first connect):
  personal_sessions   — SessionNode rows
  personal_prefs      — UserPreferenceNode rows
  team_decisions      — DecisionNode rows (local copy, synced from cold store)
  team_attempts       — AttemptNode rows
  team_conventions    — TeamConventionNode rows

All reads go: hot → warm → (cold on demand).
All writes go: warm first, then hot cache is updated (write-through).
Team writes also mark _pending_sync=True; MemorySyncer flushes them to cold.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from xce.memory.cache import XMECache
from xce.memory.models import (
    AttemptNode,
    DecisionNode,
    MemoryScope,
    MemorySearchResult,
    SessionNode,
    TeamConventionNode,
    UserPreferenceNode,
)

logger = logging.getLogger(__name__)

# Default XME directory inside a repo: .xanther/memory/
_DEFAULT_XME_DIR = ".xanther/memory"


class MemoryStore:
    """Unified read/write API for XME — personal + team memory.

    Usage::

        store = MemoryStore.open("/path/to/repo")
        await store.save_session(session)
        results = store.search("how do we handle auth", repo_id="myrepo")
    """

    def __init__(
        self,
        xme_dir: str | Path,
        *,
        cache: Optional[XMECache] = None,
        author: str = "",
    ) -> None:
        self._dir = Path(xme_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "xme.db"
        self._cache = cache or XMECache()
        self._author = author or _get_author()
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, repo_path: str | Path, *, cache: Optional[XMECache] = None) -> "MemoryStore":
        """Open (or create) a MemoryStore rooted at *repo_path*."""
        xme_dir = Path(repo_path) / _DEFAULT_XME_DIR
        store = cls(xme_dir, cache=cache)
        store.connect()
        return store

    def connect(self) -> None:
        """Open SQLite connection and initialise schema."""
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        logger.debug("XME SQLite opened at %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "MemoryStore":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS personal_sessions (
            id          TEXT PRIMARY KEY,
            repo_id     TEXT NOT NULL DEFAULT '',
            author      TEXT NOT NULL DEFAULT '',
            data        TEXT NOT NULL,           -- JSON blob
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ps_repo   ON personal_sessions(repo_id);
        CREATE INDEX IF NOT EXISTS idx_ps_author ON personal_sessions(author);

        CREATE TABLE IF NOT EXISTS personal_prefs (
            id              TEXT PRIMARY KEY,
            repo_id         TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            preference_type TEXT NOT NULL DEFAULT '',
            key             TEXT NOT NULL DEFAULT '',
            value           TEXT NOT NULL DEFAULT '',
            data            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pp_unique
            ON personal_prefs(author, repo_id, key);

        CREATE TABLE IF NOT EXISTS team_decisions (
            id              TEXT PRIMARY KEY,
            repo_id         TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            title           TEXT NOT NULL DEFAULT '',
            outcome         TEXT NOT NULL DEFAULT 'pending',
            pending_sync    INTEGER NOT NULL DEFAULT 1,
            data            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_td_repo   ON team_decisions(repo_id);
        CREATE INDEX IF NOT EXISTS idx_td_outcome ON team_decisions(outcome);

        CREATE TABLE IF NOT EXISTS team_attempts (
            id              TEXT PRIMARY KEY,
            repo_id         TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            result          TEXT NOT NULL DEFAULT 'unknown',
            pending_sync    INTEGER NOT NULL DEFAULT 1,
            data            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ta_repo   ON team_attempts(repo_id);
        CREATE INDEX IF NOT EXISTS idx_ta_result ON team_attempts(result);

        CREATE TABLE IF NOT EXISTS team_conventions (
            id              TEXT PRIMARY KEY,
            repo_id         TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            convention_type TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'active',
            pending_sync    INTEGER NOT NULL DEFAULT 1,
            data            TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tc_repo   ON team_conventions(repo_id);
        CREATE INDEX IF NOT EXISTS idx_tc_status ON team_conventions(status);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Sessions (personal)
    # ------------------------------------------------------------------

    def save_session(self, session: SessionNode) -> None:
        """Upsert a session into warm storage and hot cache."""
        if not session.author:
            session.author = self._author
        d = session.to_dict()
        self._upsert("personal_sessions", session.id, session.repo_id, session.author, d)
        self._cache.set(XMECache.session_key(session.id), d)

    def get_session(self, session_id: str) -> Optional[SessionNode]:
        cached = self._cache.get(XMECache.session_key(session_id))
        if cached:
            return SessionNode.from_dict(cached)
        row = self._fetch_one("personal_sessions", session_id)
        if row:
            node = SessionNode.from_dict(json.loads(row["data"]))
            self._cache.set(XMECache.session_key(session_id), node.to_dict())
            return node
        return None

    def list_sessions(
        self, repo_id: str = "", author: str = "", limit: int = 20
    ) -> list[SessionNode]:
        rows = self._list_rows("personal_sessions", repo_id=repo_id, author=author, limit=limit)
        return [SessionNode.from_dict(json.loads(r["data"])) for r in rows]

    # ------------------------------------------------------------------
    # Preferences (personal)
    # ------------------------------------------------------------------

    def save_preference(self, pref: UserPreferenceNode) -> None:
        if not pref.author:
            pref.author = self._author
        d = pref.to_dict()
        assert self._conn is not None
        self._conn.execute("""
            INSERT INTO personal_prefs
                (id, repo_id, author, preference_type, key, value, data, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(author, repo_id, key) DO UPDATE SET
                value=excluded.value, data=excluded.data, updated_at=excluded.updated_at
        """, (pref.id, pref.repo_id, pref.author, pref.preference_type,
              pref.key, pref.value, json.dumps(d), pref.created_at, pref.updated_at))
        self._conn.commit()
        self._cache.set(XMECache.preference_key(pref.author, pref.key), d)

    def get_preferences(self, author: str = "", repo_id: str = "") -> list[UserPreferenceNode]:
        author = author or self._author
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT data FROM personal_prefs WHERE author=? AND (repo_id=? OR repo_id='')"
            " ORDER BY updated_at DESC",
            (author, repo_id),
        )
        return [UserPreferenceNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Decisions (team)
    # ------------------------------------------------------------------

    def save_decision(self, decision: DecisionNode) -> None:
        if not decision.author:
            decision.author = self._author
        d = decision.to_dict()
        self._upsert("team_decisions", decision.id, decision.repo_id, decision.author, d,
                     extra={"title": decision.title, "outcome": decision.outcome,
                             "pending_sync": 1})
        self._cache.set(XMECache.decision_key(decision.id), d)

    def get_decision(self, decision_id: str) -> Optional[DecisionNode]:
        cached = self._cache.get(XMECache.decision_key(decision_id))
        if cached:
            return DecisionNode.from_dict(cached)
        row = self._fetch_one("team_decisions", decision_id)
        if row:
            node = DecisionNode.from_dict(json.loads(row["data"]))
            self._cache.set(XMECache.decision_key(decision_id), node.to_dict())
            return node
        return None

    def list_decisions(
        self, repo_id: str = "", limit: int = 50, include_reverted: bool = False
    ) -> list[DecisionNode]:
        assert self._conn is not None
        query = "SELECT data FROM team_decisions WHERE repo_id=?"
        params: list[Any] = [repo_id]
        if not include_reverted:
            query += " AND outcome != 'reverted'"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(query, params)
        return [DecisionNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    def list_decisions_for_module(
        self, module_path: str, repo_id: str = ""
    ) -> list[DecisionNode]:
        """Return decisions that mention *module_path* in affected_modules."""
        decisions = self.list_decisions(repo_id=repo_id, limit=200)
        return [d for d in decisions if module_path in (d.affected_modules or [])]

    # ------------------------------------------------------------------
    # Attempts (team)
    # ------------------------------------------------------------------

    def save_attempt(self, attempt: AttemptNode) -> None:
        if not attempt.author:
            attempt.author = self._author
        d = attempt.to_dict()
        self._upsert("team_attempts", attempt.id, attempt.repo_id, attempt.author, d,
                     extra={"result": attempt.result, "pending_sync": 1})
        self._cache.set(XMECache.attempt_key(attempt.id), d)

    def get_attempt(self, attempt_id: str) -> Optional[AttemptNode]:
        cached = self._cache.get(XMECache.attempt_key(attempt_id))
        if cached:
            return AttemptNode.from_dict(cached)
        row = self._fetch_one("team_attempts", attempt_id)
        if row:
            node = AttemptNode.from_dict(json.loads(row["data"]))
            self._cache.set(XMECache.attempt_key(attempt_id), node.to_dict())
            return node
        return None

    def list_attempts(
        self, repo_id: str = "", result_filter: Optional[str] = None, limit: int = 50
    ) -> list[AttemptNode]:
        assert self._conn is not None
        query = "SELECT data FROM team_attempts WHERE repo_id=?"
        params: list[Any] = [repo_id]
        if result_filter:
            query += " AND result=?"
            params.append(result_filter)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(query, params)
        return [AttemptNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Conventions (team)
    # ------------------------------------------------------------------

    def save_convention(self, convention: TeamConventionNode) -> None:
        if not convention.author:
            convention.author = self._author
        d = convention.to_dict()
        self._upsert("team_conventions", convention.id, convention.repo_id, convention.author, d,
                     extra={"convention_type": convention.convention_type,
                             "status": convention.status, "pending_sync": 1})
        self._cache.set(XMECache.convention_key(convention.id), d)

    def list_conventions(
        self, repo_id: str = "", active_only: bool = True
    ) -> list[TeamConventionNode]:
        assert self._conn is not None
        query = "SELECT data FROM team_conventions WHERE repo_id=?"
        params: list[Any] = [repo_id]
        if active_only:
            query += " AND status='active'"
        query += " ORDER BY updated_at DESC"
        cur = self._conn.execute(query, params)
        return [TeamConventionNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Unified search (keyword across all tables)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        repo_id: str = "",
        scope: Optional[MemoryScope] = None,
        limit: int = 20,
    ) -> list[MemorySearchResult]:
        """Simple keyword search across all memory nodes.

        Searches the JSON data blobs for *query* tokens (case-insensitive).
        Returns results sorted by recency.
        For semantic search, use MemoryStore.semantic_search() after building
        an embedding index (Phase 2 feature).
        """
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        if not terms:
            return []

        results: list[MemorySearchResult] = []

        tables_and_types = [
            ("personal_sessions", "session", MemoryScope.PERSONAL),
            ("personal_prefs", "preference", MemoryScope.PERSONAL),
            ("team_decisions", "decision", MemoryScope.TEAM),
            ("team_attempts", "attempt", MemoryScope.TEAM),
            ("team_conventions", "convention", MemoryScope.TEAM),
        ]

        for table, node_type, node_scope in tables_and_types:
            if scope is not None and scope != node_scope:
                continue
            rows = self._search_table(table, repo_id, terms, limit)
            for row in rows:
                d = json.loads(row["data"])
                score = self._keyword_score(d, terms)
                summary = self._extract_summary(node_type, d)
                results.append(MemorySearchResult(
                    node_type=node_type,
                    node_id=d.get("id", ""),
                    score=score,
                    scope=node_scope,
                    summary=summary,
                    data=d,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Hot-cache warm load (called after sync or startup)
    # ------------------------------------------------------------------

    def warm_hot_cache(self, repo_id: str = "", limit: int = 50) -> None:
        """Load recent team decisions + personal prefs into hot cache."""
        for d in self.list_decisions(repo_id=repo_id, limit=limit):
            self._cache.set(XMECache.decision_key(d.id), d.to_dict())
        for a in self.list_attempts(repo_id=repo_id, limit=limit):
            self._cache.set(XMECache.attempt_key(a.id), a.to_dict())
        for p in self.get_preferences(repo_id=repo_id):
            self._cache.set(XMECache.preference_key(p.author, p.key), p.to_dict())
        logger.debug("XME hot cache warmed for repo=%s", repo_id)

    # ------------------------------------------------------------------
    # Pending sync queries (used by MemorySyncer)
    # ------------------------------------------------------------------

    def get_pending_decisions(self) -> list[DecisionNode]:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT data FROM team_decisions WHERE pending_sync=1"
        )
        return [DecisionNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    def get_pending_attempts(self) -> list[AttemptNode]:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT data FROM team_attempts WHERE pending_sync=1"
        )
        return [AttemptNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    def get_pending_conventions(self) -> list[TeamConventionNode]:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT data FROM team_conventions WHERE pending_sync=1"
        )
        return [TeamConventionNode.from_dict(json.loads(r["data"])) for r in cur.fetchall()]

    def mark_synced(self, table: str, node_ids: list[str]) -> None:
        """Clear pending_sync flag after successful git push."""
        if not node_ids:
            return
        assert self._conn is not None
        placeholders = ",".join("?" * len(node_ids))
        self._conn.execute(
            f"UPDATE {table} SET pending_sync=0 WHERE id IN ({placeholders})",
            node_ids,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        assert self._conn is not None
        counts: dict[str, Any] = {}
        for table in ("personal_sessions", "personal_prefs", "team_decisions",
                       "team_attempts", "team_conventions"):
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = row["n"] if row else 0
        counts["cache"] = self._cache.stats()
        return counts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert(
        self,
        table: str,
        node_id: str,
        repo_id: str,
        author: str,
        data: dict[str, Any],
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        assert self._conn is not None
        extra = extra or {}
        cols = ["id", "repo_id", "author", "data", "created_at", "updated_at"]
        vals: list[Any] = [
            node_id, repo_id, author,
            json.dumps(data),
            data.get("created_at", ""),
            data.get("updated_at", ""),
        ]
        for k, v in extra.items():
            cols.append(k)
            vals.append(v)
        placeholders = ",".join("?" * len(cols))
        col_names = ",".join(cols)
        update_set = ", ".join(
            f"{c}=excluded.{c}" for c in cols if c != "id"
        )
        self._conn.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
            f" ON CONFLICT(id) DO UPDATE SET {update_set}",
            vals,
        )
        self._conn.commit()

    def _fetch_one(self, table: str, node_id: str) -> Optional[sqlite3.Row]:
        assert self._conn is not None
        cur = self._conn.execute(
            f"SELECT * FROM {table} WHERE id=?", (node_id,)
        )
        return cur.fetchone()

    def _list_rows(
        self,
        table: str,
        repo_id: str = "",
        author: str = "",
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        assert self._conn is not None
        query = f"SELECT * FROM {table} WHERE 1=1"
        params: list[Any] = []
        if repo_id:
            query += " AND repo_id=?"
            params.append(repo_id)
        if author:
            query += " AND author=?"
            params.append(author)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return self._conn.execute(query, params).fetchall()

    def _search_table(
        self,
        table: str,
        repo_id: str,
        terms: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        assert self._conn is not None
        # Build WHERE clause: data LIKE '%term%' AND ...
        like_clauses = " AND ".join(["LOWER(data) LIKE ?" for _ in terms])
        params: list[Any] = [f"%{t}%" for t in terms]
        query = f"SELECT data, updated_at FROM {table}"
        if repo_id:
            query += " WHERE repo_id=?"
            params = [repo_id] + params
            if like_clauses:
                query += f" AND {like_clauses}"
        elif like_clauses:
            query += f" WHERE {like_clauses}"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return self._conn.execute(query, params).fetchall()

    @staticmethod
    def _keyword_score(data: dict[str, Any], terms: list[str]) -> float:
        """Simple term frequency score over the JSON text."""
        text = json.dumps(data).lower()
        hits = sum(text.count(t) for t in terms)
        return min(1.0, hits / max(len(terms), 1) * 0.2)

    @staticmethod
    def _extract_summary(node_type: str, data: dict[str, Any]) -> str:
        if node_type == "session":
            return data.get("summary") or data.get("problem_statement", "")[:120]
        if node_type == "decision":
            return data.get("title", "")
        if node_type == "attempt":
            return (data.get("problem") or "")[:80] + " → " + data.get("result", "")
        if node_type == "preference":
            return f"{data.get('key', '')} = {data.get('value', '')}"
        if node_type == "convention":
            return data.get("title", "")
        return ""


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _get_author() -> str:
    """Best-effort: git user.name → $USER → 'unknown'."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.name"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER", "unknown")
