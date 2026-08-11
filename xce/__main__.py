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
    import os
    from xce.config import get_settings
    from xce.graph.store import GraphStore
    from xce.indexing.hash_store import HashStore

    settings = get_settings()
    repo_path = Path(args.repo_path).resolve()

    if not repo_path.is_dir():
        print(f"Error: {repo_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    repo_id = args.repo_id or repo_path.name
    postgres_uri = os.environ.get("POSTGRES_URI", "")

    print(f"Indexing {repo_path} as '{repo_id}'...")
    print(f"  Mode:      {args.mode}")
    print(f"  Neo4j:     {settings.neo4j.uri}")
    print(f"  Embedding: {settings.embedding.model} ({settings.embedding.dimensions}d)")
    if postgres_uri:
        print(f"  Postgres:  {postgres_uri.split('@')[-1]}")  # hide credentials
    print(f"  Incremental: {'full' if args.full else 'yes'}")
    print(f"  Smart docs: {'yes (default)' if args.smart_docs else 'no (all nodes)'}")
    print()

    # Mode: xme = fast facts-only, xce = code graph only, full = both
    mode = getattr(args, "mode", "full")
    run_xce_layers = mode in ("xce", "full")
    run_xme_bridge = mode in ("xme", "full")

    # xme-only mode: skip LLM doc generation entirely
    if mode == "xme":
        print("  XME-only mode: AST parse + XME sync (no LLM doc generation)")
        print("  Tip: fastest option — use for quick memory indexing without deep code analysis")
        print()

    graph_store = GraphStore(
        neo4j_uri=settings.neo4j.uri,
        neo4j_auth=settings.neo4j.auth,
        embedding_dimensions=settings.embedding.dimensions,
    )
    await graph_store.init_schema()

    hash_store: HashStore | None = None
    if postgres_uri:
        hash_store = HashStore(postgres_uri)
        try:
            await hash_store.connect()
            print("  ✓ PostgreSQL connected (incremental indexing enabled)")
        except Exception as e:
            print(f"  ⚠ PostgreSQL unavailable: {e} — running without incremental hashing")
            hash_store = None

    try:
        from xce.indexing.indexer import index_repository
        from xce.indexing.doc_generator import DocGenerator
        from xce.indexing.embedding import EmbeddingService

        doc_generator = DocGenerator(
            api_key=settings.openrouter_api_key or settings.kimi_api_key,
        )
        embedding_service = EmbeddingService(
            api_key=settings.openrouter_api_key,
            model=settings.embedding.model,
            dimensions=settings.embedding.dimensions,
        )

        import time
        import os as _os
        start = time.time()

        # XME bridge: set env var before index call so the bridge hook inside picks it up
        if run_xme_bridge:
            _os.environ["XME_BRIDGE_ENABLED"] = "true"
        else:
            _os.environ["XME_BRIDGE_ENABLED"] = "false"

        # xme-only: skip LLM doc gen by using a no-op doc_generator
        active_doc_gen = doc_generator if run_xce_layers else None

        result, _ = await index_repository(
            str(repo_path),
            repo_id,
            doc_generator=active_doc_gen,
            embedding_service=embedding_service,
            graph_store=graph_store,
            hash_store=hash_store,
            incremental=not args.full,
            smart_docs=args.smart_docs,
        )

        elapsed = time.time() - start
        print(f"\n✓ Indexing complete ({elapsed:.1f}s)")
        print(f"  Nodes:      {result.nodes_count}")
        print(f"  Edges:      {result.edges_count}")
        print(f"  Docs:       {result.docs_count}")
        print(f"  Embeddings: {result.embeddings_count}")
    finally:
        await graph_store.close()
        if hash_store:
            await hash_store.close()


async def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server."""
    from xce.server.mcp_server import XCEMCPServer

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
    from xce.graph.store import GraphStore

    settings = get_settings()
    graph_store = GraphStore(
        neo4j_uri=settings.neo4j.uri,
        neo4j_auth=settings.neo4j.auth,
        embedding_dimensions=settings.embedding.dimensions,
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


def cmd_memory(args: argparse.Namespace) -> None:
    """Handle all XME memory subcommands (sync is the only async one)."""
    from xce.memory.store import MemoryStore

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"Error: {repo_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    mem_cmd = args.memory_command
    if not mem_cmd:
        print("Usage: xce memory <remember|decisions|attempts|search|sync|stats>")
        return

    if mem_cmd == "remember":
        _mem_remember(args, repo_path)
    elif mem_cmd == "decisions":
        _mem_decisions(args, repo_path)
    elif mem_cmd == "attempts":
        _mem_attempts(args, repo_path)
    elif mem_cmd == "search":
        _mem_search(args, repo_path)
    elif mem_cmd == "sync":
        _mem_sync(args, repo_path)
    elif mem_cmd == "stats":
        _mem_stats(args, repo_path)
    elif mem_cmd == "hooks":
        _mem_hooks(args, repo_path)
    else:
        print(f"Unknown memory command: {mem_cmd}", file=sys.stderr)
        sys.exit(1)


def _mem_remember(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    from xce.memory.models import (
        DecisionNode, AttemptNode, SessionNode,
        UserPreferenceNode, TeamConventionNode,
    )
    with MemoryStore.open(repo_path) as store:
        ntype = args.node_type
        if ntype == "decision":
            node = DecisionNode()
            node.title = args.title
            node.context = args.context
            node.decision = args.decision
            node.affected_modules = args.modules or []
            store.save_decision(node)
            print(f"✓ Decision stored: {node.id}")
        elif ntype == "attempt":
            node = AttemptNode()
            node.problem = args.context
            node.approach = args.approach
            node.result = args.result
            node.failure_reason = args.failure_reason
            node.lessons_learned = args.lessons
            store.save_attempt(node)
            print(f"✓ Attempt stored: {node.id}")
        elif ntype == "session":
            node = SessionNode()
            node.problem_statement = args.context
            node.summary = args.summary
            node.outcome = args.result
            store.save_session(node)
            print(f"✓ Session stored: {node.id}")
        elif ntype == "convention":
            node = TeamConventionNode()
            node.title = args.title
            node.description = args.context
            store.save_convention(node)
            print(f"✓ Convention stored: {node.id}")
        else:
            print(f"node_type '{ntype}' not yet supported via CLI", file=sys.stderr)


def _mem_decisions(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    with MemoryStore.open(repo_path) as store:
        if args.module:
            decisions = store.list_decisions_for_module(args.module)
        else:
            decisions = store.list_decisions(
                limit=args.limit, include_reverted=args.include_reverted
            )
        if not decisions:
            print("No decisions found.")
            return
        print(f"Decisions ({len(decisions)}):\n")
        for d in decisions:
            print(f"  [{d.outcome.upper()}] {d.title}")
            print(f"    {d.context[:100]}" if d.context else "")
            print(f"    ID: {d.id}  Author: {d.author}  {d.created_at[:10]}")
            print()


def _mem_attempts(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    with MemoryStore.open(repo_path) as store:
        results = store.search(args.query, limit=args.limit)
        attempts = [r for r in results if r.node_type == "attempt"
                    and (not args.result or r.data.get("result") == args.result)]
        if not attempts:
            print("No attempts found.")
            return
        print(f"Attempts ({len(attempts)}):\n")
        for r in attempts:
            d = r.data
            print(f"  [{d.get('result','?').upper()}] {d.get('problem','')[:80]}")
            print(f"    Approach: {d.get('approach','')[:80]}")
            if d.get("failure_reason"):
                print(f"    Failed because: {d['failure_reason'][:100]}")
            if d.get("lessons_learned"):
                print(f"    Lessons: {d['lessons_learned'][:100]}")
            print()


def _mem_search(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    with MemoryStore.open(repo_path) as store:
        results = store.search(args.query, limit=args.limit)
        if not results:
            print("No results found.")
            return
        print(f"Memory search results for '{args.query}' ({len(results)}):\n")
        for r in results:
            print(f"  [{r.node_type.upper()} / {r.scope.value}] {r.summary[:100]}")
            print(f"    score={r.score:.3f}  id={r.node_id}")
            print()


def _mem_sync(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    from xce.memory.sync import MemorySyncer
    with MemoryStore.open(repo_path) as store:
        syncer = MemorySyncer(memory_dir=store._dir, repo_root=repo_path)
        direction = args.direction
        if direction == "push":
            result = syncer.push(store)
            print(f"✓ Pushed: {result}")
        elif direction == "pull":
            result = syncer.pull(store)
            print(f"✓ Pulled: {result}")
        else:
            result = syncer.sync(store)
            print(f"✓ Synced: pulled={result['pulled']} pushed={result['pushed']}")


def _mem_stats(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.store import MemoryStore
    with MemoryStore.open(repo_path) as store:
        s = store.stats()
        print("XME Memory Store Stats:")
        print(f"  Sessions:    {s.get('personal_sessions', 0)}")
        print(f"  Preferences: {s.get('personal_prefs', 0)}")
        print(f"  Decisions:   {s.get('team_decisions', 0)}")
        print(f"  Attempts:    {s.get('team_attempts', 0)}")
        print(f"  Conventions: {s.get('team_conventions', 0)}")
        cache = s.get("cache", {})
        print(f"  Cache:       {cache.get('size', 0)} entries "
              f"(hits={cache.get('hits', 0)} misses={cache.get('misses', 0)})")
        print(f"  DB path:     {store._db_path}")


def _mem_hooks(args: argparse.Namespace, repo_path: Path) -> None:
    from xce.memory.hook_installer import install_hooks, uninstall_hooks
    hooks_cmd = getattr(args, "hooks_command", None)
    if not hooks_cmd:
        print("Usage: xce memory hooks <install|uninstall>")
        return

    if hooks_cmd == "install":
        dry = getattr(args, "dry_run", False)
        written = install_hooks(str(repo_path), dry_run=dry)
        prefix = "[DRY RUN] Would write" if dry else "✓ Written"
        print(f"\n{prefix} Kiro hooks:")
        for f in written["kiro"]:
            print(f"  {f}")
        print(f"\n{prefix} Claude Code config:")
        for f in written["claude"]:
            print(f"  {f}")
        if not dry:
            print("\nHooks installed. XME will now auto-ingest after every agent turn.")
            print("Events wired:")
            print("  agentStop / Stop         → flush + compact + save session")
            print("  promptSubmit             → record user turn in journal")
            print("  postToolUse / PostToolUse → record tool calls in journal")

    elif hooks_cmd == "uninstall":
        removed = uninstall_hooks(str(repo_path))
        print("✓ Removed XME hooks:")
        for f in removed["kiro"] + removed["claude"]:
            print(f"  {f}")


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
    index_parser.add_argument(
        "--mode",
        choices=["xme", "xce", "full"],
        default="full",
        help=(
            "Indexing mode:\n"
            "  xme  — memory only: fast AST parse + XME fact/episode sync, no LLM docs\n"
            "  xce  — code graph only: full 4-layer XCE indexing, no XME sync\n"
            "  full — XCE + XME: index everything and sync to XME (default)"
        ),
    )
    index_parser.add_argument(
        "--smart-docs",
        action="store_true",
        default=True,
        help=(
            "Only generate LLM docs for classes and functions/methods >= 10 lines. "
            "Skips trivial nodes. Reduces LLM cost ~80%% with minimal quality loss. "
            "(ON by default — use --no-smart-docs to disable)"
        ),
    )
    index_parser.add_argument(
        "--no-smart-docs",
        dest="smart_docs",
        action="store_false",
        help="Disable smart filtering — generate docs for all nodes (slower, more expensive).",
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

    # --- memory ---
    mem_parser = subparsers.add_parser("memory", help="XME — Xanther Memory Engine")
    mem_sub = mem_parser.add_subparsers(dest="memory_command", help="Memory commands")

    # memory remember
    mem_rem = mem_sub.add_parser("remember", help="Store a memory node (decision/attempt/session)")
    mem_rem.add_argument("repo_path", help="Path to the repository")
    mem_rem.add_argument("node_type",
                         choices=["decision", "attempt", "session", "preference", "convention"],
                         help="Type of memory node")
    mem_rem.add_argument("--title", default="", help="Title (decisions/conventions)")
    mem_rem.add_argument("--context", default="", help="Context / problem description")
    mem_rem.add_argument("--decision", default="", help="What was decided (decision nodes)")
    mem_rem.add_argument("--approach", default="", help="Approach tried (attempt nodes)")
    mem_rem.add_argument("--result", default="unknown",
                         choices=["success", "failed", "partial", "unknown"],
                         help="Outcome (attempt/session nodes)")
    mem_rem.add_argument("--failure-reason", default="", help="Why it failed (attempt nodes)")
    mem_rem.add_argument("--lessons", default="", help="Lessons learned (attempt nodes)")
    mem_rem.add_argument("--summary", default="", help="Session summary")
    mem_rem.add_argument("--modules", nargs="*", default=[],
                         help="Affected modules (decision nodes)")

    # memory decisions
    mem_dec = mem_sub.add_parser("decisions", help="List architectural decisions")
    mem_dec.add_argument("repo_path", help="Path to the repository")
    mem_dec.add_argument("--module", default="", help="Filter by module path")
    mem_dec.add_argument("--include-reverted", action="store_true")
    mem_dec.add_argument("--limit", type=int, default=20)

    # memory attempts
    mem_att = mem_sub.add_parser("attempts", help="List past attempts for a problem")
    mem_att.add_argument("repo_path", help="Path to the repository")
    mem_att.add_argument("query", help="Problem description to search for")
    mem_att.add_argument("--result", default="", choices=["", "failed", "success", "partial"])
    mem_att.add_argument("--limit", type=int, default=10)

    # memory search
    mem_srch = mem_sub.add_parser("search", help="Keyword search across all memory")
    mem_srch.add_argument("repo_path", help="Path to the repository")
    mem_srch.add_argument("query", help="Search query")
    mem_srch.add_argument("--limit", type=int, default=20)

    # memory sync
    mem_sync = mem_sub.add_parser("sync", help="Sync team memory via git")
    mem_sync.add_argument("repo_path", help="Path to the repository")
    mem_sync.add_argument("--direction", choices=["push", "pull", "sync"], default="sync")

    # memory stats
    mem_stats = mem_sub.add_parser("stats", help="Show memory store statistics")
    mem_stats.add_argument("repo_path", help="Path to the repository")

    # memory hooks
    mem_hooks = mem_sub.add_parser("hooks", help="Install/uninstall IDE hooks")
    mem_hooks_sub = mem_hooks.add_subparsers(dest="hooks_command")
    mh_install = mem_hooks_sub.add_parser("install", help="Install Kiro + Claude Code hooks")
    mh_install.add_argument("repo_path", nargs="?", default=".", help="Repo path (default: cwd)")
    mh_install.add_argument("--dry-run", action="store_true", help="Show what would be written")
    mh_uninstall = mem_hooks_sub.add_parser("uninstall", help="Remove XME hooks")
    mh_uninstall.add_argument("repo_path", nargs="?", default=".", help="Repo path (default: cwd)")

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
    elif args.command == "memory":
        cmd_memory(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
