"""Embedding service using OpenRouter API via the openai Python client.

Generates vector embeddings for AST nodes for semantic search.
"""

from __future__ import annotations

import asyncio
import logging
import random

import tiktoken
from openai import AsyncOpenAI

from xce.models import ASTNode

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_S = 2.0


class EmbeddingService:
    """Generate embeddings via OpenRouter embedding API."""

    # ------------------------------------------------------------------
    # 5.1  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/text-embedding-3-small",
        dimensions: int = 512,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # 5.2  build_embedding_text
    # ------------------------------------------------------------------

    def build_embedding_text(self, node: ASTNode) -> str:
        """Construct text for embedding from node metadata.

        Combines: node name, kind, signature, docstring, and truncated
        source (≤512 tokens).
        """
        parts: list[str] = [
            f"{node.kind.value}: {node.name}",
        ]
        if node.signature:
            parts.append(f"signature: {node.signature}")
        if node.docstring:
            parts.append(f"docstring: {node.docstring}")

        # Truncate source to ≤512 tokens
        source = node.source_text or ""
        tokens = self._tokenizer.encode(source)
        if len(tokens) > 512:
            source = self._tokenizer.decode(tokens[:512])
        parts.append(f"source: {source}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 5.4  validate_dimensions
    # ------------------------------------------------------------------

    def validate_dimensions(self, embedding: list[float]) -> bool:
        """Return True if embedding matches configured dimensions."""
        return len(embedding) == self.dimensions

    # ------------------------------------------------------------------
    # 5.1  encode (single text)
    # ------------------------------------------------------------------

    async def encode(self, text: str) -> list[float]:
        """Encode a single text string into an embedding vector."""
        result = await self._client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimensions,
        )
        embedding = result.data[0].embedding
        if not self.validate_dimensions(embedding):
            raise ValueError(
                f"Embedding has {len(embedding)} dimensions, expected {self.dimensions}"
            )
        return embedding

    # ------------------------------------------------------------------
    # 5.3  encode_batch — with rate limiting and exponential backoff
    # ------------------------------------------------------------------

    async def encode_batch(
        self, texts: list[str], *, batch_size: int = 100,
    ) -> list[list[float]]:
        """Batch encode texts via OpenRouter API.

        Handles rate limiting with exponential backoff and batching.
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._encode_batch_with_retry(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def _encode_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Encode a single batch with retry logic."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await self._client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self.dimensions,
                )
                embeddings = [item.embedding for item in result.data]

                # Validate all dimensions
                for idx, emb in enumerate(embeddings):
                    if not self.validate_dimensions(emb):
                        raise ValueError(
                            f"Embedding at index {idx} has {len(emb)} dimensions, "
                            f"expected {self.dimensions}"
                        )

                return embeddings

            except Exception as exc:
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Embedding batch failed (%s), retrying in %.1fs (attempt %d/%d)",
                        exc, delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        # Unreachable, but satisfies type checker
        raise RuntimeError("Exhausted retries")  # pragma: no cover

    async def close(self) -> None:
        """Close the underlying client."""
        await self._client.close()
