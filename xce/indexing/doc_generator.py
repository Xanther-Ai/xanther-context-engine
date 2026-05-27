"""Documentation generator using LLM via OpenRouter API.

Generates ComponentDescription, LLDDocument, and HLDDocument from AST
nodes by prompting an LLM and parsing structured JSON responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from xce.models import (
    ASTNode,
    ComponentDescription,
    HLDDocument,
    LLDDocument,
)

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_S = 2.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class DocGenerator:
    """Generate documentation for AST nodes via an LLM (OpenRouter API)."""

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
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    # ------------------------------------------------------------------
    # 4.7  LLM call with retry logic
    # ------------------------------------------------------------------

    async def _llm_call(self, messages: list[dict[str, str]]) -> dict[str, Any] | None:
        """Send a chat completion request with exponential backoff retry.

        Returns the parsed JSON content on success, or ``None`` after all
        retries are exhausted.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                    },
                )
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < MAX_RETRIES:
                        delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "LLM returned %s, retrying in %.1fs (attempt %d/%d)",
                            response.status_code, delay, attempt + 1, MAX_RETRIES,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error("LLM returned %s after %d retries", response.status_code, MAX_RETRIES)
                    return None

                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)

            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as exc:
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
    # 4.3  generate_component_desc
    # ------------------------------------------------------------------

    @staticmethod
    def _build_component_prompt(node: ASTNode, context_nodes: list[ASTNode]) -> list[dict[str, str]]:
        """Build the prompt messages for component description generation."""
        context_text = ""
        if context_nodes:
            snippets = [f"- {cn.kind.value} `{cn.name}`: {cn.docstring or cn.source_text[:200]}"
                        for cn in context_nodes[:5]]
            context_text = "\n\nRelated code elements:\n" + "\n".join(snippets)

        return [
            {
                "role": "system",
                "content": (
                    "You are a code documentation expert. Respond ONLY with valid JSON "
                    "matching this schema: {\"summary\": \"string\", "
                    "\"responsibilities\": [\"string\"], \"dependencies\": [\"string\"]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate a component description for this {node.kind.value} "
                    f"named `{node.name}`:\n\n```python\n{node.source_text}\n```"
                    f"{context_text}"
                ),
            },
        ]

    async def generate_component_desc(
        self, node: ASTNode, context_nodes: list[ASTNode] | None = None,
    ) -> ComponentDescription:
        """Generate a component-level description for an AST node.

        On LLM failure after retries, returns a description with
        ``summary="doc_pending"``.
        """
        messages = self._build_component_prompt(node, context_nodes or [])
        result = await self._llm_call(messages)

        if result is None:
            logger.warning("Marking node %s as doc_pending", node.id)
            return ComponentDescription(
                node_id=node.id,
                summary="doc_pending",
            )

        return ComponentDescription(
            node_id=node.id,
            summary=result.get("summary", ""),
            responsibilities=result.get("responsibilities", []),
            dependencies=result.get("dependencies", []),
        )

    # ------------------------------------------------------------------
    # 4.4  generate_lld
    # ------------------------------------------------------------------

    @staticmethod
    def _build_lld_prompt(
        node: ASTNode, desc: ComponentDescription, callees: list[ASTNode],
    ) -> list[dict[str, str]]:
        """Build the prompt messages for LLD generation."""
        callee_text = ""
        if callees:
            snippets = [f"- `{c.name}` ({c.kind.value}): {c.docstring or c.source_text[:150]}"
                        for c in callees[:5]]
            callee_text = "\n\nFunctions/methods this code calls:\n" + "\n".join(snippets)

        return [
            {
                "role": "system",
                "content": (
                    "You are a code documentation expert. Respond ONLY with valid JSON "
                    "matching this schema: {\"algorithm_description\": \"string\", "
                    "\"data_flow\": \"string\", \"error_handling\": \"string\", "
                    "\"edge_cases\": [\"string\"]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate a low-level design document for `{node.name}`.\n\n"
                    f"Component summary: {desc.summary}\n\n"
                    f"Source code:\n```python\n{node.source_text}\n```"
                    f"{callee_text}"
                ),
            },
        ]

    async def generate_lld(
        self, node: ASTNode, desc: ComponentDescription, callees: list[ASTNode] | None = None,
    ) -> LLDDocument:
        """Generate a low-level design document for a function/method.

        On LLM failure, returns an LLD with ``algorithm_description="doc_pending"``.
        """
        messages = self._build_lld_prompt(node, desc, callees or [])
        result = await self._llm_call(messages)

        if result is None:
            logger.warning("Marking LLD for %s as doc_pending", node.id)
            return LLDDocument(
                component_id=node.id,
                algorithm_description="doc_pending",
                data_flow="",
                error_handling="",
            )

        return LLDDocument(
            component_id=node.id,
            algorithm_description=result.get("algorithm_description", ""),
            data_flow=result.get("data_flow", ""),
            error_handling=result.get("error_handling", ""),
            edge_cases=result.get("edge_cases", []),
        )

    # ------------------------------------------------------------------
    # 4.5  generate_hld
    # ------------------------------------------------------------------

    @staticmethod
    def _build_hld_prompt(
        module_nodes: list[ASTNode], descs: list[ComponentDescription],
    ) -> list[dict[str, str]]:
        """Build the prompt messages for HLD generation."""
        desc_map = {d.node_id: d for d in descs}
        items: list[str] = []
        for n in module_nodes[:20]:
            d = desc_map.get(n.id)
            summary = d.summary if d else (n.docstring or "")
            items.append(f"- {n.kind.value} `{n.name}`: {summary}")

        module_path = module_nodes[0].filepath.rsplit("/", 1)[0] if "/" in module_nodes[0].filepath else "."

        return [
            {
                "role": "system",
                "content": (
                    "You are a software architect. Respond ONLY with valid JSON "
                    "matching this schema: {\"architectural_role\": \"string\", "
                    "\"design_patterns\": [\"string\"], \"integration_points\": [\"string\"], "
                    "\"quality_attributes\": [\"string\"]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate a high-level design document for the module at `{module_path}`.\n\n"
                    f"Components in this module:\n" + "\n".join(items)
                ),
            },
        ]

    async def generate_hld(
        self, module_nodes: list[ASTNode], descs: list[ComponentDescription],
    ) -> HLDDocument:
        """Generate a high-level design document for a module/package.

        On LLM failure, returns an HLD with ``architectural_role="doc_pending"``.
        """
        if not module_nodes:
            return HLDDocument(module_path="", architectural_role="doc_pending")

        module_path = module_nodes[0].filepath.rsplit("/", 1)[0] if "/" in module_nodes[0].filepath else "."
        messages = self._build_hld_prompt(module_nodes, descs)
        result = await self._llm_call(messages)

        if result is None:
            logger.warning("Marking HLD for %s as doc_pending", module_path)
            return HLDDocument(
                module_path=module_path,
                architectural_role="doc_pending",
            )

        return HLDDocument(
            module_path=module_path,
            architectural_role=result.get("architectural_role", ""),
            design_patterns=result.get("design_patterns", []),
            integration_points=result.get("integration_points", []),
            quality_attributes=result.get("quality_attributes", []),
        )

    # ------------------------------------------------------------------
    # 4.6  generate_batch
    # ------------------------------------------------------------------

    async def generate_batch(self, nodes: list[ASTNode]) -> list[ComponentDescription]:
        """Batch-generate component descriptions for a list of nodes.

        Nodes are grouped into batches of ``self.batch_size`` and sent as
        a single LLM call per batch. On failure, individual nodes in the
        batch are marked ``doc_pending``.
        """
        all_descs: list[ComponentDescription] = []

        for i in range(0, len(nodes), self.batch_size):
            batch = nodes[i : i + self.batch_size]
            descs = await self._generate_batch_single(batch)
            all_descs.extend(descs)

        return all_descs

    async def _generate_batch_single(self, batch: list[ASTNode]) -> list[ComponentDescription]:
        """Generate descriptions for a single batch via one LLM call."""
        items: list[str] = []
        for idx, node in enumerate(batch):
            items.append(
                f"[{idx}] {node.kind.value} `{node.name}`:\n"
                f"```python\n{node.source_text[:500]}\n```"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code documentation expert. You will receive multiple code "
                    "elements. Respond ONLY with valid JSON: {\"descriptions\": ["
                    "{\"index\": 0, \"summary\": \"string\", "
                    "\"responsibilities\": [\"string\"], \"dependencies\": [\"string\"]}, ...]}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate component descriptions for each of these code elements:\n\n"
                    + "\n\n".join(items)
                ),
            },
        ]

        result = await self._llm_call(messages)

        if result is None:
            return [
                ComponentDescription(node_id=n.id, summary="doc_pending")
                for n in batch
            ]

        desc_list = result.get("descriptions", [])
        desc_by_idx: dict[int, dict[str, Any]] = {}
        for d in desc_list:
            idx = d.get("index")
            if idx is not None:
                desc_by_idx[int(idx)] = d

        descs: list[ComponentDescription] = []
        for idx, node in enumerate(batch):
            d = desc_by_idx.get(idx)
            if d:
                descs.append(ComponentDescription(
                    node_id=node.id,
                    summary=d.get("summary", ""),
                    responsibilities=d.get("responsibilities", []),
                    dependencies=d.get("dependencies", []),
                ))
            else:
                descs.append(ComponentDescription(
                    node_id=node.id,
                    summary="doc_pending",
                ))

        return descs

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
