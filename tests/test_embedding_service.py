"""Unit tests for xce.embedding_service.EmbeddingService.

All OpenRouter API calls are mocked. Tests verify:
- Embedding dimensions (5.1)
- build_embedding_text output format (5.2)
- Dimension validation rejection (5.4)
- Rate limit retry behavior (5.3)
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from xce.embedding_service import EmbeddingService, MAX_RETRIES
from xce.models import ASTNode, NodeKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    name: str = "my_func",
    kind: NodeKind = NodeKind.FUNCTION,
    filepath: str = "src/foo.py",
    source_text: str = "def my_func(): pass",
    docstring: str | None = "Does stuff.",
    signature: str | None = "def my_func()",
) -> ASTNode:
    return ASTNode(
        id=f"repo:{filepath}:{kind.value}:{name}",
        kind=kind,
        name=name,
        filepath=filepath,
        start_line=1,
        end_line=3,
        source_text=source_text,
        docstring=docstring,
        signature=signature,
    )


@dataclass
class _FakeEmbeddingItem:
    embedding: list[float]


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeEmbeddingItem]


def _make_embedding(dims: int = 512) -> list[float]:
    return [0.1] * dims


# ---------------------------------------------------------------------------
# 5.1: EmbeddingService init
# ---------------------------------------------------------------------------

class TestEmbeddingServiceInit:
    def test_default_config(self):
        svc = EmbeddingService(api_key="test-key")
        assert svc.model == "openai/text-embedding-3-small"
        assert svc.dimensions == 512

    def test_custom_config(self):
        svc = EmbeddingService(api_key="k", model="custom/model", dimensions=1536)
        assert svc.model == "custom/model"
        assert svc.dimensions == 1536


# ---------------------------------------------------------------------------
# 5.2: build_embedding_text
# ---------------------------------------------------------------------------

class TestBuildEmbeddingText:
    def test_includes_name_and_kind(self):
        svc = EmbeddingService(api_key="test-key")
        node = _make_node(name="calculate", kind=NodeKind.FUNCTION)
        text = svc.build_embedding_text(node)
        assert "function: calculate" in text

    def test_includes_signature(self):
        svc = EmbeddingService(api_key="test-key")
        node = _make_node(signature="def calculate(x, y)")
        text = svc.build_embedding_text(node)
        assert "signature: def calculate(x, y)" in text

    def test_includes_docstring(self):
        svc = EmbeddingService(api_key="test-key")
        node = _make_node(docstring="Computes the sum")
        text = svc.build_embedding_text(node)
        assert "docstring: Computes the sum" in text

    def test_includes_source(self):
        svc = EmbeddingService(api_key="test-key")
        node = _make_node(source_text="def foo(): return 42")
        text = svc.build_embedding_text(node)
        assert "source: def foo(): return 42" in text

    def test_truncates_long_source(self):
        svc = EmbeddingService(api_key="test-key")
        # Create a very long source text (well over 512 tokens)
        long_source = "x = 1\n" * 2000
        node = _make_node(source_text=long_source)
        text = svc.build_embedding_text(node)
        # The source portion should be truncated
        source_line = [l for l in text.split("\n") if l.startswith("source:")][0]
        # Verify it's shorter than the original
        assert len(source_line) < len(long_source)

    def test_handles_none_optional_fields(self):
        svc = EmbeddingService(api_key="test-key")
        node = _make_node(docstring=None, signature=None)
        text = svc.build_embedding_text(node)
        assert "docstring:" not in text
        assert "signature:" not in text
        assert "function: my_func" in text


# ---------------------------------------------------------------------------
# 5.4: Dimension validation
# ---------------------------------------------------------------------------

class TestDimensionValidation:
    def test_valid_dimensions(self):
        svc = EmbeddingService(api_key="test-key", dimensions=512)
        assert svc.validate_dimensions([0.0] * 512) is True

    def test_invalid_dimensions_too_short(self):
        svc = EmbeddingService(api_key="test-key", dimensions=512)
        assert svc.validate_dimensions([0.0] * 256) is False

    def test_invalid_dimensions_too_long(self):
        svc = EmbeddingService(api_key="test-key", dimensions=512)
        assert svc.validate_dimensions([0.0] * 1024) is False

    def test_empty_embedding_rejected(self):
        svc = EmbeddingService(api_key="test-key", dimensions=512)
        assert svc.validate_dimensions([]) is False


# ---------------------------------------------------------------------------
# 5.1 / 5.3: encode and encode_batch with mocked API
# ---------------------------------------------------------------------------

class TestEncode:
    @pytest.mark.asyncio
    async def test_encode_returns_embedding(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)
        mock_response = _FakeEmbeddingResponse(
            data=[_FakeEmbeddingItem(embedding=[0.1, 0.2, 0.3])]
        )
        svc._client.embeddings.create = AsyncMock(return_value=mock_response)

        result = await svc.encode("hello world")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_encode_rejects_wrong_dimensions(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)
        mock_response = _FakeEmbeddingResponse(
            data=[_FakeEmbeddingItem(embedding=[0.1, 0.2])]  # wrong dims
        )
        svc._client.embeddings.create = AsyncMock(return_value=mock_response)

        with pytest.raises(ValueError, match="dimensions"):
            await svc.encode("hello")


class TestEncodeBatch:
    @pytest.mark.asyncio
    async def test_batch_returns_all_embeddings(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)
        mock_response = _FakeEmbeddingResponse(
            data=[
                _FakeEmbeddingItem(embedding=[0.1, 0.2, 0.3]),
                _FakeEmbeddingItem(embedding=[0.4, 0.5, 0.6]),
            ]
        )
        svc._client.embeddings.create = AsyncMock(return_value=mock_response)

        results = await svc.encode_batch(["text1", "text2"], batch_size=10)
        assert len(results) == 2
        assert results[0] == [0.1, 0.2, 0.3]
        assert results[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_batch_splits_into_chunks(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            texts = kwargs["input"]
            return _FakeEmbeddingResponse(
                data=[_FakeEmbeddingItem(embedding=[0.1, 0.2, 0.3]) for _ in texts]
            )

        svc._client.embeddings.create = mock_create  # type: ignore[assignment]

        results = await svc.encode_batch(["a", "b", "c", "d", "e"], batch_size=2)
        assert len(results) == 5
        assert call_count == 3  # 2+2+1

    @pytest.mark.asyncio
    async def test_batch_validates_dimensions(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)
        mock_response = _FakeEmbeddingResponse(
            data=[_FakeEmbeddingItem(embedding=[0.1, 0.2])]  # wrong dims
        )
        svc._client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch("xce.embedding_service.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="dimensions"):
                await svc.encode_batch(["text1"], batch_size=10)


# ---------------------------------------------------------------------------
# 5.3: Rate limit retry behavior
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("rate limited")
            texts = kwargs["input"]
            return _FakeEmbeddingResponse(
                data=[_FakeEmbeddingItem(embedding=[0.1, 0.2, 0.3]) for _ in texts]
            )

        svc._client.embeddings.create = mock_create  # type: ignore[assignment]

        with patch("xce.embedding_service.asyncio.sleep", new_callable=AsyncMock):
            results = await svc.encode_batch(["hello"], batch_size=10)

        assert len(results) == 1
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_exhausted_retries(self):
        svc = EmbeddingService(api_key="test-key", dimensions=3)

        svc._client.embeddings.create = AsyncMock(side_effect=Exception("always fails"))

        with patch("xce.embedding_service.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="always fails"):
                await svc.encode_batch(["hello"], batch_size=10)
