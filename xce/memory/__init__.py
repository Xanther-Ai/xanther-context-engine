"""XME — Xanther Memory Engine.

Provides two-tier persistent memory for coding agents:
  - Personal memory: local-only, per-user session state, preferences, learnings
  - Team memory:     git-synced, shared decisions, failed approaches, conventions

Storage hierarchy:
  Hot cache  (in-process LRU)     → sub-millisecond retrieval
  Warm cache (local SQLite)       → recent months, semantic search
  Cold store (git-tracked JSON)   → full history, team sync

Public surface:
  MemoryStore   — unified read/write API
  XMECache      — LRU hot cache
  MemorySyncer  — git pull/push + conflict resolution
"""

from xce.memory.models import (
    MemoryScope,
    SessionNode,
    DecisionNode,
    AttemptNode,
    UserPreferenceNode,
    TeamConventionNode,
    MemorySearchResult,
)
from xce.memory.store import MemoryStore
from xce.memory.cache import XMECache
from xce.memory.sync import MemorySyncer
from xce.memory.journal import ChatJournal, CompactionResult
from xce.memory.lifecycle import SessionContext, JournalingMiddleware, generate_xme_steering

__all__ = [
    "MemoryScope",
    "SessionNode",
    "DecisionNode",
    "AttemptNode",
    "UserPreferenceNode",
    "TeamConventionNode",
    "MemorySearchResult",
    "MemoryStore",
    "XMECache",
    "MemorySyncer",
    "ChatJournal",
    "CompactionResult",
    "SessionContext",
    "JournalingMiddleware",
    "generate_xme_steering",
]
