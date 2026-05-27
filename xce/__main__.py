"""CLI entry point for Xanther Context Engine.

Usage:
    python -m xce index /path/to/repo --repo-id my-project
    python -m xce serve
    python -m xce serve --sse
    python -m xce status
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("xce")


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the CLI."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def cmd_index(args: argparse.Namespace) -> None:
    """Index a repository into the knowledge graph."""
    from xce.config import get_settings
    from xce.graph_store import GraphStore
    from xce.indexer import Indexer

    settings = get_settings()
    repo_path = Path(args.repo_path).resolve()

    if not repo_path.is_dir():
        print(f"Error: {repo_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    repo_id = args.repo_id or repo_path.name

    print(f"Indexing {repo_path} as '{repo_id}'...")
    print(f"  Neo4j: {settings.neo4j_uri}")
    print(f"  Embedding model: {settings.embedding_model}")
    print()

    graph_store = GraphStore(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    try:
        indexer = Indexer(graph_store=graph_store, settings=settings)
        result = await indexer.index_repository(
            str(repo_path),
            repo_id,
            incremental=not args.full,
        )
        print(f"\nIndexing complete:")
        print(f"  Nodes:      {result.nodes_count}")
        print(f"  Edges:      {result.edges_count}")
        print(f"  Docs:       {result.docs_count}")
        print(f"  Embeddings: {result.embeddings_count}")
    finally:
        await graph_store.close()


async def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from xce.mcp_server import XCEMCPServer

    server = XCEMCPServer()

    if args.sse:
        import uvicorn

        print("Starting XCE MCP server (SSE mode) on http://0.0.0.0:8000")
        app = server.create_sse_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=args.port)
        srv = uvicorn.Server(config)
        await srv.serve()
    else:
        print("Starting XCE MCP server (stdio mode)...", file=sys.stderr)
        await server.run_stdio()


async def cmd_status(args: argparse.Namespace) -> None:
    """Show status of indexed repositories."""
    from xce.config import get_settings
    from xce.graph_store import GraphStore

    settings = get_settings()
    graph_store = GraphStore(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    try:
        repos = await graph_store.list_repositories()
        if not repos:
            print("No repositories indexed yet.")
            print("\nTo index a repo:")
            print("  python -m xce index /path/to/repo --repo-id my-project")
            return

        print(f"Indexed repositories ({len(repos)}):\n")
        for repo in repos:
            print(f"  {repo['repo_id']}")
            print(f"    Nodes: {repo.get('node_count', 'unknown')}")
            print(f"    Last indexed: {repo.get('last_indexed', 'unknown')}")
            print()
    finally:
        await graph_store.close()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xce",
        description="Xanther Context Engine — architecture-aware code intelligence",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- index ---
    index_parser = subparsers.add_parser("index", help="Index a repository")
    index_parser.add_argument("repo_path", help="Path to the repository to index")
    index_parser.add_argument(
        "--repo-id",
        default=None,
        help="Repository identifier (defaults to directory name)",
    )
    index_parser.add_argument(
        "--full",
        action="store_true",
        help="Force full re-index (skip incremental)",
    )

    # --- serve ---
    serve_parser = subparsers.add_parser("serve", help="Start MCP server")
    serve_parser.add_argument(
        "--sse",
        action="store_true",
        help="Use SSE transport (HTTP) instead of stdio",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE mode (default: 8000)",
    )

    # --- status ---
    subparsers.add_parser("status", help="Show indexed repositories")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.log_level)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "index":
        asyncio.run(cmd_index(args))
    elif args.command == "serve":
        asyncio.run(cmd_serve(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
