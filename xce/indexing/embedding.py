"""Embedding service using OpenRouter API or AWS Bedrock.

Generates vector embeddings for AST nodes for semantic search.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_S = 2.0


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def encode(self, text: str) -> list[float]:
        """Encode a single text string into an embedding vector."""
        pass

    @abstractmethod
    async def encode_batch(self, texts: list[str], *, batch_size: int = 100) -> list[list[float]]:
        """Batch encode texts into embedding vectors."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the underlying client."""
        pass


class OpenRouterProvider(EmbeddingProvider):
    """Generate embeddings via OpenRouter embedding API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/text-embedding-3-small",
        dimensions: int = 512,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        from openai import AsyncOpenAI
        self.model = model
        self.dimensions = dimensions
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def validate_dimensions(self, embedding: list[float]) -> bool:
        return len(embedding) == self.dimensions

    async def encode(self, text: str) -> list[float]:
        from openai import AsyncOpenAI
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

    async def encode_batch(self, texts: list[str], *, batch_size: int = 100) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._encode_batch_with_retry(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def _encode_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await self._client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self.dimensions,
                )
                embeddings = [item.embedding for item in result.data]
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
        raise RuntimeError("Exhausted retries")

    async def close(self) -> None:
        await self._client.close()


class AWSBedrockProvider(EmbeddingProvider):
    """Generate embeddings via AWS Bedrock (Titan or Cohere)."""

    def __init__(
        self,
        *,
        model: str = "amazon.titan-embed-text-v1",
        dimensions: int = 1536,
        region: str = "us-east-1",
    ) -> None:
        import boto3
        self.model = model
        self.dimensions = dimensions
        self.region = region
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def validate_dimensions(self, embedding: list[float]) -> bool:
        return len(embedding) == self.dimensions

    async def encode(self, text: str) -> list[float]:
        return (await self.encode_batch([text]))[0]

    async def encode_batch(self, texts: list[str], *, batch_size: int = 100) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            
            for attempt in range(MAX_RETRIES + 1):
                try:
                    embeddings = []
                    for text in batch:
                        emb = await self._call_bedrock(text)
                        embeddings.append(emb)
                    all_embeddings.extend(embeddings)
                    break
                except Exception as exc:
                    if attempt < MAX_RETRIES:
                        delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "Bedrock embedding failed (%s), retrying in %.1fs (attempt %d/%d)",
                            exc, delay, attempt + 1, MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise
        
        return all_embeddings

    async def _call_bedrock(self, text: str) -> list[float]:
        import json
        
        # Different models have different input formats
        if "titan" in self.model:
            body = json.dumps({
                "inputText": text
            })
            content_type = "application/json"
            embed_key = "embedding"
        elif "cohere" in self.model:
            body = json.dumps({
                "texts": [text],
                "input_type": "search_document"
            })
            content_type = "application/json"
            embed_key = "embeddings"
        else:
            raise ValueError(f"Unsupported model: {self.model}")
        
        response = self._client.invoke_model(
            modelId=self.model,
            body=body,
            contentType=content_type,
            accept="application/json"
        )
        
        response_body = json.loads(response["body"].read())
        
        if "titan" in self.model:
            embedding = response_body[embed_key]
        else:
            embedding = response_body[embed_key][0]
        
        if not self.validate_dimensions(embedding):
            raise ValueError(
                f"Embedding has {len(embedding)} dimensions, expected {self.dimensions}"
            )
        
        return embedding

    async def close(self) -> None:
        pass  # boto3 client doesn't need explicit closing


class EmbeddingService:
    """Generate embeddings using configured provider (AWS Bedrock or OpenRouter)."""

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
        
        # Check if AWS credentials are available
        aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        aws_region = os.environ.get("AWS_REGION", "us-east-1")
        
        # Use AWS Bedrock if credentials are available and model is a Bedrock model
        if aws_access_key and aws_secret and ("bedrock" in model.lower() or "titan" in model.lower() or "cohere" in model.lower()):
            logger.info(f"Using AWS Bedrock for embeddings with model: {model}")
            self._provider = AWSBedrockProvider(
                model=model,
                dimensions=dimensions,
                region=aws_region,
            )
        elif aws_access_key and aws_secret:
            # Default to Bedrock Titan if AWS credentials are available
            titan_model = "amazon.titan-embed-text-v1"
            logger.info(f"Using AWS Bedrock Titan for embeddings (default)")
            self._provider = AWSBedrockProvider(
                model=titan_model,
                dimensions=1536,
                region=aws_region,
            )
            self.dimensions = 1536
            self.model = titan_model
        else:
            logger.info(f"Using OpenRouter for embeddings with model: {model}")
            self._provider = OpenRouterProvider(
                api_key=api_key,
                model=model,
                dimensions=dimensions,
                base_url=base_url,
            )
        
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # 5.2  build_embedding_text
    # ------------------------------------------------------------------

    def build_embedding_text(self, node) -> str:
        """Construct text for embedding from node metadata."""
        from xce.models import ASTNode
        
        parts: list[str] = [
            f"{node.kind.value}: {node.name}",
        ]
        if node.signature:
            parts.append(f"signature: {node.signature}")
        if node.docstring:
            parts.append(f"docstring: {node.docstring}")

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
        return await self._provider.encode(text)

    # ------------------------------------------------------------------
    # 5.3  encode_batch — with rate limiting and exponential backoff
    # ------------------------------------------------------------------

    async def encode_batch(
        self, texts: list[str], *, batch_size: int = 100,
    ) -> list[list[float]]:
        """Batch encode texts via configured provider."""
        return await self._provider.encode_batch(texts, batch_size=batch_size)

    async def close(self) -> None:
        """Close the underlying client."""
        await self._provider.close()