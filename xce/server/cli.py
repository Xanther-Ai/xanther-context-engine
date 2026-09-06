"""CLI entry point for XCE MCP Server.

This module initializes the MCP server with all required agents and runs it.
Used as console script entry point: xce-mcp-server

Run: xce-mcp-server
Or:  python -m xce.server.cli
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from xce.config import get_settings
from xce.graph.store import GraphStore
from xce.query.agents import (
    ArchitectureAgent,
    ImpactAnalysisAgent,
    SearchDiscoveryAgent,
    TraceabilityAgent,
)
from xce.server.mcp_server import XCEMCPServer

logger = logging.getLogger(__name__)


def _build_agents() -> dict:
    """Wire up the XCE agents backed by a lazy Neo4j GraphStore.

    The Neo4j driver is created lazily and does not open a connection until a
    tool is actually called, so this succeeds even when Neo4j is unreachable —
    which is what lets the server answer introspection (tools/list) in
    directory checks (Glama, Docker MCP Catalog) that start the server without
    a backing datastore. On any unexpected wiring failure we return no agents
    so the server still starts and can serve tools/list; individual tool calls
    then report that the relevant agent is not configured.
    """
    try:
        settings = get_settings()
        logger.info(f"Configuring Neo4j at {settings.neo4j.uri} (connection is lazy)")
        graph_store = GraphStore(
            neo4j_uri=settings.neo4j.uri,
            neo4j_auth=settings.neo4j.auth,
            embedding_dimensions=settings.embedding.dimensions,
        )
        logger.info("Initializing agents...")
        return {
            "architecture": ArchitectureAgent(graph_store),
            "traceability": TraceabilityAgent(graph_store),
            "impact": ImpactAnalysisAgent(graph_store),
            "search": SearchDiscoveryAgent(graph_store),
        }
    except Exception:
        logger.exception(
            "Agent initialization failed; starting server without agents. "
            "Tool introspection will still work; tool calls will report "
            "that agents are not configured."
        )
        return {}


async def main() -> None:
    """Initialize agents and run the MCP server.

    Startup is resilient: even if agent wiring fails, the server still starts so
    that MCP introspection (tools/list) succeeds. This keeps directory listing
    checks (Glama, Docker MCP Catalog) — which start the server with no reachable
    Neo4j — from failing.
    """
    agents = _build_agents()

    logger.info("Starting XCE MCP Server...")
    server = XCEMCPServer(agents=agents)

    if "--sse" in sys.argv:
        # Remote SSE mode
        logger.info("Running in SSE mode (remote deployment)")
        import uvicorn
        app = server.create_sse_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=8000)
        srv = uvicorn.Server(config)
        await srv.serve()
    else:
        # Local stdio mode (default for Kiro)
        logger.info("Running in stdio mode (local)")
        await server.run_stdio()


def run() -> None:
    """Synchronous entry point for console script."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # MCP protocol uses stdout for messages
    )
    
    asyncio.run(main())


if __name__ == "__main__":
    run()
