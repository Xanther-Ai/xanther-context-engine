"""Unit tests for xce.doc_generator.DocGenerator.

All LLM API calls are mocked. Tests verify:
- Prompt construction (4.3, 4.4, 4.5)
- Batch grouping (4.6)
- Retry behavior with exponential backoff (4.7)
- "doc_pending" marking on exhausted retries (4.7)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from xce.indexing.doc_generator import DocGenerator, MAX_RETRIES, BASE_DELAY_S
from xce.models import ASTNode, ComponentDescription, ArchitectureDoc, ComponentDoc, NodeKind


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


def _mock_response(json_body: dict, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response wrapping a chat completion."""
    content = json.dumps(json_body)
    payload = {
        "choices": [{"message": {"content": content}}],
    }
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://example.com"),
    )


def _mock_error_response(status_code: int = 429) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text="rate limited",
        request=httpx.Request("POST", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# 4.2: __init__
# ---------------------------------------------------------------------------

class TestDocGeneratorInit:
    def test_default_config(self):
        gen = DocGenerator(api_key="test-key")
        assert gen.api_key == "test-key"
        assert gen.batch_size == 10
        assert gen.model == "openai/gpt-4o-mini"

    def test_custom_config(self):
        gen = DocGenerator(api_key="k", model="custom/model", batch_size=5)
        assert gen.model == "custom/model"
        assert gen.batch_size == 5


# ---------------------------------------------------------------------------
# 4.3: generate_component_desc — prompt construction
# ---------------------------------------------------------------------------

class TestGenerateComponentDesc:
    @pytest.mark.asyncio
    async def test_prompt_includes_source_and_name(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node(name="calculate", source_text="def calculate(x): return x * 2")

        captured_messages = []

        async def mock_post(url, **kwargs):
            captured_messages.append(kwargs["json"]["messages"])
            return _mock_response({
                "summary": "Doubles input",
                "responsibilities": ["compute"],
                "dependencies": [],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        desc = await gen.generate_component_desc(node)
        assert desc.summary == "Doubles input"
        assert desc.node_id == node.id

        # Verify prompt content
        user_msg = captured_messages[0][1]["content"]
        assert "calculate" in user_msg
        assert "def calculate(x): return x * 2" in user_msg

    @pytest.mark.asyncio
    async def test_prompt_includes_context_nodes(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node(name="main_func")
        ctx = [_make_node(name="helper", docstring="Helps with things")]

        captured_messages = []

        async def mock_post(url, **kwargs):
            captured_messages.append(kwargs["json"]["messages"])
            return _mock_response({
                "summary": "Main function",
                "responsibilities": [],
                "dependencies": ["helper"],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        desc = await gen.generate_component_desc(node, context_nodes=ctx)
        user_msg = captured_messages[0][1]["content"]
        assert "helper" in user_msg
        assert "Helps with things" in user_msg

    @pytest.mark.asyncio
    async def test_returns_component_description(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node()

        async def mock_post(url, **kwargs):
            return _mock_response({
                "summary": "A function",
                "responsibilities": ["compute", "validate"],
                "dependencies": ["os"],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        desc = await gen.generate_component_desc(node)
        assert isinstance(desc, ComponentDescription)
        assert desc.summary == "A function"
        assert desc.responsibilities == ["compute", "validate"]
        assert desc.dependencies == ["os"]



# ---------------------------------------------------------------------------
# 4.4: generate_component — prompt construction
# ---------------------------------------------------------------------------

class TestGenerateComponent:
    @pytest.mark.asyncio
    async def test_prompt_includes_source_and_desc(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node(name="process", source_text="def process(data): return sorted(data)")
        desc = ComponentDescription(node_id=node.id, summary="Processes data")

        captured_messages = []

        async def mock_post(url, **kwargs):
            captured_messages.append(kwargs["json"]["messages"])
            return _mock_response({
                "algorithm_description": "Sorts input",
                "data_flow": "data in -> sorted out",
                "error_handling": "none",
                "edge_cases": ["empty list"],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        lld = await gen.generate_component(node, desc)
        assert isinstance(lld, ComponentDoc)
        assert lld.algorithm_description == "Sorts input"
        assert lld.component_id == node.id

        user_msg = captured_messages[0][1]["content"]
        assert "process" in user_msg
        assert "Processes data" in user_msg

    @pytest.mark.asyncio
    async def test_prompt_includes_callees(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node(name="caller")
        desc = ComponentDescription(node_id=node.id, summary="Calls things")
        callees = [_make_node(name="helper_fn", docstring="A helper")]

        captured_messages = []

        async def mock_post(url, **kwargs):
            captured_messages.append(kwargs["json"]["messages"])
            return _mock_response({
                "algorithm_description": "Delegates",
                "data_flow": "in -> helper -> out",
                "error_handling": "propagates",
                "edge_cases": [],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        await gen.generate_component(node, desc, callees=callees)
        user_msg = captured_messages[0][1]["content"]
        assert "helper_fn" in user_msg


# ---------------------------------------------------------------------------
# 4.5: generate_architecture — prompt construction
# ---------------------------------------------------------------------------

class TestGenerateArchitecture:
    @pytest.mark.asyncio
    async def test_prompt_includes_module_nodes(self):
        gen = DocGenerator(api_key="test-key")
        nodes = [
            _make_node(name="view_func", filepath="src/views/main.py"),
            _make_node(name="ViewClass", kind=NodeKind.CLASS, filepath="src/views/main.py"),
        ]
        descs = [
            ComponentDescription(node_id=nodes[0].id, summary="Handles requests"),
            ComponentDescription(node_id=nodes[1].id, summary="View class"),
        ]

        captured_messages = []

        async def mock_post(url, **kwargs):
            captured_messages.append(kwargs["json"]["messages"])
            return _mock_response({
                "architectural_role": "controller",
                "design_patterns": ["MVC"],
                "integration_points": ["REST API"],
                "quality_attributes": ["testable"],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        hld = await gen.generate_architecture(nodes, descs)
        assert isinstance(hld, ArchitectureDoc)
        assert hld.module_path == "src/views"
        assert hld.architectural_role == "controller"

        user_msg = captured_messages[0][1]["content"]
        assert "view_func" in user_msg
        assert "ViewClass" in user_msg

    @pytest.mark.asyncio
    async def test_empty_nodes_returns_pending(self):
        gen = DocGenerator(api_key="test-key")
        hld = await gen.generate_architecture([], [])
        assert hld.architectural_role == "doc_pending"


# ---------------------------------------------------------------------------
# 4.6: generate_batch — batch grouping
# ---------------------------------------------------------------------------

class TestGenerateBatch:
    @pytest.mark.asyncio
    async def test_batch_groups_nodes(self):
        gen = DocGenerator(api_key="test-key", batch_size=2)
        nodes = [_make_node(name=f"func_{i}") for i in range(5)]

        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            msgs = kwargs["json"]["messages"]
            user_msg = msgs[1]["content"]
            # Count how many [idx] markers are in the prompt
            indices = [i for i in range(10) if f"[{i}]" in user_msg]
            descs = [
                {"index": idx, "summary": f"desc_{idx}", "responsibilities": [], "dependencies": []}
                for idx in indices
            ]
            return _mock_response({"descriptions": descs})

        gen._client.post = mock_post  # type: ignore[assignment]

        results = await gen.generate_batch(nodes)
        assert len(results) == 5
        # With batch_size=2, 5 nodes → 3 batches (2+2+1)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_batch_returns_correct_descriptions(self):
        gen = DocGenerator(api_key="test-key", batch_size=10)
        nodes = [_make_node(name="alpha"), _make_node(name="beta")]

        async def mock_post(url, **kwargs):
            return _mock_response({
                "descriptions": [
                    {"index": 0, "summary": "Alpha desc", "responsibilities": ["a"], "dependencies": []},
                    {"index": 1, "summary": "Beta desc", "responsibilities": ["b"], "dependencies": []},
                ]
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        results = await gen.generate_batch(nodes)
        assert results[0].summary == "Alpha desc"
        assert results[1].summary == "Beta desc"


# ---------------------------------------------------------------------------
# 4.7: Retry behavior and doc_pending marking
# ---------------------------------------------------------------------------

class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node()

        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _mock_error_response(429)
            return _mock_response({
                "summary": "Success after retry",
                "responsibilities": [],
                "dependencies": [],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        # Patch sleep to avoid actual delays
        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            desc = await gen.generate_component_desc(node)

        assert desc.summary == "Success after retry"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node()

        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return _mock_error_response(500)
            return _mock_response({
                "summary": "Recovered",
                "responsibilities": [],
                "dependencies": [],
            })

        gen._client.post = mock_post  # type: ignore[assignment]

        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            desc = await gen.generate_component_desc(node)

        assert desc.summary == "Recovered"

    @pytest.mark.asyncio
    async def test_doc_pending_on_exhausted_retries(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node()

        async def mock_post(url, **kwargs):
            return _mock_error_response(429)

        gen._client.post = mock_post  # type: ignore[assignment]

        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            desc = await gen.generate_component_desc(node)

        assert desc.summary == "doc_pending"
        assert desc.node_id == node.id

    @pytest.mark.asyncio
    async def test_doc_pending_on_batch_failure(self):
        gen = DocGenerator(api_key="test-key", batch_size=10)
        nodes = [_make_node(name="a"), _make_node(name="b")]

        async def mock_post(url, **kwargs):
            return _mock_error_response(500)

        gen._client.post = mock_post  # type: ignore[assignment]

        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            results = await gen.generate_batch(nodes)

        assert all(d.summary == "doc_pending" for d in results)

    @pytest.mark.asyncio
    async def test_lld_doc_pending_on_failure(self):
        gen = DocGenerator(api_key="test-key")
        node = _make_node()
        desc = ComponentDescription(node_id=node.id, summary="test")

        async def mock_post(url, **kwargs):
            return _mock_error_response(503)

        gen._client.post = mock_post  # type: ignore[assignment]

        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            lld = await gen.generate_component(node, desc)

        assert lld.algorithm_description == "doc_pending"

    @pytest.mark.asyncio
    async def test_hld_doc_pending_on_failure(self):
        gen = DocGenerator(api_key="test-key")
        nodes = [_make_node(filepath="src/mod.py")]

        async def mock_post(url, **kwargs):
            return _mock_error_response(502)

        gen._client.post = mock_post  # type: ignore[assignment]

        with patch("xce.indexing.doc_generator.asyncio.sleep", new_callable=AsyncMock):
            hld = await gen.generate_architecture(nodes, [])

        assert hld.architectural_role == "doc_pending"
