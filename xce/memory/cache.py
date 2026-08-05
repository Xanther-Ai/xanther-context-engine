"""XME hot cache — in-process LRU for sub-millisecond memory retrieval.

Two levels:
  Hot (in-process LRU)
    - Active session context for the current session
    - Top-K recent personal memories for the current user
    - Top-K recent team decisions loaded at startup
    - User preferences (all, typically small)

  The hot cache is populated:
    - On MemoryStore.get_context_for_session() calls
    - After every write (write-through)
    - On MemorySyncer.post_sync_refresh() (after a git pull)

  Eviction:
    - LRU with configurable max_size (default 256 entries)
    - Entries expire after ttl_seconds (default 1 hour)
    - On session end, session entry is promoted to warm (SQLite)
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    value: Any
    inserted_at: float = field(default_factory=time.monotonic)


class XMECache:
    """Thread-safe (single-process) LRU cache with TTL eviction.

    Keys are arbitrary strings (typically node IDs or query strings).
    Values are raw dicts (``node.to_dict()`` outputs).

    Usage::

        cache = XMECache(max_size=256, ttl_seconds=3600)
        cache.set("decision:abc", decision_node.to_dict())
        data = cache.get("decision:abc")  # → dict or None
        cache.invalidate("decision:abc")
        cache.clear()
    """

    def __init__(self, max_size: int = 256, ttl_seconds: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

        # Namespace counters for observability
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None (LRU bump + TTL check)."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        # TTL check
        if time.monotonic() - entry.inserted_at > self._ttl:
            del self._store[key]
            self._misses += 1
            return None

        # LRU bump — move to end (most recently used)
        self._store.move_to_end(key)
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any) -> None:
        """Insert or update a cache entry. Evicts LRU on overflow."""
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = _CacheEntry(value=value)
            return

        self._store[key] = _CacheEntry(value=value)
        self._store.move_to_end(key)

        if len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._evictions += 1
            logger.debug("XMECache evicted key=%s", evicted_key)

    def invalidate(self, key: str) -> None:
        """Remove a single entry (no-op if missing)."""
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all keys that start with *prefix*. Returns count removed."""
        to_remove = [k for k in self._store if k.startswith(prefix)]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def clear(self) -> None:
        """Wipe all entries."""
        self._store.clear()

    # ------------------------------------------------------------------
    # Bulk warm-load
    # ------------------------------------------------------------------

    def warm_load(self, entries: dict[str, Any]) -> None:
        """Bulk-populate cache (e.g. after git pull / startup)."""
        for k, v in entries.items():
            self.set(k, v)
        logger.debug("XMECache warmed with %d entries", len(entries))

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._store)

    def stats(self) -> dict[str, int]:
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "max_size": self._max_size,
        }

    # ------------------------------------------------------------------
    # Convenience namespace helpers
    # ------------------------------------------------------------------

    @staticmethod
    def session_key(session_id: str) -> str:
        return f"session:{session_id}"

    @staticmethod
    def decision_key(decision_id: str) -> str:
        return f"decision:{decision_id}"

    @staticmethod
    def attempt_key(attempt_id: str) -> str:
        return f"attempt:{attempt_id}"

    @staticmethod
    def preference_key(author: str, key: str) -> str:
        return f"pref:{author}:{key}"

    @staticmethod
    def convention_key(convention_id: str) -> str:
        return f"convention:{convention_id}"

    @staticmethod
    def query_key(namespace: str, query: str, repo_id: str) -> str:
        """Cache key for a search query result set."""
        import hashlib
        digest = hashlib.sha1(f"{namespace}:{query}:{repo_id}".encode()).hexdigest()[:12]
        return f"query:{namespace}:{digest}"
