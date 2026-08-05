"""XME Session Lifecycle Manager.

This is the piece that answers: "who calls what, and when?"

The three-stage lifecycle for every agent session:

  SESSION START
    └── SessionContext.start()
          ├── open MemoryStore (SQLite warm)
          ├── load MEMORY.md → inject into agent context
          ├── load yesterday+today logs → inject recent context
          ├── warm hot cache from recent decisions/attempts
          └── emit context_snapshot (ready to inject into steering/prompt)

  DURING SESSION  (per turn, non-blocking)
    └── SessionContext.record_turn(role, content)
          ├── buffer append → daily MD log (async fire-and-forget)
          ├── every FLUSH_EVERY turns: flush buffer to disk
          └── every COMPACT_CHECK_EVERY turns: check threshold → maybe compact()

  SESSION END
    └── SessionContext.end(summary, outcome, files_touched)
          ├── flush remaining buffer
          ├── force compact() → extract all structured nodes
          ├── save SessionNode to warm store
          ├── warm hot cache
          └── [if sync_enabled] fire-and-forget git push

The SessionContext is the single entry point for the MCP server middleware.
It lives for exactly one agent session (one MCP server connection / one chat).

Integration with MCP server:
  XCEMCPServer wraps handle_tool_call() with auto-journal middleware.
  Every XCE tool call gets recorded as a tool turn automatically.
  No agent cooperation required.

Integration with steering:
  SessionContext.get_context_for_prompt() returns a compact markdown block
  ready to inject into agent system prompts / steering files.
  This gives the agent its memory at session start with zero extra tool calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
_FLUSH_EVERY = int(os.environ.get("XME_FLUSH_EVERY_TURNS", "5"))
_COMPACT_CHECK_EVERY = int(os.environ.get("XME_COMPACT_CHECK_EVERY_TURNS", "20"))
_MAX_CONTEXT_DECISIONS = int(os.environ.get("XME_CONTEXT_MAX_DECISIONS", "5"))
_MAX_CONTEXT_FAILURES = int(os.environ.get("XME_CONTEXT_MAX_FAILURES", "3"))
_MAX_RECENT_LOG_LINES = int(os.environ.get("XME_CONTEXT_MAX_LOG_LINES", "40"))
_DEFAULT_XME_DIR = ".xanther/memory"


@dataclass
class ContextSnapshot:
    """Ready-to-inject memory context for an agent session start."""
    permanent_memory: str       # MEMORY.md content (or truncated version)
    recent_log: str             # Last N lines of today's log
    top_decisions: list[dict[str, Any]]   # Most recent team decisions
    top_failures: list[dict[str, Any]]    # Most recent failed attempts
    preferences: list[dict[str, Any]]    # User preferences
    formatted_block: str        # Single markdown block for prompt injection


class SessionContext:
    """Manages the full XME lifecycle for a single agent session.

    Usage (inside MCP server)::

        ctx = await SessionContext.start(repo_path="/path/to/repo", repo_id="myrepo")
        prompt_block = ctx.get_context_for_prompt()
        # → inject into agent's system prompt / steering

        # Per turn (called by MCP middleware):
        ctx.record_turn("user", "How does auth work?")
        ctx.record_turn("assistant", "Auth uses JWT...")
        ctx.record_tool("xce_search", {"query": "auth"}, "Found 3 results")

        # Session end:
        await ctx.end(summary="Refactored auth", outcome="success",
                      files_touched=["xce/auth.py"])
    """

    def __init__(
        self,
        repo_path: str,
        repo_id: str,
        memory_dir: Optional[str] = None,
        author: str = "",
        session_id: str = "",
        sync_enabled: bool = False,
    ) -> None:
        self._repo_path = repo_path
        self._repo_id = repo_id
        self._author = author or _get_author()
        self._session_id = session_id or _new_id()
        self._sync_enabled = sync_enabled
        self._turn_count = 0

        # Determine memory dir
        if memory_dir:
            self._memory_dir = Path(memory_dir)
        else:
            self._memory_dir = Path(repo_path) / _DEFAULT_XME_DIR
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-initialized components
        self._store: Any = None
        self._journal: Any = None
        self._snapshot: Optional[ContextSnapshot] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def start(
        cls,
        repo_path: str,
        repo_id: str = "",
        memory_dir: Optional[str] = None,
        author: str = "",
        sync_enabled: bool = False,
    ) -> "SessionContext":
        """Open store, journal, warm caches, build context snapshot."""
        import uuid
        ctx = cls(
            repo_path=repo_path,
            repo_id=repo_id or Path(repo_path).name,
            memory_dir=memory_dir,
            author=author,
            session_id=str(uuid.uuid4()),
            sync_enabled=sync_enabled,
        )
        await ctx._initialize()
        return ctx

    async def _initialize(self) -> None:
        from xce.memory.store import MemoryStore
        from xce.memory.journal import ChatJournal

        # Open warm store
        self._store = MemoryStore.open(self._repo_path)

        # Open journal
        self._journal = ChatJournal(
            memory_dir=str(self._memory_dir),
            repo_id=self._repo_id,
            author=self._author,
            session_id=self._session_id,
        )

        # Warm hot cache from recent decisions/attempts
        self._store.warm_hot_cache(repo_id=self._repo_id, limit=50)

        # Build context snapshot for prompt injection
        self._snapshot = await self._build_snapshot()

        # Mark session start in journal
        self._journal.note(
            f"SESSION START | id={self._session_id} | author={self._author}",
            tag="session",
        )
        self._journal.flush_sync()

        logger.info("XME session started: %s repo=%s", self._session_id, self._repo_id)

    async def end(
        self,
        summary: str = "",
        outcome: str = "unknown",
        files_touched: Optional[list[str]] = None,
        problem_statement: str = "",
    ) -> None:
        """Flush, compact, save session node, optionally push to git."""
        if not self._journal or not self._store:
            return

        # Mark session end in journal
        self._journal.note(
            f"SESSION END | outcome={outcome} | summary={summary[:100]}",
            tag="session",
        )

        # Flush remaining buffer
        self._journal.flush_sync()

        # Force compaction to extract structured nodes
        try:
            result = await self._journal.compact(self._store)
            logger.info(
                "XME session end compaction: %d→%d lines, promoted=%s",
                result.lines_before, result.lines_after, result.promoted,
            )
        except Exception as e:
            logger.warning("XME compaction error: %s", e)

        # Save session recap
        from xce.memory.models import SessionNode
        session = SessionNode()
        session.id = self._session_id
        session.repo_id = self._repo_id
        session.author = self._author
        session.problem_statement = problem_statement
        session.summary = summary
        session.files_touched = files_touched or []
        session.outcome = outcome
        self._store.save_session(session)

        # Refresh hot cache
        self._store.warm_hot_cache(repo_id=self._repo_id)

        # Git push (fire-and-forget, don't block session end)
        if self._sync_enabled:
            asyncio.create_task(self._async_push())

        self._store.close()
        logger.info("XME session ended: %s", self._session_id)

    # ------------------------------------------------------------------
    # Per-turn recording (called by MCP middleware, non-blocking)
    # ------------------------------------------------------------------

    def record_turn(self, role: str, content: str) -> None:
        """Record a chat turn. Non-blocking buffer append."""
        if not self._journal:
            return
        self._journal.append_turn(role, content)
        self._turn_count += 1
        self._maybe_flush_and_check()

    def record_tool(self, tool_name: str, args: dict[str, Any], result_summary: str) -> None:
        """Record a tool invocation. Non-blocking."""
        if not self._journal:
            return
        self._journal.append_tool_call(tool_name, args, result_summary)
        self._turn_count += 1
        self._maybe_flush_and_check()

    def _maybe_flush_and_check(self) -> None:
        """Flush to disk every N turns. Schedule compaction check every M turns."""
        if self._turn_count % _FLUSH_EVERY == 0:
            self._journal.flush_sync()

        if self._turn_count % _COMPACT_CHECK_EVERY == 0:
            # Schedule as a background task — never blocks a turn
            asyncio.create_task(self._background_compact())

    async def _background_compact(self) -> None:
        """Run compaction check in background. Swallows all errors."""
        if not self._journal or not self._store:
            return
        try:
            await self._journal.flush(self._store)  # triggers _maybe_compact
        except Exception as e:
            logger.debug("XME background compact error (suppressed): %s", e)

    # ------------------------------------------------------------------
    # Context snapshot for prompt injection
    # ------------------------------------------------------------------

    async def _build_snapshot(self) -> ContextSnapshot:
        """Build the context block to inject at session start."""
        if not self._store or not self._journal:
            return ContextSnapshot("", "", [], [], [], "")

        # MEMORY.md permanent memory
        permanent = self._journal.read_memory_md()
        # Truncate if huge — just show last 80 lines
        perm_lines = permanent.splitlines()
        if len(perm_lines) > 80:
            permanent = "\n".join(perm_lines[-80:])

        # Recent daily log (today + yesterday)
        today_log = self._journal.read_daily_log()
        log_lines = today_log.splitlines()
        recent_log = "\n".join(log_lines[-_MAX_RECENT_LOG_LINES:])

        # Top decisions (most recent, not reverted)
        decisions = self._store.list_decisions(
            repo_id=self._repo_id,
            limit=_MAX_CONTEXT_DECISIONS,
        )
        top_decisions = [
            {"title": d.title, "decision": d.decision, "outcome": d.outcome}
            for d in decisions
        ]

        # Top failed attempts (most recent)
        failures = self._store.list_attempts(
            repo_id=self._repo_id,
            result_filter="failed",
            limit=_MAX_CONTEXT_FAILURES,
        )
        top_failures = [
            {
                "problem": a.problem[:120],
                "failure_reason": a.failure_reason[:120],
                "lessons_learned": a.lessons_learned[:120],
            }
            for a in failures
        ]

        # User preferences
        prefs = self._store.get_preferences(
            author=self._author, repo_id=self._repo_id
        )
        preferences = [{"key": p.key, "value": p.value} for p in prefs]

        formatted = _format_context_block(
            repo_id=self._repo_id,
            top_decisions=top_decisions,
            top_failures=top_failures,
            preferences=preferences,
            recent_log=recent_log,
        )

        return ContextSnapshot(
            permanent_memory=permanent,
            recent_log=recent_log,
            top_decisions=top_decisions,
            top_failures=top_failures,
            preferences=preferences,
            formatted_block=formatted,
        )

    def get_context_for_prompt(self) -> str:
        """Return the markdown context block for injection into agent prompts.

        Call this at session start to prime the agent with memory.
        Empty string if no memory exists yet.
        """
        if self._snapshot:
            return self._snapshot.formatted_block
        return ""

    @property
    def snapshot(self) -> Optional[ContextSnapshot]:
        return self._snapshot

    @property
    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------
    # Async git push
    # ------------------------------------------------------------------

    async def _async_push(self) -> None:
        from xce.memory.sync import MemorySyncer
        # Open a fresh store for push (main store already closed)
        from xce.memory.store import MemoryStore
        try:
            with MemoryStore.open(self._repo_path) as store:
                syncer = MemorySyncer(
                    memory_dir=str(self._memory_dir),
                    repo_root=self._repo_path,
                )
                syncer.push(store)
                logger.info("XME async push complete for session %s", self._session_id)
        except Exception as e:
            logger.warning("XME async push failed: %s", e)


# ---------------------------------------------------------------------------
# Context block formatter
# ---------------------------------------------------------------------------

def _format_context_block(
    repo_id: str,
    top_decisions: list[dict[str, Any]],
    top_failures: list[dict[str, Any]],
    preferences: list[dict[str, Any]],
    recent_log: str,
) -> str:
    """Render a compact markdown block suitable for system prompt injection."""
    parts: list[str] = [
        f"<!-- XME Memory Context | repo={repo_id} -->\n",
    ]

    if top_decisions:
        parts.append("**Recent Architectural Decisions:**")
        for d in top_decisions:
            status = f"[{d.get('outcome', 'pending').upper()}]"
            parts.append(f"- {status} {d.get('title', '')} — {d.get('decision', '')[:100]}")
        parts.append("")

    if top_failures:
        parts.append("**Known Failed Approaches (don't repeat):**")
        for f in top_failures:
            parts.append(f"- Problem: {f.get('problem', '')[:80]}")
            if f.get("failure_reason"):
                parts.append(f"  Failed because: {f['failure_reason'][:100]}")
            if f.get("lessons_learned"):
                parts.append(f"  Lesson: {f['lessons_learned'][:100]}")
        parts.append("")

    if preferences:
        parts.append("**User Preferences:**")
        for p in preferences:
            parts.append(f"- {p.get('key', '')}: {p.get('value', '')}")
        parts.append("")

    if recent_log.strip():
        parts.append("**Recent Session Activity (last 40 lines):**")
        parts.append("```")
        parts.append(recent_log[-2000:])  # hard cap
        parts.append("```")

    if len(parts) <= 1:
        return ""  # Nothing to inject

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MCP middleware — wraps handle_tool_call with auto-journaling
# ---------------------------------------------------------------------------

class JournalingMiddleware:
    """Wraps XCEMCPServer.handle_tool_call to auto-record every tool call.

    The middleware:
      1. Extracts repo_path from tool arguments (best-effort)
      2. Gets or creates a SessionContext for that repo
      3. Records the tool call and result in the journal
      4. Returns the original result unchanged

    The agent doesn't need to call xme_journal_append explicitly.
    This runs transparently on every XCE tool call.

    Usage::

        server = XCEMCPServer(...)
        middleware = JournalingMiddleware(server)
        # replace server's call handler:
        server._journaling_middleware = middleware
        # now all tool calls go through middleware.handle()
    """

    def __init__(self, server: Any) -> None:
        self._server = server
        # repo_path → SessionContext (one per repo per process lifetime)
        self._sessions: dict[str, SessionContext] = {}

    async def handle(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        """Intercept tool call, journal it, return original result."""
        # Extract repo context from args
        repo_path = (
            arguments.get("repo_path")
            or arguments.get("repo_id")
            or ""
        )

        # Get/create session for this repo
        ctx: Optional[SessionContext] = None
        if repo_path and os.path.isdir(repo_path):
            ctx = await self._get_or_create_session(repo_path)

        # Execute original tool
        result = await self._server.handle_tool_call(name, arguments)

        # Journal the tool call (fire-and-forget, never blocks)
        if ctx and not name.startswith("xme_"):  # don't journal XME meta-calls
            result_text = result[0].text[:200] if result else ""
            ctx.record_tool(
                tool_name=name,
                args={k: str(v)[:80] for k, v in arguments.items()},
                result_summary=result_text,
            )

        return result

    async def _get_or_create_session(self, repo_path: str) -> SessionContext:
        if repo_path not in self._sessions:
            ctx = await SessionContext.start(
                repo_path=repo_path,
                repo_id=Path(repo_path).name,
            )
            self._sessions[repo_path] = ctx
            logger.debug("XME: new session context for %s", repo_path)
        return self._sessions[repo_path]

    async def end_session(
        self,
        repo_path: str,
        summary: str = "",
        outcome: str = "unknown",
        files_touched: Optional[list[str]] = None,
    ) -> None:
        """End the session for a given repo (call on MCP disconnect)."""
        ctx = self._sessions.pop(repo_path, None)
        if ctx:
            await ctx.end(summary=summary, outcome=outcome, files_touched=files_touched)

    async def end_all_sessions(self) -> None:
        """End all active sessions (call on server shutdown)."""
        for repo_path, ctx in list(self._sessions.items()):
            try:
                await ctx.end()
            except Exception as e:
                logger.warning("Error ending session for %s: %s", repo_path, e)
        self._sessions.clear()

    def get_context_for_repo(self, repo_path: str) -> str:
        """Get the memory context block for a repo (for prompt injection)."""
        ctx = self._sessions.get(repo_path)
        return ctx.get_context_for_prompt() if ctx else ""


# ---------------------------------------------------------------------------
# Steering file generator
# ---------------------------------------------------------------------------

def generate_xme_steering(repo_path: str) -> str:
    """Generate a steering file block that injects XME context at session start.

    This is called by `xanther generate` / `xce memory steering` to produce
    a `.kiro/steering/xme.md` (or CLAUDE.md section, cursor.md etc.)

    The steering file:
      1. Tells the agent to call xme_journal_append on each turn
      2. Injects the current memory context inline
      3. Tells the agent to call xme_journal_compact at session end
    """
    from xce.memory.store import MemoryStore
    from xce.memory.journal import ChatJournal

    memory_dir = Path(repo_path) / _DEFAULT_XME_DIR
    if not memory_dir.exists():
        return _STEERING_TEMPLATE_EMPTY

    try:
        store = MemoryStore.open(repo_path)
        journal = ChatJournal(memory_dir=str(memory_dir))
        repo_id = Path(repo_path).name

        decisions = store.list_decisions(repo_id=repo_id, limit=5)
        failures = store.list_attempts(repo_id=repo_id, result_filter="failed", limit=3)
        prefs = store.get_preferences(repo_id=repo_id)

        memory_md_excerpt = journal.read_memory_md()
        lines = memory_md_excerpt.splitlines()
        excerpt = "\n".join(lines[:40]) if lines else ""

        store.close()

        decisions_block = "\n".join(
            f"- [{d.outcome.upper()}] {d.title}: {d.decision[:100]}"
            for d in decisions
        ) or "_(none yet)_"

        failures_block = "\n".join(
            f"- {a.problem[:80]} → failed because: {a.failure_reason[:80]}"
            for a in failures
        ) or "_(none yet)_"

        prefs_block = "\n".join(
            f"- {p.key}: {p.value}" for p in prefs
        ) or "_(none yet)_"

        return _STEERING_TEMPLATE.format(
            repo_id=repo_id,
            decisions_block=decisions_block,
            failures_block=failures_block,
            prefs_block=prefs_block,
            memory_excerpt=excerpt,
        )
    except Exception as e:
        logger.warning("Could not generate XME steering: %s", e)
        return _STEERING_TEMPLATE_EMPTY


_STEERING_TEMPLATE_EMPTY = """\
---
description: XME Memory Engine — no memory recorded yet
---
# Xanther Memory

No memory has been recorded for this repository yet.

To start recording: use the `xme_journal_append` and `xme_remember` MCP tools.
"""

_STEERING_TEMPLATE = """\
---
description: XME Memory Engine — auto-injected context
---
# Xanther Memory Context (repo: {repo_id})

## How to use this memory

At the start of every session:
- This file is loaded automatically — no action needed
- The decisions/failures below are your project's institutional memory
- Use `xme_journal_append` to record turns (or rely on auto-middleware)
- Use `xme_remember` to save important decisions explicitly
- Run `xme_journal_compact` at session end to promote learnings to graph

## Architectural Decisions

{decisions_block}

## Known Failed Approaches (do not repeat)

{failures_block}

## User Preferences

{prefs_block}

## Permanent Memory (MEMORY.md excerpt)

```
{memory_excerpt}
```

## MCP Tools Reference

| Tool | When to use |
|------|------------|
| `xme_journal_append` | After each turn (auto-called by middleware) |
| `xme_remember` | Explicitly save a decision/attempt/preference |
| `xme_decisions` | Query what decisions have been made |
| `xme_attempts` | Find past approaches to a similar problem |
| `xme_history` | See what was done on a file/symbol |
| `xme_journal_compact` | End of session — promotes log → graph |
| `xme_sync` | Share team decisions via git |
"""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _get_author() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["git", "config", "--get", "user.name"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER", "unknown")
