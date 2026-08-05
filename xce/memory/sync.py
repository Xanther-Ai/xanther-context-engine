"""XME MemorySyncer — git-backed team memory sync.

Team memory (decisions, attempts, conventions) lives in two places:
  Warm store: SQLite (this machine, fast)
  Cold store: .xanther/memory/team/ directory (git-tracked JSON files)

Sync flow:
  1. pull()  — git pull on the memory dir (or the repo root)
               Load any new/changed JSON files from cold into warm
               Refresh hot cache for changed IDs
  2. push()  — Write all pending_sync=True rows from warm → cold (JSON)
               git add + git commit + git push
  3. sync()  — pull() then push() (the normal operation)

Conflict resolution (append-only design minimises conflicts):
  - Each node has a stable UUID. New nodes never conflict.
  - If the same ID was updated on two machines:
      field-level merge: take union of list fields, latest timestamp wins
      for scalar fields (outcome, result): latest updated_at wins
  - Convention conflicts → status set to 'pending_validation'

Cold storage layout:
  .xanther/memory/
  ├── xme.db                      ← SQLite warm store
  └── team/
      ├── decisions/
      │   └── {id}.json
      ├── attempts/
      │   └── {id}.json
      └── conventions/
          └── {id}.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from xce.memory.store import MemoryStore

from xce.memory.models import (
    AttemptNode,
    DecisionNode,
    TeamConventionNode,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(data: dict[str, Any]) -> str:
    """Stable SHA-1 of the canonical JSON (sorted keys, no sync metadata)."""
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    canonical = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()


class MemorySyncer:
    """Manages git-backed cold storage sync for team memory.

    Usage::

        syncer = MemorySyncer(memory_dir="/repo/.xanther/memory", repo_root="/repo")
        syncer.push(store)   # write pending → cold, git commit+push
        syncer.pull(store)   # git pull, load new cold → warm
        syncer.sync(store)   # pull then push
    """

    def __init__(
        self,
        memory_dir: str | Path,
        repo_root: Optional[str | Path] = None,
        remote: str = "origin",
        branch: str = "main",
    ) -> None:
        self._dir = Path(memory_dir).resolve()
        self._team_dir = self._dir / "team"
        self._repo_root = Path(repo_root).resolve() if repo_root else self._dir
        self._remote = remote
        self._branch = branch

        # Ensure cold storage dirs exist
        for sub in ("decisions", "attempts", "conventions"):
            (self._team_dir / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, store: "MemoryStore") -> dict[str, int]:
        """Write all pending nodes to cold store and git-commit+push."""
        pushed: dict[str, int] = {"decisions": 0, "attempts": 0, "conventions": 0}

        decisions = store.get_pending_decisions()
        for d in decisions:
            self._write_cold("decisions", d.id, d.to_dict())
        pushed["decisions"] = len(decisions)

        attempts = store.get_pending_attempts()
        for a in attempts:
            self._write_cold("attempts", a.id, a.to_dict())
        pushed["attempts"] = len(attempts)

        conventions = store.get_pending_conventions()
        for c in conventions:
            self._write_cold("conventions", c.id, c.to_dict())
        pushed["conventions"] = len(conventions)

        total = sum(pushed.values())
        if total == 0:
            logger.debug("XME push: nothing to sync")
            return pushed

        # Git commit + push
        try:
            self._git_add_and_commit(
                f"xme: sync {total} memory nodes "
                f"({pushed['decisions']}d {pushed['attempts']}a {pushed['conventions']}c)"
            )
            self._git_push()

            # Mark synced in warm store
            store.mark_synced("team_decisions", [d.id for d in decisions])
            store.mark_synced("team_attempts", [a.id for a in attempts])
            store.mark_synced("team_conventions", [c.id for c in conventions])

            logger.info("XME pushed %d nodes to cold store", total)
        except GitError as e:
            logger.warning("XME push failed (git error): %s", e)

        return pushed

    def pull(self, store: "MemoryStore") -> dict[str, int]:
        """Git-pull and load any new/changed cold nodes into warm store."""
        loaded: dict[str, int] = {"decisions": 0, "attempts": 0, "conventions": 0}

        try:
            self._git_pull()
        except GitError as e:
            logger.warning("XME pull failed (git error): %s", e)
            return loaded

        # Load cold → warm with conflict resolution
        for json_file in (self._team_dir / "decisions").glob("*.json"):
            d = self._read_cold(json_file)
            if d is None:
                continue
            existing = store.get_decision(d["id"])
            if existing is None:
                node = DecisionNode.from_dict(d)
                node._pending_sync = False
                store.save_decision(node)
                store.mark_synced("team_decisions", [node.id])
                loaded["decisions"] += 1
            else:
                merged = self._merge_decision(existing.to_dict(), d)
                if merged:
                    node = DecisionNode.from_dict(merged)
                    node._pending_sync = False
                    store.save_decision(node)
                    store.mark_synced("team_decisions", [node.id])
                    loaded["decisions"] += 1

        for json_file in (self._team_dir / "attempts").glob("*.json"):
            d = self._read_cold(json_file)
            if d is None:
                continue
            existing = store.get_attempt(d["id"])
            if existing is None:
                node = AttemptNode.from_dict(d)
                node._pending_sync = False
                store.save_attempt(node)
                store.mark_synced("team_attempts", [node.id])
                loaded["attempts"] += 1
            # Attempts are append-only — no merge needed

        for json_file in (self._team_dir / "conventions").glob("*.json"):
            d = self._read_cold(json_file)
            if d is None:
                continue
            existing = store.get_convention_by_id(d["id"]) if hasattr(store, "get_convention_by_id") else None
            if existing is None:
                node = TeamConventionNode.from_dict(d)
                node._pending_sync = False
                store.save_convention(node)
                store.mark_synced("team_conventions", [node.id])
                loaded["conventions"] += 1

        total = sum(loaded.values())
        if total:
            store.warm_hot_cache()
            logger.info("XME pulled %d new nodes from cold store", total)

        return loaded

    def sync(self, store: "MemoryStore") -> dict[str, dict[str, int]]:
        """Full sync: pull (get team changes) then push (share ours)."""
        pulled = self.pull(store)
        pushed = self.push(store)
        return {"pulled": pulled, "pushed": pushed}

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_decision(local: dict[str, Any], remote: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Merge two versions of the same decision.

        Rules:
          - List fields: take union
          - outcome: latest updated_at wins
          - Other scalar fields: latest updated_at wins
        Returns merged dict, or None if identical.
        """
        local_ts = local.get("updated_at", "")
        remote_ts = remote.get("updated_at", "")

        if _content_hash(local) == _content_hash(remote):
            return None  # identical — nothing to do

        merged = dict(local)
        newer = remote if remote_ts >= local_ts else local
        older = local if remote_ts >= local_ts else remote

        # Take newer for scalars
        for field in ("title", "context", "decision", "consequences", "outcome",
                       "linked_adr_path", "supersedes_id"):
            merged[field] = newer.get(field, older.get(field))

        # Take union for lists
        for field in ("alternatives_considered", "affected_modules", "linked_node_ids"):
            merged[field] = list({
                *local.get(field, []),
                *remote.get(field, []),
            })

        merged["updated_at"] = _now_iso()
        return merged

    # ------------------------------------------------------------------
    # Cold store I/O
    # ------------------------------------------------------------------

    def _write_cold(self, subdir: str, node_id: str, data: dict[str, Any]) -> None:
        target = self._team_dir / subdir / f"{node_id}.json"
        # Strip internal sync metadata before persisting
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        target.write_text(json.dumps(clean, indent=2, ensure_ascii=False))

    @staticmethod
    def _read_cold(path: Path) -> Optional[dict[str, Any]]:
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning("Could not read cold store file %s: %s", path, e)
            return None

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def _git(self, *args: str) -> str:
        cmd = ["git", "-C", str(self._repo_root), *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()

    def _git_add_and_commit(self, message: str) -> None:
        self._git("add", str(self._team_dir.relative_to(self._repo_root)))
        # If nothing staged, skip commit
        status = subprocess.run(
            ["git", "-C", str(self._repo_root), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if status.returncode == 0:
            logger.debug("XME: nothing staged, skipping commit")
            return
        self._git("commit", "-m", message)

    def _git_push(self) -> None:
        self._git("push", self._remote, self._branch)

    def _git_pull(self) -> None:
        self._git("pull", "--rebase", self._remote, self._branch)


class GitError(RuntimeError):
    """Raised when a git command fails."""
