"""XME Chat Journal — OpenClaw-style async markdown logging + graph compaction.

Two tiers of live session writing:
  MEMORY.md          — permanent, structured, survives compaction
                       (decisions, preferences, conventions, key facts)
  memory/YYYY-MM-DD.md — append-only daily ephemeral log
                          (raw turns, tool calls, WIP notes)

Compaction pipeline (runs async, never blocks a turn):
  1. When daily log exceeds COMPACTION_THRESHOLD lines (default 300)
     OR explicitly triggered by caller:
  2. Extract structured memories from raw turns (regex + heuristics, no LLM needed)
  3. Promote to SQLite/graph via MemoryStore:
        - Decisions    → DecisionNode
        - Attempts      → AttemptNode
        - Preferences   → UserPreferenceNode
        - Conventions   → TeamConventionNode
  4. Compact the daily log: keep last COMPACT_KEEP_LINES lines verbatim,
     replace older content with a one-line "compacted YYYY-MM-DD HH:MM" marker
  5. Update MEMORY.md with any new permanent entries

This gives us OpenClaw's human-readable durability PLUS XCE's structured graph —
something neither OpenClaw nor Graphify has.

Key design choices:
  - Writes are non-blocking (asyncio.create_task) — never slow a chat turn
  - All files are plain Markdown — inspectable, git-diff-able, editable by humans
  - MEMORY.md uses sections with stable headers so idempotent appends work
  - Compaction is purely additive to the graph (never deletes structured nodes)
  - No LLM required for compaction — regex heuristics with fallback to raw capture
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from xce.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
COMPACTION_THRESHOLD_LINES = int(os.environ.get("XME_COMPACTION_THRESHOLD", "300"))
COMPACT_KEEP_LINES = int(os.environ.get("XME_COMPACT_KEEP_LINES", "60"))

# Section headers in MEMORY.md
_SECTION_DECISIONS = "## Decisions"
_SECTION_PREFERENCES = "## Preferences"
_SECTION_CONVENTIONS = "## Conventions"
_SECTION_FAILED = "## Failed Approaches"
_MEMORY_SECTIONS = [_SECTION_DECISIONS, _SECTION_PREFERENCES,
                    _SECTION_CONVENTIONS, _SECTION_FAILED]

# Regex patterns for extracting structured memory from raw chat turns
_DECISION_PATTERNS = [
    re.compile(r"(?:decided|decision|we decided|we'll use|using|chose)\s*[:\-]?\s*(.{10,200})", re.I),
    re.compile(r"ADR[:\s]+(.{10,200})", re.I),
]
_FAILED_PATTERNS = [
    re.compile(r"(?:failed|didn't work|doesn't work|broke|error|gave up on)\s*[:\-]?\s*(.{10,200})", re.I),
    re.compile(r"(?:because|reason)\s*[:\-]?\s*(.{10,150})", re.I),
]
_PREFERENCE_PATTERNS = [
    re.compile(r"(?:prefer|always use|we use|I use|use only)\s+(.{5,100})", re.I),
]
_CONVENTION_PATTERNS = [
    re.compile(r"(?:convention|rule|team rule|standard|policy)[:\s]+(.{10,200})", re.I),
    re.compile(r"(?:all PRs?|always|never|must|should)\s+(.{10,150})", re.I),
]


# ---------------------------------------------------------------------------
# ChatJournal
# ---------------------------------------------------------------------------

class ChatJournal:
    """Append-only markdown journal with async compaction.

    Usage::

        journal = ChatJournal(memory_dir=".xanther/memory", repo_id="myrepo")
        # Called once per chat turn (non-blocking):
        journal.append_turn(role="user", content="How does auth work?")
        journal.append_turn(role="assistant", content="Auth uses JWT tokens stored in...")
        # At session end:
        await journal.flush(store)
    """

    def __init__(
        self,
        memory_dir: str | Path,
        repo_id: str = "",
        author: str = "",
        session_id: str = "",
    ) -> None:
        self._dir = Path(memory_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "memory").mkdir(exist_ok=True)

        self._repo_id = repo_id
        self._author = author or _get_author()
        self._session_id = session_id
        self._date_str = _today()

        # The two core files
        self._memory_md = self._dir / "MEMORY.md"
        self._daily_log = self._dir / "memory" / f"{self._date_str}.md"

        # In-memory buffer (flushed to disk periodically or on explicit flush)
        self._buffer: list[str] = []
        self._lock = threading.Lock()

        # Background compaction state
        self._compaction_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._pending_compact = False

        # Ensure files exist with proper headers
        self._ensure_memory_md()
        self._ensure_daily_log()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_turn(
        self,
        role: str,
        content: str,
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append a single chat turn to the in-memory buffer.

        Non-blocking. Call from anywhere in a chat loop.
        The buffer is periodically flushed by flush() or flush_sync().
        """
        ts = _now_iso()
        md_role = "**User**" if role == "user" else "**Assistant**"
        meta_str = ""
        if metadata:
            tags = ", ".join(f"`{k}={v}`" for k, v in metadata.items())
            meta_str = f" <!-- {tags} -->"

        entry = f"\n### {ts}{meta_str}\n{md_role}: {content.strip()}\n"
        with self._lock:
            self._buffer.append(entry)

    def append_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result_summary: str,
    ) -> None:
        """Record a tool call in the daily log."""
        ts = _now_iso()
        args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args.items())
        entry = (
            f"\n### {ts} [tool]\n"
            f"**Tool**: `{tool_name}({args_str})`\n"
            f"**Result**: {result_summary[:200]}\n"
        )
        with self._lock:
            self._buffer.append(entry)

    def note(self, text: str, tag: str = "note") -> None:
        """Write a freeform note to the daily log (e.g. agent interim thoughts)."""
        ts = _now_iso()
        entry = f"\n### {ts} [{tag}]\n{text.strip()}\n"
        with self._lock:
            self._buffer.append(entry)

    async def flush(self, store: Optional["MemoryStore"] = None) -> None:
        """Write buffer to disk. Trigger compaction if needed.

        Call this at the end of a session or periodically during long sessions.
        """
        self._flush_buffer_to_disk()
        if store:
            await self._maybe_compact(store)

    def flush_sync(self) -> None:
        """Synchronous buffer flush (for use in non-async contexts)."""
        self._flush_buffer_to_disk()

    # ------------------------------------------------------------------
    # MEMORY.md — permanent structured memory
    # ------------------------------------------------------------------

    def write_permanent(
        self,
        section: str,
        content: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """Append *content* under *section* in MEMORY.md.

        Returns True if written, False if idempotency_key already present.
        section must be one of the top-level section headers.
        """
        text = self._memory_md.read_text(encoding="utf-8")

        # Idempotency check
        if idempotency_key and idempotency_key in text:
            return False

        if section not in text:
            text += f"\n{section}\n\n"

        # Insert after the section header
        insert_after = section
        entry = f"- {_today()} {content.strip()}"
        if idempotency_key:
            entry += f" <!-- key:{idempotency_key} -->"
        entry += "\n"

        lines = text.splitlines(keepends=True)
        new_lines: list[str] = []
        inserted = False
        i = 0
        while i < len(lines):
            new_lines.append(lines[i])
            if not inserted and lines[i].strip() == insert_after:
                # Insert after the header (skip one blank line)
                if i + 1 < len(lines) and lines[i + 1].strip() == "":
                    new_lines.append(lines[i + 1])
                    i += 1
                new_lines.append(entry)
                inserted = True
            i += 1

        if not inserted:
            new_lines.append(f"\n{section}\n\n{entry}")

        self._memory_md.write_text("".join(new_lines), encoding="utf-8")
        return True

    def read_memory_md(self) -> str:
        """Return the full MEMORY.md content."""
        return self._memory_md.read_text(encoding="utf-8")

    def read_daily_log(self, date: Optional[str] = None) -> str:
        """Return a daily log file content. date = 'YYYY-MM-DD' or today."""
        path = self._dir / "memory" / f"{date or self._date_str}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def list_daily_logs(self) -> list[str]:
        """Return sorted list of YYYY-MM-DD date strings that have log files."""
        dates = []
        for f in sorted((self._dir / "memory").glob("????-??-??.md")):
            dates.append(f.stem)
        return dates

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    async def _maybe_compact(self, store: "MemoryStore") -> None:
        """Trigger compaction if the daily log is above threshold."""
        log_text = self._daily_log.read_text(encoding="utf-8") if self._daily_log.exists() else ""
        line_count = log_text.count("\n")
        if line_count >= COMPACTION_THRESHOLD_LINES:
            logger.info("XME: daily log at %d lines, triggering compaction", line_count)
            await self.compact(store)

    async def compact(self, store: "MemoryStore") -> "CompactionResult":
        """Extract structured nodes from daily log, promote to graph, truncate log."""
        log_text = self._daily_log.read_text(encoding="utf-8") if self._daily_log.exists() else ""
        if not log_text.strip():
            return CompactionResult(lines_before=0, lines_after=0)

        lines = log_text.splitlines()
        lines_before = len(lines)

        # Extract structured memories from raw turns
        extractions = _extract_from_log(log_text)

        # Promote to MemoryStore (SQLite + hot cache)
        promoted = await _promote_extractions(extractions, store, self._repo_id, self._author)

        # Also write key decisions/failures to permanent MEMORY.md
        for d in extractions.get("decisions", []):
            self.write_permanent(_SECTION_DECISIONS, d, idempotency_key=d[:40])
        for f in extractions.get("failed", []):
            self.write_permanent(_SECTION_FAILED, f, idempotency_key=f[:40])
        for p in extractions.get("preferences", []):
            self.write_permanent(_SECTION_PREFERENCES, p, idempotency_key=p[:40])

        # Compact the log: keep last N lines, replace older with a header
        kept_lines = lines[-COMPACT_KEEP_LINES:] if len(lines) > COMPACT_KEEP_LINES else lines
        compact_header = (
            f"<!-- compacted {_now_iso()} | "
            f"extracted: {promoted['decisions']}d {promoted['attempts']}a "
            f"{promoted['preferences']}p -->\n"
        )
        new_content = compact_header + "\n".join(kept_lines)
        self._daily_log.write_text(new_content, encoding="utf-8")

        lines_after = len(kept_lines) + 1
        logger.info(
            "XME compaction: %d → %d lines, promoted %s",
            lines_before, lines_after, promoted,
        )
        return CompactionResult(
            lines_before=lines_before,
            lines_after=lines_after,
            promoted=promoted,
            extractions=extractions,
        )

    # ------------------------------------------------------------------
    # File initialization
    # ------------------------------------------------------------------

    def _ensure_memory_md(self) -> None:
        if not self._memory_md.exists():
            self._memory_md.write_text(
                f"# Xanther Memory\n\n"
                f"repo: {self._repo_id}  \n"
                f"created: {_today()}  \n\n"
                + "\n\n".join(s + "\n" for s in _MEMORY_SECTIONS),
                encoding="utf-8",
            )

    def _ensure_daily_log(self) -> None:
        if not self._daily_log.exists():
            self._daily_log.write_text(
                f"# Session Log — {self._date_str}\n\n"
                f"repo: {self._repo_id}  \n"
                f"author: {self._author}  \n\n",
                encoding="utf-8",
            )

    def _flush_buffer_to_disk(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            content = "".join(self._buffer)
            self._buffer.clear()

        with open(self._daily_log, "a", encoding="utf-8") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_from_log(log_text: str) -> dict[str, list[str]]:
    """Extract structured memory candidates from raw markdown log text.

    Returns dict with keys: decisions, failed, preferences, conventions.
    Uses regex heuristics — no LLM needed.
    """
    results: dict[str, list[str]] = {
        "decisions": [],
        "failed": [],
        "preferences": [],
        "conventions": [],
    }

    # Split into assistant turns only (decisions come from agent output)
    assistant_turns = re.findall(
        r"\*\*Assistant\*\*:\s*(.*?)(?=\n###|\Z)", log_text, re.DOTALL
    )
    full_text = "\n".join(assistant_turns)

    def _collect(patterns: list[re.Pattern[str]], key: str) -> None:  # type: ignore[type-arg]
        seen: set[str] = set()
        for pattern in patterns:
            for m in pattern.finditer(full_text):
                text = m.group(1).strip().rstrip(".,;")
                normalized = text.lower()[:60]
                if len(text) >= 10 and normalized not in seen:
                    seen.add(normalized)
                    results[key].append(text[:200])

    _collect(_DECISION_PATTERNS, "decisions")
    _collect(_FAILED_PATTERNS, "failed")
    _collect(_PREFERENCE_PATTERNS, "preferences")
    _collect(_CONVENTION_PATTERNS, "conventions")

    return results


async def _promote_extractions(
    extractions: dict[str, list[str]],
    store: "MemoryStore",
    repo_id: str,
    author: str,
) -> dict[str, int]:
    """Write extracted memories to the MemoryStore. Returns counts per type."""
    from xce.memory.models import DecisionNode, AttemptNode, UserPreferenceNode
    import asyncio

    counts: dict[str, int] = {"decisions": 0, "attempts": 0, "preferences": 0}

    def _write() -> None:
        for text in extractions.get("decisions", []):
            node = DecisionNode()
            node.repo_id = repo_id
            node.author = author
            node.title = text[:100]
            node.context = text
            node.decision = text
            node.outcome = "pending"
            store.save_decision(node)
            counts["decisions"] += 1

        for text in extractions.get("failed", []):
            node = AttemptNode()
            node.repo_id = repo_id
            node.author = author
            node.problem = text[:100]
            node.approach = "unknown"
            node.result = "failed"
            node.failure_reason = text
            store.save_attempt(node)
            counts["attempts"] += 1

        for text in extractions.get("preferences", []):
            node = UserPreferenceNode()
            node.repo_id = repo_id
            node.author = author
            node.preference_type = "inferred"
            node.key = text[:60]
            node.value = text
            node.source = "inferred"
            node.confidence = 0.6
            store.save_preference(node)
            counts["preferences"] += 1

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)
    return counts


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


@dataclass
class CompactionResult:
    lines_before: int = 0
    lines_after: int = 0
    promoted: dict[str, int] = field(default_factory=dict)
    extractions: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_promoted(self) -> int:
        return sum(self.promoted.values())

    @property
    def reduction_pct(self) -> float:
        if self.lines_before == 0:
            return 0.0
        return round((1 - self.lines_after / self.lines_before) * 100, 1)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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
