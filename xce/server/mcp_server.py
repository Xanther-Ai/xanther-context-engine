"""MCP Server for the Xanther Context Engine.

Exposes XCE tools via the Model Context Protocol.
Supports stdio (local) and SSE (remote via FastAPI) transport.

Run locally:  python -m xce.mcp_server
Run remote:   python -m xce.mcp_server --sse
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="xce_architecture_context",
        description="Get architectural context for a file or symbol",
        inputSchema={
            "type": "object",
            "properties": {
                "file_or_symbol": {"type": "string", "description": "File path or symbol name"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["file_or_symbol", "repo_id"],
        },
    ),
    Tool(
        name="xce_trace",
        description="Trace relationships between code and design artifacts",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source code symbol or file"},
                "target_level": {
                    "type": "string",
                    "enum": ["code", "component", "architecture"],
                    "description": "Target abstraction level",
                },
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["source", "target_level", "repo_id"],
        },
    ),
    Tool(
        name="xce_impact_analysis",
        description="Predict blast radius for proposed code changes",
        inputSchema={
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of changed file paths",
                },
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["changed_files", "repo_id"],
        },
    ),
    Tool(
        name="xce_search",
        description="Search the knowledge graph by semantic meaning or symbol",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
                "search_type": {
                    "type": "string",
                    "enum": ["semantic", "symbol", "tag"],
                    "description": "Type of search to perform",
                },
            },
            "required": ["query", "repo_id"],
        },
    ),
    Tool(
        name="xce_index_repo",
        description="Index or re-index a code repository",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the repository"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
                "incremental": {
                    "type": "boolean",
                    "default": True,
                    "description": "Only re-index changed files",
                },
            },
            "required": ["repo_path", "repo_id"],
        },
    ),
]

# Map tool name → required fields for validation
_REQUIRED_FIELDS: dict[str, list[str]] = {
    t.name: t.inputSchema.get("required", []) for t in TOOLS  # type: ignore[union-attr]
}

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    t.name: t.inputSchema for t in TOOLS  # type: ignore[misc]
}

_PROPERTY_TYPES: dict[str, dict[str, str]] = {}
for _t in TOOLS:
    schema = _t.inputSchema  # type: ignore[union-attr]
    props = schema.get("properties", {})
    _PROPERTY_TYPES[_t.name] = {k: v.get("type", "string") for k, v in props.items()}


# ---------------------------------------------------------------------------
# 9.3  Input validation
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised when tool arguments fail validation."""


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """Validate arguments against the tool's JSON schema.

    Raises ``ValidationError`` on missing required fields or wrong types.
    """
    if tool_name not in _REQUIRED_FIELDS:
        raise ValidationError(f"Unknown tool: {tool_name}")

    # Check required fields
    for field in _REQUIRED_FIELDS[tool_name]:
        if field not in arguments:
            raise ValidationError(f"Missing required argument: {field}")

    # Check types
    prop_types = _PROPERTY_TYPES.get(tool_name, {})
    for key, value in arguments.items():
        if key not in prop_types:
            continue  # extra fields are allowed
        expected = prop_types[key]
        if expected == "string" and not isinstance(value, str):
            raise ValidationError(f"Argument '{key}' must be a string, got {type(value).__name__}")
        elif expected == "array" and not isinstance(value, list):
            raise ValidationError(f"Argument '{key}' must be an array, got {type(value).__name__}")
        elif expected == "boolean" and not isinstance(value, bool):
            raise ValidationError(f"Argument '{key}' must be a boolean, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# 9.1 / 9.2  XCEMCPServer
# ---------------------------------------------------------------------------


class XCEMCPServer:
    """MCP server that registers 5 tools and routes calls to agents."""

    def __init__(
        self,
        agents: dict[str, Any] | None = None,
        summarizer: Any | None = None,
        indexer: Any | None = None,
    ) -> None:
        self.server = Server("xanther-context-engine")
        self._agents = agents or {}
        self._summarizer = summarizer
        self._indexer = indexer
        self._register_handlers()

    # -- tool registration -------------------------------------------

    def get_tools(self) -> list[Tool]:
        return list(TOOLS)

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def _list_tools() -> list[Tool]:
            return self.get_tools()

        @self.server.call_tool()
        async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
            return await self.handle_tool_call(name, arguments)

    # -- 9.2  routing ------------------------------------------------

    async def handle_tool_call(
        self, name: str, arguments: dict[str, Any],
    ) -> list[TextContent]:
        """Route MCP tool calls to the appropriate agent."""
        # Validate
        try:
            validate_tool_arguments(name, arguments)
        except ValidationError as exc:
            return [TextContent(type="text", text=json.dumps({
                "error": str(exc),
                "tool": name,
            }))]

        try:
            result = await self._dispatch(name, arguments)
            return [TextContent(type="text", text=json.dumps(result))]
        except Exception as exc:
            logger.exception("Tool call %s failed", name)
            return [TextContent(type="text", text=json.dumps({
                "error": f"Internal error: {exc}",
                "tool": name,
            }))]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "xce_architecture_context":
            agent = self._agents.get("architecture")
            if not agent:
                return {"error": "Architecture agent not configured"}
            result = await agent.query(args["file_or_symbol"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_trace":
            agent = self._agents.get("traceability")
            if not agent:
                return {"error": "Traceability agent not configured"}
            result = await agent.trace(args["source"], args["target_level"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_impact_analysis":
            agent = self._agents.get("impact")
            if not agent:
                return {"error": "Impact analysis agent not configured"}
            result = await agent.analyze(args["changed_files"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_search":
            agent = self._agents.get("search")
            if not agent:
                return {"error": "Search agent not configured"}
            result = await agent.search(
                args["query"], args["repo_id"],
                search_type=args.get("search_type", "semantic"),
            )
            return self._format_result(result)

        elif name == "xce_index_repo":
            if not self._indexer:
                return {"error": "Indexer not configured"}
            result = await self._indexer.index_repository(
                args["repo_path"], args["repo_id"],
                incremental=args.get("incremental", True),
            )
            return {"status": "ok", "result": str(result)}

        return {"error": f"Unknown tool: {name}"}

    @staticmethod
    def _format_result(result: Any) -> dict[str, Any]:
        """Convert a TraversalResult to a JSON-serializable dict."""
        return {
            "contexts": result.contexts,
            "reasoning": result.reasoning,
            "confidence": result.confidence,
            "nodes_visited": result.nodes_visited,
        }

    # -- 9.4  transport ----------------------------------------------

    async def run_stdio(self) -> None:
        """Run the MCP server over stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, write_stream,
                self.server.create_initialization_options(),
            )

    def create_sse_app(self) -> Any:
        """Create a FastAPI app with SSE transport for remote deployment."""
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI(title="XCE MCP Server")

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/tools")
        async def list_tools() -> list[dict[str, Any]]:
            return [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in self.get_tools()
            ]

        @app.post("/call")
        async def call_tool(request: Request) -> JSONResponse:
            body = await request.json()
            name = body.get("name", "")
            arguments = body.get("arguments", {})
            results = await self.handle_tool_call(name, arguments)
            return JSONResponse(content={
                "content": [{"type": r.type, "text": r.text} for r in results],
            })

        return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    server = XCEMCPServer()
    if "--sse" in sys.argv:
        import uvicorn
        app = server.create_sse_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=8000)
        srv = uvicorn.Server(config)
        await srv.serve()
    else:
        await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
