"""XME domain models.

Two memory scopes:
  PERSONAL — local-only, per-user. Never synced to git.
  TEAM     — git-synced, shared across the team.

Node types:
  SessionNode       — a completed agent session (personal)
  UserPreferenceNode— inferred/explicit coding preferences (personal)
  DecisionNode      — architectural decision + rationale (team)
  AttemptNode       — an approach tried for a problem, with outcome (team)
  TeamConventionNode— team-wide coding/process convention (team)

All nodes carry:
  id            — uuid4, stable across syncs
  created_at    — ISO-8601 UTC
  updated_at    — ISO-8601 UTC (set on every write)
  author        — git user.name or $USER (never empty)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

class MemoryScope(str, Enum):
    """Whether a memory node is personal (local) or shared with the team."""
    PERSONAL = "personal"
    TEAM = "team"


# ---------------------------------------------------------------------------
# Personal memory nodes
# ---------------------------------------------------------------------------

@dataclass
class SessionNode:
    """Records a completed agent session — what was tried and what happened.

    Scope: PERSONAL (never synced).
    """
    scope: MemoryScope = field(default=MemoryScope.PERSONAL, init=False)

    # identity
    id: str = field(default_factory=_new_id)
    repo_id: str = ""

    # session metadata
    agent_type: str = ""                    # "kiro", "claude-code", "cursor", etc.
    model: str = ""                         # "claude-sonnet-4", etc.
    started_at: str = field(default_factory=_now_iso)
    ended_at: Optional[str] = None

    # what happened
    problem_statement: str = ""
    summary: str = ""                       # LLM-generated or user-written recap
    files_touched: list[str] = field(default_factory=list)
    outcome: str = "unknown"                # "success" | "failed" | "partial" | "unknown"
    next_steps: str = ""

    # bookkeeping
    author: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # XCE linkage — AST node IDs that were involved
    linked_node_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "repo_id": self.repo_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "problem_statement": self.problem_statement,
            "summary": self.summary,
            "files_touched": self.files_touched,
            "outcome": self.outcome,
            "next_steps": self.next_steps,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "linked_node_ids": self.linked_node_ids,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionNode":
        n = cls()
        for k, v in d.items():
            if k == "scope":
                continue  # fixed
            if hasattr(n, k):
                setattr(n, k, v)
        return n


@dataclass
class UserPreferenceNode:
    """An inferred or explicitly stated coding preference.

    Scope: PERSONAL.
    Examples: prefers PostgreSQL, names files in kebab-case, avoids `any` in TS.
    """
    scope: MemoryScope = field(default=MemoryScope.PERSONAL, init=False)

    id: str = field(default_factory=_new_id)
    repo_id: str = ""               # empty = global preference

    preference_type: str = ""       # "tech_stack" | "naming" | "code_style" | "testing" | "other"
    key: str = ""                   # e.g. "database", "naming_convention"
    value: str = ""                 # e.g. "postgresql", "kebab-case"
    source: str = "inferred"        # "inferred" | "explicit"
    confidence: float = 0.8         # 0–1

    author: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "repo_id": self.repo_id,
            "preference_type": self.preference_type,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UserPreferenceNode":
        n = cls()
        for k, v in d.items():
            if k == "scope":
                continue
            if hasattr(n, k):
                setattr(n, k, v)
        return n


# ---------------------------------------------------------------------------
# Team memory nodes
# ---------------------------------------------------------------------------

@dataclass
class DecisionNode:
    """An architectural or technical decision made for a repository.

    Scope: TEAM (git-synced).
    Linked to specific XCE AST nodes (modules, files, classes).
    """
    scope: MemoryScope = field(default=MemoryScope.TEAM, init=False)

    id: str = field(default_factory=_new_id)
    repo_id: str = ""

    title: str = ""
    context: str = ""                           # why this decision was needed
    decision: str = ""                          # what was decided
    alternatives_considered: list[str] = field(default_factory=list)
    consequences: str = ""                      # tradeoffs accepted
    outcome: str = "pending"                    # "validated" | "reverted" | "pending"

    # linkage
    affected_modules: list[str] = field(default_factory=list)   # module paths from XCE
    linked_node_ids: list[str] = field(default_factory=list)    # XCE ASTNode IDs
    linked_adr_path: Optional[str] = None                       # e.g. "docs/decisions/011.md"
    supersedes_id: Optional[str] = None                         # ID of the decision this replaces

    author: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # sync metadata — managed by MemorySyncer
    _sync_hash: str = ""    # SHA-1 of canonical JSON; set on sync
    _pending_sync: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "repo_id": self.repo_id,
            "title": self.title,
            "context": self.context,
            "decision": self.decision,
            "alternatives_considered": self.alternatives_considered,
            "consequences": self.consequences,
            "outcome": self.outcome,
            "affected_modules": self.affected_modules,
            "linked_node_ids": self.linked_node_ids,
            "linked_adr_path": self.linked_adr_path,
            "supersedes_id": self.supersedes_id,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionNode":
        n = cls()
        for k, v in d.items():
            if k == "scope":
                continue
            if hasattr(n, k):
                setattr(n, k, v)
        return n


@dataclass
class AttemptNode:
    """An approach tried for a specific problem, with outcome.

    Scope: TEAM (git-synced).
    The key uniqueness: we store WHY it failed, not just that it failed.
    This prevents teams from retrying the same doomed approach.
    """
    scope: MemoryScope = field(default=MemoryScope.TEAM, init=False)

    id: str = field(default_factory=_new_id)
    repo_id: str = ""

    problem: str = ""                           # what was being solved
    approach: str = ""                          # what was tried
    result: str = "unknown"                     # "success" | "failed" | "partial" | "unknown"
    failure_reason: str = ""                    # if failed: root cause
    lessons_learned: str = ""                   # actionable insight for next time

    # linkage
    linked_decision_id: Optional[str] = None    # DecisionNode that came from this
    linked_node_ids: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    session_id: Optional[str] = None            # SessionNode that recorded this

    author: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    _sync_hash: str = ""
    _pending_sync: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "repo_id": self.repo_id,
            "problem": self.problem,
            "approach": self.approach,
            "result": self.result,
            "failure_reason": self.failure_reason,
            "lessons_learned": self.lessons_learned,
            "linked_decision_id": self.linked_decision_id,
            "linked_node_ids": self.linked_node_ids,
            "files_touched": self.files_touched,
            "session_id": self.session_id,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AttemptNode":
        n = cls()
        for k, v in d.items():
            if k == "scope":
                continue
            if hasattr(n, k):
                setattr(n, k, v)
        return n


@dataclass
class TeamConventionNode:
    """A team-wide convention or process agreement.

    Scope: TEAM (git-synced).
    Examples: "All PRs need 2 approvals", "use Result types not exceptions".
    """
    scope: MemoryScope = field(default=MemoryScope.TEAM, init=False)

    id: str = field(default_factory=_new_id)
    repo_id: str = ""

    convention_type: str = ""   # "testing" | "git" | "code_review" | "naming" | "architecture" | "other"
    title: str = ""
    description: str = ""
    rationale: str = ""
    status: str = "active"      # "active" | "deprecated" | "pending_validation"
    confirmed_by: list[str] = field(default_factory=list)  # list of authors who confirmed

    author: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    _sync_hash: str = ""
    _pending_sync: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "repo_id": self.repo_id,
            "convention_type": self.convention_type,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "status": self.status,
            "confirmed_by": self.confirmed_by,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TeamConventionNode":
        n = cls()
        for k, v in d.items():
            if k == "scope":
                continue
            if hasattr(n, k):
                setattr(n, k, v)
        return n


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------

@dataclass
class MemorySearchResult:
    """A single result from a memory search query."""
    node_type: str              # "session" | "decision" | "attempt" | "preference" | "convention"
    node_id: str
    score: float                # 0–1, higher = more relevant
    scope: MemoryScope
    summary: str                # Short text representing this result
    data: dict[str, Any] = field(default_factory=dict)   # full node dict
