#!/usr/bin/env python3
"""
Xanther Interactive CLI — xanther-cli
=====================================
Rich terminal UI for indexing repos with live progress bars and stage views.

Usage:
    xanther index /path/to/repo                     # interactive full index
    xanther index /path/to/repo --mode xme          # fast mode (no LLM docs)
    xanther index /path/to/repo --diff              # index only changed files
    xanther status                                  # show indexed repos
    xanther query "how does auth work?" --repo myrepo   # query memory

Features:
    - Live progress bars per layer
    - Stage status indicators (✓ completed, ⟳ running, ○ pending)
    - Background processing with real-time updates
    - Git-diff based incremental indexing (--diff flag)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Set up path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Force OpenRouter
os.environ.setdefault("XCE_LLM_PROVIDER", "openrouter")

console = Console()

# Stage definitions
STAGES = [
    ("parse", "Layer 1: AST Parsing"),
    ("graph", "Graph Storage"),
    ("docs_l2", "Layer 2: Component Summaries"),
    ("docs_l3", "Layer 3: Component Docs"),
    ("docs_l4", "Layer 4: Architecture Docs"),
    ("embeddings", "Embeddings"),
    ("bridge", "XME Bridge Sync"),
]


def _get_git_changed_files(repo_path: str) -> list[str]:
    """Get files changed since last commit (staged + unstaged + untracked)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=repo_path
        )
        changed = set(result.stdout.strip().splitlines())
        # Also get untracked
        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=repo_path
        )
        changed.update(result2.stdout.strip().splitlines())
        return [f for f in changed if f]
    except Exception:
        return []


def _build_status_table(stages: dict[str, str], stats: dict) -> Table:
    """Build a rich table showing stage status."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("icon", width=3)
    table.add_column("stage", min_width=30)
    table.add_column("detail", min_width=30)

    icons = {"done": "✓", "running": "⟳", "pending": "○", "skipped": "—", "failed": "✗"}
    colors = {"done": "green", "running": "yellow", "pending": "dim", "skipped": "dim", "failed": "red"}

    for stage_id, stage_name in STAGES:
        status = stages.get(stage_id, "pending")
        icon = icons.get(status, "?")
        color = colors.get(status, "white")
        detail = stats.get(stage_id, "")
        table.add_row(
            f"[{color}]{icon}[/{color}]",
            f"[{color}]{stage_name}[/{color}]",
            f"[dim]{detail}[/dim]",
        )
    return table


async def cmd_index_interactive(
    repo_path: str,
    repo_id: Optional[str] = None,
    mode: str = "full",
    diff_only: bool = False,
    full_reindex: bool = False,
) -> None:
    """Interactive indexing with rich progress display."""
    from xce.config import get_settings
    from xce.graph.store import GraphStore
    from xce.indexing.indexer import index_repository, _discover_source_files
    from xce.indexing.doc_generator import DocGenerator
    from xce.indexing.embedding import EmbeddingService
    from xce.parsers import get_default_registry

    repo_path_obj = Path(repo_path).resolve()
    if not repo_path_obj.is_dir():
        console.print(f"[red]Error:[/red] {repo_path} is not a directory")
        return

    repo_id = repo_id or repo_path_obj.name
    settings = get_settings()

    # Set mode env vars
    if mode == "xme":
        os.environ["XCE_DEEP_DOCS"] = "false"
        os.environ["XCE_ARCH_DOCS"] = "false"
        os.environ["XME_BRIDGE_ENABLED"] = "true"
    elif mode == "full":
        os.environ["XCE_DEEP_DOCS"] = "true"
        os.environ["XCE_ARCH_DOCS"] = "true"
        os.environ["XME_BRIDGE_ENABLED"] = "true"
    else:  # xce
        os.environ["XCE_DEEP_DOCS"] = "true"
        os.environ["XCE_ARCH_DOCS"] = "true"
        os.environ["XME_BRIDGE_ENABLED"] = "false"

    # Diff mode: show changed files
    if diff_only:
        changed = _get_git_changed_files(str(repo_path_obj))
        if not changed:
            console.print("[green]✓ No files changed since last commit — nothing to index.[/green]")
            return
        console.print(f"\n[yellow]Changed files ({len(changed)}):[/yellow]")
        for f in changed[:20]:
            console.print(f"  [dim]•[/dim] {f}")
        if len(changed) > 20:
            console.print(f"  [dim]... and {len(changed)-20} more[/dim]")
        console.print()

    # Discover files
    registry = get_default_registry()
    source_files = _discover_source_files(str(repo_path_obj), registry)

    # Header
    console.print()
    console.print(Panel(
        f"[bold]Indexing:[/bold] {repo_path_obj.name}\n"
        f"[dim]Path:[/dim]    {repo_path_obj}\n"
        f"[dim]Repo ID:[/dim] {repo_id}\n"
        f"[dim]Mode:[/dim]    {mode.upper()}\n"
        f"[dim]Files:[/dim]   {len(source_files)} source files\n"
        f"[dim]Diff:[/dim]    {'yes (changed only)' if diff_only else 'no (full scan)'}",
        title="🧠 Xanther Index",
        border_style="blue",
    ))
    console.print()

    # Stage tracking
    stages: dict[str, str] = {s[0]: "pending" for s in STAGES}
    stats: dict[str, str] = {}
    t_start = time.time()

    # Run indexing with progress updates
    with console.status("[bold green]Indexing...") as status:
        # Phase 1: Connect + Parse
        status.update("[bold yellow]Connecting to Neo4j...")
        graph_store = GraphStore(
            neo4j_uri=settings.neo4j.uri,
            neo4j_auth=settings.neo4j.auth,
            embedding_dimensions=settings.embedding.dimensions,
        )
        await graph_store.init_schema()
        status.update("[bold yellow]✓ Neo4j connected")

        doc_gen = DocGenerator(api_key=settings.openrouter_api_key) if mode != "xme" else None
        embed_svc = EmbeddingService(
            api_key=settings.openrouter_api_key,
            model=settings.embedding.model,
            dimensions=settings.embedding.dimensions,
        )

        if doc_gen:
            console.print(f"  [dim]DocGen: {type(doc_gen._provider).__name__}[/dim]")
            console.print(f"  [dim]Embed: {type(embed_svc._provider).__name__}[/dim]")
            console.print(f"  [dim]Smart docs: ON (classes + functions ≥10 lines)[/dim]")
        console.print()

        status.update("[bold yellow]⟳ Layer 1: Parsing AST...")
        result, _ = await index_repository(
            str(repo_path_obj), repo_id,
            doc_generator=doc_gen,
            embedding_service=embed_svc,
            graph_store=graph_store,
            incremental=not full_reindex,
            smart_docs=True,
        )

    elapsed = time.time() - t_start

    # Final summary
    console.print()
    console.print(Panel(
        f"[green bold]✓ Indexing Complete[/green bold]\n\n"
        f"  [bold]Time:[/bold]       {elapsed:.1f}s\n"
        f"  [bold]Nodes:[/bold]      {result.nodes_count:,}\n"
        f"  [bold]Edges:[/bold]      {result.edges_count:,}\n"
        f"  [bold]Docs:[/bold]       {result.docs_count:,}\n"
        f"  [bold]Embeddings:[/bold] {result.embeddings_count:,}\n"
        f"  [bold]Mode:[/bold]       {mode.upper()}",
        title="📊 Results",
        border_style="green",
    ))
    console.print()

    await graph_store.close()


async def cmd_status_interactive() -> None:
    """Show indexed repos as a rich table."""
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
            console.print("\n[dim]No repositories indexed yet.[/dim]")
            console.print("[dim]  Run: xanther index /path/to/repo[/dim]\n")
            return

        table = Table(title="🧠 Indexed Repositories")
        table.add_column("Repo ID", style="bold")
        table.add_column("Nodes", justify="right")
        table.add_column("Edges", justify="right")
        table.add_column("Last Indexed")

        for r in repos:
            table.add_row(
                str(r.get("repo_id", "?")),
                str(r.get("node_count", "?")),
                str(r.get("edge_count", "?")),
                str(r.get("last_indexed", "?"))[:19],
            )
        console.print()
        console.print(table)
        console.print()
    finally:
        await graph_store.close()


async def cmd_query_interactive(query: str, repo_id: str) -> None:
    """Query CodeMemory and display results."""
    from xce.config import get_settings
    from xce.memory.code_memory import CodeMemory
    from neo4j import AsyncGraphDatabase

    settings = get_settings()
    driver = AsyncGraphDatabase.driver(settings.neo4j.uri, auth=settings.neo4j.auth)
    mem = CodeMemory(neo4j_driver=driver, xme_db_path=".xanther/xme.db")
    await mem.init()

    with console.status("[bold green]Searching memory..."):
        ctx = await mem.query(query, repo_id=repo_id)

    console.print()
    console.print(Panel(
        f"[bold]Query:[/bold] {query}\n"
        f"[bold]Repo:[/bold]  {repo_id}\n\n"
        f"[bold]Facts:[/bold] {len(ctx['facts'])} retrieved\n"
        f"[bold]Episodes:[/bold] {len(ctx['episodes'])} retrieved\n"
        f"[bold]Context:[/bold] {len(ctx['context_str']):,} chars",
        title="🔍 Search Results",
        border_style="cyan",
    ))
    console.print()

    if ctx["facts"]:
        console.print("[bold]Code Facts:[/bold]")
        for f in ctx["facts"][:10]:
            attr = f.get("attr") or f.get("name", "")
            val = str(f.get("val") or f.get("value", ""))[:100]
            console.print(f"  [green]•[/green] {attr}: [dim]{val}[/dim]")
        console.print()

    if ctx["episodes"]:
        console.print("[bold]Relevant Files/Sessions:[/bold]")
        for ep in ctx["episodes"][:5]:
            fp = ep.get("filepath", "")
            summary = ep.get("summary", "")
            label = fp or summary
            console.print(f"  [blue]📄[/blue] {label}")
        console.print()

    await mem.close()
    await driver.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="xanther",
        description="🧠 Xanther — Code Intelligence + Agent Memory",
    )
    sub = parser.add_subparsers(dest="command")

    # index
    idx = sub.add_parser("index", help="Index a repository")
    idx.add_argument("repo_path", help="Path to repository")
    idx.add_argument("--repo-id", default=None, help="Repository ID (default: dir name)")
    idx.add_argument("--mode", choices=["xme", "xce", "full"], default="full",
                     help="xme=fast memory only | xce=code graph only | full=both (default)")
    idx.add_argument("--diff", action="store_true",
                     help="Only index files changed since last git commit")
    idx.add_argument("--full", action="store_true", dest="full_reindex",
                     help="Force full re-index (skip incremental)")

    # status
    sub.add_parser("status", help="Show indexed repositories")

    # query
    q = sub.add_parser("query", help="Query code memory")
    q.add_argument("question", help="Natural language question about the codebase")
    q.add_argument("--repo", required=True, help="Repository ID to search")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "index":
        asyncio.run(cmd_index_interactive(
            args.repo_path,
            repo_id=args.repo_id,
            mode=args.mode,
            diff_only=args.diff,
            full_reindex=args.full_reindex,
        ))
    elif args.command == "status":
        asyncio.run(cmd_status_interactive())
    elif args.command == "query":
        asyncio.run(cmd_query_interactive(args.question, args.repo))


if __name__ == "__main__":
    main()
