"""Tests for error handling and resilience (Task 10).

Validates:
- Circuit breaker state transitions (closed → open → half-open → closed)
- Syntax error skip behavior
- Embedding dimension rejection
- Token budget overflow truncation
"""

from __future__ import annotations

import time

import pytest

from xce.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    safe_parse_file,
    truncate_to_token_budget,
    validate_embedding_dimensions,
)


class TestCircuitBreaker:
    """10.1 — Circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_requests(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=30)
        for _ in range(3):
            cb.record_failure()
        assert not cb.allow_request()

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=0.1)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request()

    def test_closes_on_success_after_half_open(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=0.1)
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=0.1)
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_success(self):
        cb = CircuitBreaker()

        async def ok():
            return 42

        result = await cb.call(ok)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_failure_records(self):
        cb = CircuitBreaker(failure_threshold=2)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_raises_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_seconds=30)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        async def ok():
            return 1

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(ok)


class TestSafeParseFile:
    """10.2 — Graceful syntax error handling."""

    def test_catches_syntax_error(self):
        def bad_parse(fp, src):
            raise SyntaxError("bad")

        result = safe_parse_file(bad_parse, "test.py", "bad code")
        assert result == ([], [])

    def test_passes_through_on_success(self):
        def good_parse(fp, src):
            return ["node"], ["edge"]

        result = safe_parse_file(good_parse, "test.py", "good code")
        assert result == (["node"], ["edge"])


class TestEmbeddingDimensionValidation:
    """10.3 — Embedding dimension mismatch detection."""

    def test_valid_dimensions_pass(self):
        validate_embedding_dimensions([0.1] * 512, 512)

    def test_wrong_dimensions_raise(self):
        with pytest.raises(ValueError, match="dimension mismatch"):
            validate_embedding_dimensions([0.1] * 256, 512)

    def test_error_includes_context(self):
        with pytest.raises(ValueError, match="node-123"):
            validate_embedding_dimensions([0.1] * 10, 512, context="node-123")


class TestTokenBudgetOverflow:
    """10.4 — Token budget overflow truncation."""

    def test_short_text_unchanged(self):
        text = "Hello world."
        result = truncate_to_token_budget(text, max_tokens=100)
        assert result == text

    def test_long_text_truncated(self):
        text = "word " * 500  # ~500 tokens
        result = truncate_to_token_budget(text, max_tokens=50)
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        assert len(enc.encode(result)) <= 50

    def test_preserves_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence. " * 20
        result = truncate_to_token_budget(text, max_tokens=30)
        assert result.endswith(".")
