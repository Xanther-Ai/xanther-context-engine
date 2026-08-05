"""Documentation generator using LLM via AWS Bedrock or OpenRouter API.

Generates ComponentDescription, ComponentDoc, and ArchitectureDoc from AST
nodes by prompting an LLM and parsing structured JSON responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import Any

import httpx

from xce.models import (
    ASTNode,
    ArchitectureDoc,
    ComponentDescription,
    ComponentDoc,
)

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_S = 2.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> dict[str, Any]:
        """Send a chat completion request and return parsed JSON."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the underlying client."""
        pass


class OpenRouterProvider(LLMProvider):
    """Generate documentation via OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/gpt-4o-mini",
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> dict[str, Any]:
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    async def close(self) -> None:
        await self._client.aclose()


class AWSBedrockProvider(LLMProvider):
    """Generate documentation via AWS Bedrock (DeepSeek, Kimi, Claude, Llama, etc.)."""

    def __init__(
        self,
        *,
        model: str = "deepseek.v3.2",
        region: str = "us-east-1",
    ) -> None:
        import boto3
        self.model = model
        self.region = region
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> dict[str, Any]:
        import json
        
        # Different payload for different model families
        if "deepseek" in self.model:
            # DeepSeek V3 format (OpenAI-compatible)
            body = {
                "messages": messages,
                "max_tokens": 4096,
                "temperature": temperature,
            }
        elif "kimi" in self.model:
            # Kimi format
            body = {
                "messages": messages,
                "max_tokens": 4096,
                "temperature": temperature,
            }
        elif "claude" in self.model:
            # Anthropic Claude format
            system_message = ""
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    anthropic_messages.append({"role": msg["role"], "content": msg["content"]})
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": anthropic_messages,
                "system": system_message,
                "temperature": temperature,
            }
        elif "llama" in self.model:
            # Llama format
            system_message = ""
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    anthropic_messages.append({"role": msg["role"], "content": msg["content"]})
            prompt = f"System: {system_message}\n\n" + "\n\n".join([
                f"Human: {m['content']}" if m["role"] == "user" else f"Assistant: {m['content']}"
                for m in anthropic_messages
            ])
            body = {
                "prompt": prompt,
                "max_gen_len": 4096,
                "temperature": temperature,
            }
        else:
            # Default format (OpenAI-compatible)
            body = {
                "messages": messages,
                "max_tokens": 4096,
                "temperature": temperature,
            }
        
        response = self._client.invoke_model(
            modelId=self.model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
        
        response_body = json.loads(response["body"].read())
        
        # Parse response based on model
        if "deepseek" in self.model:
            content = response_body["choices"][0]["message"]["content"]
        elif "kimi" in self.model:
            content = response_body["choices"][0]["message"]["content"]
        elif "claude" in self.model:
            content = response_body["content"][0]["text"]
        elif "llama" in self.model:
            content = response_body["generation"]
        else:
            content = response_body.get("message", {}).get("content", str(response_body))
        
        # Try to parse content as JSON (if it's a JSON string)
        # If it's not JSON, return it as-is
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Content is not JSON - return it wrapped
            return {"content": content}

    async def close(self) -> None:
        pass  # boto3 client doesn't need explicit closing


class DocGenerator:
    """Generate documentation for AST nodes via an LLM (AWS Bedrock or OpenRouter)."""

    # ------------------------------------------------------------------
    # 4.2  __init__
    # ------------------------------------------------------------------

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/gpt-4o-mini",
        batch_size: int = 10,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size
        
        # Check if AWS credentials are available
        aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
        aws_region = os.environ.get("AWS_REGION", "us-east-1")
        
        # Use AWS Bedrock if credentials are available
        if aws_access_key and aws_secret:
            # Default to DeepSeek V3 for cheaper generation
            bedrock_model = "deepseek.v3.2"
            logger.info(f"Using AWS Bedrock for doc generation with model: {bedrock_model}")
            self._provider = AWSBedrockProvider(
                model=bedrock_model,
                region=aws_region,
            )
            self.model = bedrock_model
        else:
            logger.info(f"Using OpenRouter for doc generation with model: {model}")
            self._provider = OpenRouterProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
            )

    # ------------------------------------------------------------------
    # 4.7  LLM call with retry logic
    # ------------------------------------------------------------------

    async def _llm_call(self, messages: list[dict[str, str]]) -> dict[str, Any] | None:
        """Send a chat completion request with exponential backoff retry."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await self._provider.chat(messages)
                return result

            except Exception as exc:
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "LLM call failed (%s), retrying in %.1fs (attempt %d/%d)",
                        exc, delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after %d retries: %s", MAX_RETRIES, exc)
                    return None

        return None

    # ------------------------------------------------------------------
    # 4.3  build_component_description_prompt
    # ------------------------------------------------------------------

    def _build_component_description_prompt(self, node: ASTNode) -> list[dict[str, str]]:
        prompt = f"""You are a code analyst. Analyze this AST node and provide a JSON description.

AST Node:
- Name: {node.name}
- Kind: {node.kind.value}
- File: {node.filepath}
- Signature: {node.signature or 'N/A'}
- Docstring: {node.docstring or 'N/A'}
- Source (truncated): {node.source_text[:500] if node.source_text else 'N/A'}

Respond with a JSON object containing:
{{
  "summary": "A one-sentence summary of what this component does",
  "responsibilities": ["list", "of", "key", "responsibilities"],
  "dependencies": ["list", "of", "dependencies", "or", "imports"]
}}
"""
        return [{"role": "user", "content": prompt}]

    # ------------------------------------------------------------------
    # 4.4  generate_component_description
    # ------------------------------------------------------------------

    async def generate_component_description(
        self,
        node: ASTNode,
    ) -> ComponentDescription | None:
        """Generate ComponentDescription for a single AST node."""
        messages = self._build_component_description_prompt(node)
        result = await self._llm_call(messages)

        if result is None:
            return None

        return ComponentDescription(
            node_id=node.id,
            summary=result.get("summary", ""),
            responsibilities=result.get("responsibilities", []),
            dependencies=result.get("dependencies", []),
        )

    # ------------------------------------------------------------------
    # 4.5  generate_component_doc
    # ------------------------------------------------------------------

    async def generate_component_doc(
        self,
        component: ComponentDescription,
        source_code: str,
    ) -> ComponentDoc | None:
        prompt = f"""You are a code analyst. Generate detailed documentation for this component.

Component Summary: {component.summary}
Responsibilities: {", ".join(component.responsibilities)}
Dependencies: {", ".join(component.dependencies)}

Source Code:
{source_code[:2000]}

Respond with a JSON object containing:
{{
  "algorithm_description": "How this component works",
  "data_flow": "How data flows through this component",
  "error_handling": "How errors are handled",
  "edge_cases": ["list", "of", "edge", "cases", "to", "consider"]
}}
"""
        messages = [{"role": "user", "content": prompt}]
        result = await self._llm_call(messages)

        if result is None:
            return None

        return ComponentDoc(
            component_id=component.node_id,
            algorithm_description=result.get("algorithm_description", ""),
            data_flow=result.get("data_flow", ""),
            error_handling=result.get("error_handling", ""),
            edge_cases=result.get("edge_cases", []),
        )

    # ------------------------------------------------------------------
    # 4.6  generate_architecture_doc
    # ------------------------------------------------------------------

    async def generate_architecture_doc(
        self,
        module_path: str,
        components: list[ComponentDescription],
    ) -> ArchitectureDoc | None:
        prompt = f"""You are a software architect. Analyze this module and provide architecture documentation.

Module Path: {module_path}

Components in this module:
{chr(10).join(f"- {c.summary} ({c.node_id})" for c in components)}

Respond with a JSON object containing:
{{
  "architectural_role": "What role this module plays in the larger system",
  "design_patterns": ["list", "of", "design", "patterns", "used"],
  "integration_points": ["how", "this", "module", "integrates", "with", "others"],
  "quality_attributes": ["performance", "maintainability", "security", "etc"]
}}
"""
        messages = [{"role": "user", "content": prompt}]
        result = await self._llm_call(messages)

        if result is None:
            return None

        return ArchitectureDoc(
            module_path=module_path,
            architectural_role=result.get("architectural_role", ""),
            design_patterns=result.get("design_patterns", []),
            integration_points=result.get("integration_points", []),
            quality_attributes=result.get("quality_attributes", []),
        )

    # ------------------------------------------------------------------
    # 4.8  generate_all_descriptions
    # ------------------------------------------------------------------

    async def generate_all_descriptions(
        self,
        nodes: list[ASTNode],
    ) -> list[ComponentDescription]:
        """Generate ComponentDescriptions for all nodes in batch."""
        tasks = [self.generate_component_description(node) for node in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        descriptions = []
        for node, result in zip(nodes, results):
            if isinstance(result, Exception):
                logger.warning("Failed to generate description for %s: %s", node.id, result)
            elif result is not None:
                descriptions.append(result)

        return descriptions

    # ------------------------------------------------------------------
    # 4.9  generate_all_docs
    # ------------------------------------------------------------------

    async def generate_all_docs(
        self,
        components: list[ComponentDescription],
        source_by_id: dict[str, str],
    ) -> list[ComponentDoc]:
        """Generate ComponentDocs for all components in batch."""
        tasks = [
            self.generate_component_doc(comp, source_by_id.get(comp.node_id, ""))
            for comp in components
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        docs = []
        for comp, result in zip(components, results):
            if isinstance(result, Exception):
                logger.warning("Failed to generate doc for %s: %s", comp.node_id, result)
            elif result is not None:
                docs.append(result)

        return docs

    async def close(self) -> None:
        """Close the underlying client."""
        await self._provider.close()
# ------------------------------------------------------------------
    # 4.10  generate_batch (for indexer compatibility)
    # ------------------------------------------------------------------

    async def generate_batch(
        self,
        nodes: list[ASTNode],
    ) -> list[ComponentDescription]:
        """Generate ComponentDescriptions for a batch of nodes."""
        return await self.generate_all_descriptions(nodes)