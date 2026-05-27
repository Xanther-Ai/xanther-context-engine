"""Error handling and resilience for the Xanther Context Engine.

Implements:
- Neo4j circuit breaker (open after 3 failures, 30s timeout, half-open probe)
- Graceful source code error handling
- Embedding dimension mismatch detection
- Token budget overflow handling
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable, TypeVar

import tiktoken

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 10.1  Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker for Neo4j connections.

    Opens after ``failure_threshold`` consecutive failures, stays open for
    ``timeout_seconds``, then transitions to half-open for a single probe.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.timeout_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        """Record a successful operation — reset to closed."""
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed operation — may trip the breaker."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN after %d consecutive failures",
                self._failure_count,
            )

    def allow_request(self) -> bool:
        """Return True if a request is allowed through."""
        current = self.state
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return True  # allow one probe
        return False

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute *func* through the circuit breaker.

        Raises ``CircuitBreakerOpenError`` when the circuit is open.
        """
        if not self.allow_request():
            raise CircuitBreakerOpenError("Circuit breaker is open — Neo4j unavailable")
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open."""


# ---------------------------------------------------------------------------
# 10.2  Graceful source code error handling
# ---------------------------------------------------------------------------


def safe_parse_file(parse_fn: Callable[..., Any], filepath: str, source: str) -> Any:
    """Wrap a parse function to catch SyntaxError and skip gracefully."""
    try:
        return parse_fn(filepath, source)
    except SyntaxError as exc:
        logger.warning("Skipping %s due to syntax error: %s", filepath, exc)
        return [], []


# ---------------------------------------------------------------------------
# 10.3  Embedding dimension mismatch detection
# ---------------------------------------------------------------------------


def validate_embedding_dimensions(
    embedding: list[float],
    expected_dimensions: int,
    context: str = "",
) -> None:
    """Raise ValueError if embedding dimensions don't match expected."""
    if len(embedding) != expected_dimensions:
        msg = (
            f"Embedding dimension mismatch: got {len(embedding)}, "
            f"expected {expected_dimensions}"
        )
        if context:
            msg += f" (context: {context})"
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# 10.4  Token budget overflow handling
# ---------------------------------------------------------------------------


def truncate_to_token_budget(
    text: str,
    max_tokens: int,
    encoding_name: str = "cl100k_base",
) -> str:
    """Post-truncate text to fit within *max_tokens*.

    Preserves complete sentences where possible.
    """
    tokenizer = tiktoken.get_encoding(encoding_name)
    tokens = tokenizer.encode(text)
    if len(tokens) <= max_tokens:
        return text
    truncated = tokenizer.decode(tokens[:max_tokens])
    # Try to end at a sentence boundary
    last_period = truncated.rfind(".")
    if last_period > len(truncated) // 2:
        truncated = truncated[: last_period + 1]
    logger.warning(
        "Truncated output from %d to %d tokens (budget: %d)",
        len(tokens),
        len(tokenizer.encode(truncated)),
        max_tokens,
    )
    return truncated
