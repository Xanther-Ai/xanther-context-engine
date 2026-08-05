"""
HTTP MCP Server for Xanther Context Engine.

Exposes XCE tools via HTTP (no external MCP package required).
Kiro calls this via http://localhost:8001/mcp/call

Run: python -m xce.server.http_mcp_server
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from xce.graph.store import GraphStore
from xce.query.agents import (
    ArchitectureAgent,
    ImpactAnalysisAgent,
    SearchDiscoveryAgent,
    TraceabilityAgent,
)
from xce.config import get_settings

logger = logging.getLogger("xce.http_mcp")

# Tool definitions matching MCP schema
TOOLS = [
    {
        "name": "xce_search",
        "description": "Search the knowledge graph by semantic meaning or symbol",
        "inputSchema": {
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
    },
    {
        "name": "xce_architecture_context",
        "description": "Get architectural context for a file or symbol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_or_symbol": {"type": "string", "description": "File path or symbol name"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["file_or_symbol", "repo_id"],
        },
    },
    {
        "name": "xce_trace",
        "description": "Trace relationships between code and design artifacts",
        "inputSchema": {
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
    },
    {
        "name": "xce_impact_analysis",
        "description": "Predict blast radius for proposed code changes",
        "inputSchema": {
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
    },
]


class XCEHTTPMCPServer:
    """HTTP-based MCP server for XCE."""

    def __init__(self):
        self.settings = get_settings()
        self.app = FastAPI(title="XCE HTTP MCP Server")
        self._register_routes()

    def _register_routes(self):
        """Register FastAPI routes."""

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "service": "xce-http-mcp"}

        @self.app.get("/tools")
        async def list_tools():
            return {"tools": TOOLS}

        @self.app.post("/mcp/call")
        async def call_tool(request: Request):
            """Call an MCP tool via HTTP."""
            try:
                body = await request.json()
                tool_name = body.get("name", "")
                arguments = body.get("arguments", {})

                result = await self._dispatch_tool(tool_name, arguments)
                return JSONResponse({
                    "content": [{"type": "text", "text": json.dumps(result)}]
                })
            except Exception as e:
                logger.exception(f"Tool call failed: {tool_name}")
                return JSONResponse(
                    {
                        "content": [
                            {"type": "text", "text": json.dumps({"error": str(e)})}
                        ]
                    },
                    status_code=500,
                )

    async def _dispatch_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch tool call to appropriate agent."""
        settings = get_settings()

        # Create GraphStore
        graph_store = GraphStore(
            neo4j_uri=settings.neo4j.uri,
            neo4j_auth=settings.neo4j.auth,
            embedding_dimensions=settings.embedding.dimensions,
        )

        try:
            if tool_name == "xce_search":
                agent = SearchDiscoveryAgent(graph_store)
                result = await agent.search(
                    arguments["query"],
                    arguments["repo_id"],
                    search_type=arguments.get("search_type", "semantic"),
                )
                return {
                    "contexts": result.contexts,
                    "reasoning": result.reasoning,
                    "confidence": result.confidence,
                }

            elif tool_name == "xce_architecture_context":
                agent = ArchitectureAgent(graph_store)
                result = await agent.query(
                    arguments["file_or_symbol"],
                    arguments["repo_id"],
                )
                return {
                    "contexts": result.contexts,
                    "reasoning": result.reasoning,
                    "confidence": result.confidence,
                }

            elif tool_name == "xce_trace":
                agent = TraceabilityAgent(graph_store)
                result = await agent.trace(
                    arguments["source"],
                    arguments["target_level"],
                    arguments["repo_id"],
                )
                return {
                    "contexts": result.contexts,
                    "reasoning": result.reasoning,
                    "confidence": result.confidence,
                }

            elif tool_name == "xce_impact_analysis":
                agent = ImpactAnalysisAgent(graph_store)
                result = await agent.analyze(
                    arguments["changed_files"],
                    arguments["repo_id"],
                )
                return {
                    "contexts": result.contexts,
                    "reasoning": result.reasoning,
                    "confidence": result.confidence,
                }

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        finally:
            await graph_store.close()

    def run(self, host: str = "127.0.0.1", port: int = 8001):
        """Run the HTTP MCP server."""
        logger.info(f"Starting XCE HTTP MCP Server on http://{host}:{port}")
        uvicorn.run(self.app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    server = XCEHTTPMCPServer()
    server.run()
