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


async def main() -> None:
    """Initialize agents and run the MCP server."""
    try:
        settings = get_settings()
        
        # Initialize GraphStore
        logger.info(f"Connecting to Neo4j at {settings.neo4j.uri}")
        graph_store = GraphStore(
            neo4j_uri=settings.neo4j.uri,
            neo4j_auth=settings.neo4j.auth,
            embedding_dimensions=settings.embedding.dimensions,
        )
        
        # Initialize agents
        logger.info("Initializing agents...")
        agents = {
            "architecture": ArchitectureAgent(graph_store),
            "traceability": TraceabilityAgent(graph_store),
            "impact": ImpactAnalysisAgent(graph_store),
            "search": SearchDiscoveryAgent(graph_store),
        }
        
        # Create and run MCP server
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
            
    except Exception as e:
        logger.exception("Failed to start MCP server")
        sys.exit(1)


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
