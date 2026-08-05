"""XME Hook Handler — CLI script invoked by Kiro and Claude Code hooks.

Both Kiro and Claude Code hooks call shell commands with JSON context on stdin.
This script is that shell command. It handles all XME hook events:

  Event               Source          What XME does
  ─────────────────── ─────────────── ────────────────────────────────────────
  agentStop           Kiro            flush + compact + save session
  promptSubmit        Kiro            record user turn in journal
  postToolUse         Kiro/CC         record tool call in journal
  Stop                Claude Code     flush + compact + save session
  UserPromptSubmit    Claude Code     record user turn
  PostToolUse         Claude Code     record tool call

Invoked by hook scripts as:
    python -m xce.memory.hook_handler --event agentStop --repo-path /path/to/repo

Or receiving JSON on stdin (Claude Code style):
    echo '{"event":"Stop","session_id":"abc","repo_path":"/repo"}' | \
        python -m xce.memory.hook_handler

The script is deliberately fast and silent:
  - Never blocks for more than 200ms
  - Writes errors to stderr only, never stdout (Claude Code reads stdout)
  - Exit 0 always (errors are logged, never surfaced to break the agent)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s xme-hook: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("xme.hook")

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="XME hook handler — invoked by Kiro/Claude Code hooks",
    )
    parser.add_argument("--event", default="", help="Event name")
    parser.add_argument("--repo-path", default="", help="Repo root path")
    parser.add_argument("--tool-name", default="", help="Tool name (postToolUse)")
    parser.add_argument("--tool-result", default="", help="Tool result summary (postToolUse)")
    parser.add_argument("--content", default="", help="Turn content (promptSubmit)")
    parser.add_argument("--summary", default="", help="Session summary (agentStop)")
    parser.add_argument("--outcome", default="unknown", help="Session outcome")
    args = parser.parse_args()

    # Also try reading JSON from stdin (Claude Code passes context on stdin)
    stdin_data: dict[str, Any] = {}
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read(8192)
            if raw.strip():
                stdin_data = json.loads(raw)
        except Exception:
            pass

    # Merge: CLI args take priority over stdin
    event = args.event or stdin_data.get("event", "") or stdin_data.get("hook_event_name", "")
    repo_path = (
        args.repo_path
        or stdin_data.get("repo_path", "")
        or stdin_data.get("cwd", "")
        or _find_repo_root()
    )

    if not event:
        logger.warning("No event specified, nothing to do")
        sys.exit(0)

    if not repo_path or not Path(repo_path).is_dir():
        # Silently exit — not all events have a repo path
        sys.exit(0)

    # Dispatch
    event_normalized = event.lower().replace("-", "_").replace(" ", "_")

    try:
        if event_normalized in ("agentstop", "stop", "session_end"):
            summary = args.summary or stdin_data.get("summary", "")
            outcome = args.outcome or stdin_data.get("outcome", "unknown")
            asyncio.run(_handle_session_end(repo_path, summary, outcome, stdin_data))

        elif event_normalized in ("promptsubmit", "userpromptsubmit", "prompt_submit"):
            content = args.content or stdin_data.get("content", "") or stdin_data.get("prompt", "")
            _handle_turn(repo_path, role="user", content=content)

        elif event_normalized in ("posttooluse", "post_tool_use"):
            tool_name = args.tool_name or stdin_data.get("tool_name", "") or stdin_data.get("tool", "")
            tool_result = args.tool_result or stdin_data.get("tool_result", "") or stdin_data.get("output", "")
            tool_input = stdin_data.get("tool_input", {})
            _handle_tool_call(repo_path, tool_name, tool_input, tool_result)

        elif event_normalized in ("agentstart", "sessionstart", "session_start"):
            _handle_session_start(repo_path, stdin_data)

        else:
            logger.debug("Unhandled event: %s", event)

    except Exception as e:
        logger.warning("Hook handler error (event=%s): %s", event, e)

    # Always exit 0 — never break the agent
    sys.exit(0)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_session_end(
    repo_path: str,
    summary: str,
    outcome: str,
    extra: dict[str, Any],
) -> None:
    """Flush journal, compact, save SessionNode. Called on agentStop / Stop."""
    try:
        from xce.memory.store import MemoryStore
        from xce.memory.journal import ChatJournal
        from xce.memory.models import SessionNode
        from xce.memory.lifecycle import _DEFAULT_XME_DIR

        memory_dir = Path(repo_path) / _DEFAULT_XME_DIR
        repo_id = Path(repo_path).name

        with MemoryStore.open(repo_path) as store:
            journal = ChatJournal(
                memory_dir=str(memory_dir),
                repo_id=repo_id,
            )

            # Mark end in journal
            journal.note(
                f"SESSION END via hook | outcome={outcome} | {summary[:80]}",
                tag="session",
            )
            journal.flush_sync()

            # Compact — extract structured nodes from everything in the log
            try:
                result = await journal.compact(store)
                logger.warning(
                    "Compacted: %d→%d lines, promoted=%s",
                    result.lines_before, result.lines_after, result.promoted,
                )
            except Exception as e:
                logger.warning("Compact failed: %s", e)

            # Save session node
            files_touched = extra.get("files_touched", extra.get("modified_files", []))
            if isinstance(files_touched, str):
                files_touched = [files_touched]

            session = SessionNode()
            session.repo_id = repo_id
            session.summary = summary
            session.outcome = outcome
            session.files_touched = files_touched or []
            session.problem_statement = extra.get("problem_statement", extra.get("task", ""))
            store.save_session(session)

            logger.warning("Session saved: %s outcome=%s", session.id[:8], outcome)

    except Exception as e:
        logger.warning("Session end handler failed: %s", e)


def _handle_turn(repo_path: str, role: str, content: str) -> None:
    """Append a user/assistant turn to the journal (sync, fast path)."""
    if not content:
        return
    try:
        from xce.memory.journal import ChatJournal
        from xce.memory.lifecycle import _DEFAULT_XME_DIR

        memory_dir = Path(repo_path) / _DEFAULT_XME_DIR
        journal = ChatJournal(
            memory_dir=str(memory_dir),
            repo_id=Path(repo_path).name,
        )
        journal.append_turn(role=role, content=content[:500])
        journal.flush_sync()
    except Exception as e:
        logger.warning("Turn handler failed: %s", e)


def _handle_tool_call(
    repo_path: str,
    tool_name: str,
    tool_input: dict[str, Any],
    result: str,
) -> None:
    """Record a tool invocation in the journal (sync, fast path)."""
    if not tool_name:
        return
    # Skip XME meta-tools to avoid circular journaling
    if tool_name.startswith("xme_"):
        return
    try:
        from xce.memory.journal import ChatJournal
        from xce.memory.lifecycle import _DEFAULT_XME_DIR

        memory_dir = Path(repo_path) / _DEFAULT_XME_DIR
        journal = ChatJournal(
            memory_dir=str(memory_dir),
            repo_id=Path(repo_path).name,
        )
        journal.append_tool_call(
            tool_name=tool_name,
            args={k: str(v)[:60] for k, v in tool_input.items()},
            result_summary=str(result)[:200],
        )
        journal.flush_sync()
    except Exception as e:
        logger.warning("Tool call handler failed: %s", e)


def _handle_session_start(repo_path: str, extra: dict[str, Any]) -> None:
    """Pre-warm cache at session start (sync, best-effort)."""
    try:
        from xce.memory.store import MemoryStore

        with MemoryStore.open(repo_path) as store:
            repo_id = Path(repo_path).name
            store.warm_hot_cache(repo_id=repo_id, limit=50)
            logger.warning("Cache warmed for %s", repo_id)
    except Exception as e:
        logger.warning("Session start handler failed: %s", e)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _find_repo_root() -> str:
    """Walk up from cwd to find the git root."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


if __name__ == "__main__":
    main()
