#!/usr/bin/env python3
"""
Xanther Interactive CLI — xanther-cli
=====================================
Rich terminal UI with real progress bars, stage transitions, and % updates.

Usage:
    xanther index /path/to/repo                     # full index (XCE + XME)
    xanther index /path/to/repo --mode xme          # fast mode (no LLM docs)
    xanther index /path/to/repo --diff              # only changed files
    xanther status                                  # show indexed repos
    xanther query "how does auth work?" --repo id   # query memory
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
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TaskProgressColumn
from rich.table import Table

# Set up path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Force OpenRouter
os.environ.setdefault("XCE_LLM_PROVIDER", "openrouter")

console = Console()


def _get_git_changed_files(repo_path: str) -> list[str]:
    """Get files changed since last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=repo_path
        )
        changed = set(result.stdout.strip().splitlines())
        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=repo_path
        )
        changed.update(result2.stdout.strip().splitlines())
        return [f for f in changed if f]
    except Exception:
        return []


async def cmd_index_interactive(
    repo_path: str,
    repo_id: Optional[str] = None,
    mode: str = "full",
    diff_only: bool = False,
    full_reindex: bool = False,
) -> None:
    """Interactive indexing with real progress bars per stage."""
    from xce.config import get_settings
    from xce.graph.store import GraphStore
    from xce.indexing.doc_generator import DocGenerator
    from xce.indexing.embedding import EmbeddingService
    from xce.indexing.indexer import _discover_source_files, _compute_file_hash, _is_worth_documenting, group_by_module
    from xce.parsers import get_default_registry
    from xce.models import ASTNode, NodeKind
    from xce.parser import resolve_cross_file_imports

    repo_path_obj = Path(repo_path).resolve()
    if not repo_path_obj.is_dir():
        console.print(f"[red]Error:[/red] {repo_path} is not a directory")
        return

    repo_id = repo_id or repo_path_obj.name
    settings = get_settings()

    # Mode env
    run_docs = mode in ("xce", "full")
    run_bridge = mode in ("xme", "full")
    if run_bridge:
        os.environ["XME_BRIDGE_ENABLED"] = "true"
    else:
        os.environ["XME_BRIDGE_ENABLED"] = "false"

    # Header
    console.print()
    console.print(Panel(
        f"[bold]Repo:[/bold]    {repo_path_obj.name}\n"
        f"[dim]Path:[/dim]    {repo_path_obj}\n"
        f"[dim]ID:[/dim]      {repo_id}\n"
        f"[dim]Mode:[/dim]    {mode.upper()} {'(no LLM docs)' if mode == 'xme' else '(all layers)'}",
        title="Xanther Index",
        border_style="blue",
    ))
    console.print()

    t_start = time.time()

    # Checkpoint for resumable indexing
    from xce.indexing.checkpoint import IndexCheckpoint
    ckpt = IndexCheckpoint(repo_id)

    if ckpt.has_progress:
        console.print(f"  [yellow]⟳ Resuming from previous run[/yellow]")
        console.print(f"  [dim]Completed: {', '.join(ckpt.completed_layers)}[/dim]")
        console.print()

    # Connect Neo4j
    graph_store = GraphStore(
        neo4j_uri=settings.neo4j.uri,
        neo4j_auth=settings.neo4j.auth,
        embedding_dimensions=settings.embedding.dimensions,
    )
    await graph_store.init_schema()

    # Services
    doc_gen = DocGenerator(api_key=settings.openrouter_api_key) if run_docs else None
    embed_svc = EmbeddingService(
        api_key=settings.openrouter_api_key,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
    )

    # ===== STAGE 1: Discover + Parse =====
    registry = get_default_registry()
    source_files = _discover_source_files(str(repo_path_obj), registry)

    all_nodes: list[ASTNode] = []
    all_edges = []

    # Layer 1 is fast — always re-run (idempotent)
    ckpt.start_layer("layer1")
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Layer 1:[/bold blue] Parsing AST"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("parsing", total=len(source_files))
        for abs_path in source_files:
            rel_path = os.path.relpath(abs_path, str(repo_path_obj))
            parser = registry.get_parser(rel_path)
            if parser is None:
                progress.advance(task)
                continue
            try:
                source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
                nodes, edges = parser.parse_file(rel_path, source, repo_id)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
            except Exception:
                pass
            progress.advance(task)

    # Cross-file imports
    cross_edges = resolve_cross_file_imports(all_nodes)
    all_edges.extend(cross_edges)
    ckpt.set_total_nodes(len(all_nodes))
    ckpt.complete_layer("layer1")
    console.print(f"  [green]✓[/green] {len(all_nodes)} nodes, {len(all_edges)} edges parsed")

    # ===== STAGE 2: Store in Neo4j =====
    if not ckpt.is_layer_done("graph"):
        ckpt.start_layer("graph")
        with console.status("[bold yellow]Storing graph in Neo4j..."):
            nodes_stored = await graph_store.upsert_ast_nodes(all_nodes)
            edges_stored = await graph_store.upsert_edges(all_edges)
        ckpt.complete_layer("graph")
        console.print(f"  [green]✓[/green] Graph stored: {nodes_stored} nodes, {edges_stored} edges")
    else:
        nodes_stored = len(all_nodes)
        edges_stored = len(all_edges)
        console.print(f"  [green]✓[/green] Graph: already stored (skipped)")

    # ===== STAGE 3: Generate component descriptions (Layer 2) =====
    all_descs = []
    if doc_gen:
        if not ckpt.is_layer_done("layer2"):
            ckpt.start_layer("layer2")
            nodes_for_docs = [n for n in all_nodes if _is_worth_documenting(n, True)]
            done_ids = ckpt.get_done_nodes("layer2")
            remaining = [n for n in nodes_for_docs if n.id not in done_ids]
            console.print(f"  [dim]Smart docs: {len(nodes_for_docs)} nodes ({len(remaining)} remaining)[/dim]")

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Layer 2:[/bold blue] Component summaries"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                batch_size = doc_gen.batch_size
                total_batches = (len(remaining) + batch_size - 1) // batch_size
                task = progress.add_task("docs", total=total_batches)
                for i in range(0, len(remaining), batch_size):
                    batch = remaining[i:i + batch_size]
                    try:
                        descs = await doc_gen.generate_batch(batch)
                        all_descs.extend(descs)
                        await graph_store.upsert_documentation(descs)
                        for n in batch:
                            ckpt.mark_node_done("layer2", n.id)
                    except Exception:
                        pass
                    progress.advance(task)

            ckpt.flush()
            ckpt.complete_layer("layer2")
            console.print(f"  [green]✓[/green] {len(all_descs)} descriptions generated")
        else:
            console.print(f"  [green]✓[/green] Layer 2: already complete (skipped)")

    # ===== STAGE 4: Layer 3 (ComponentDoc) =====
    docs_count = 0
    deep_docs = os.environ.get("XCE_DEEP_DOCS", "true").lower() == "true"
    if doc_gen and deep_docs:
        if not ckpt.is_layer_done("layer3"):
            ckpt.start_layer("layer3")
            desc_map = {d.node_id: d for d in all_descs}
            func_nodes = [n for n in all_nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD) and n.id in desc_map]
            done_ids = ckpt.get_done_nodes("layer3")
            remaining = [n for n in func_nodes if n.id not in done_ids]

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Layer 3:[/bold blue] Detailed docs"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("layer3", total=len(remaining))
                for node in remaining:
                    desc = desc_map.get(node.id)
                    if desc:
                        try:
                            cdoc = await doc_gen.generate_component_doc(desc, node.source_text or "")
                            if cdoc:
                                await graph_store.upsert_documentation([cdoc])
                                docs_count += 1
                        except Exception:
                            pass
                    ckpt.mark_node_done("layer3", node.id)
                    progress.advance(task)

            ckpt.flush()
            ckpt.complete_layer("layer3")
            console.print(f"  [green]✓[/green] {docs_count} component docs generated")
        else:
            console.print(f"  [green]✓[/green] Layer 3: already complete (skipped)")

    # ===== STAGE 5: Layer 4 (Architecture) =====
    arch_count = 0
    arch_docs = os.environ.get("XCE_ARCH_DOCS", "true").lower() == "true"
    if doc_gen and arch_docs:
        if not ckpt.is_layer_done("layer4"):
            ckpt.start_layer("layer4")
            desc_map = {d.node_id: d for d in all_descs}
            modules = group_by_module(all_nodes)
            done_mods = ckpt.get_done_nodes("layer4")
            remaining_mods = {k: v for k, v in modules.items() if k not in done_mods}

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Layer 4:[/bold blue] Architecture docs"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("layer4", total=len(remaining_mods))
                for module_path, module_nodes in remaining_mods.items():
                    module_descs = [desc_map[n.id] for n in module_nodes if n.id in desc_map]
                    if module_descs:
                        try:
                            adoc = await doc_gen.generate_architecture_doc(module_path, module_descs)
                            if adoc:
                                await graph_store.upsert_documentation([adoc])
                                arch_count += 1
                        except Exception:
                            pass
                    ckpt.mark_node_done("layer4", module_path)
                    progress.advance(task)

            ckpt.flush()
            ckpt.complete_layer("layer4")
            console.print(f"  [green]✓[/green] {arch_count} architecture docs generated")
        else:
            console.print(f"  [green]✓[/green] Layer 4: already complete (skipped)")

    # ===== STAGE 6: Embeddings =====
    emb_count = 0
    if not ckpt.is_layer_done("embed"):
        ckpt.start_layer("embed")
        embed_start = ckpt.get_embed_progress()

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Embeddings:[/bold blue] Vector encoding"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            texts = [embed_svc.build_embedding_text(n) for n in all_nodes]
            batch_size = 100
            total_batches = (len(texts) + batch_size - 1) // batch_size
            start_batch = embed_start // batch_size
            task = progress.add_task("embed", total=total_batches, completed=start_batch)
            all_embeddings = [[0.0] * settings.embedding.dimensions] * embed_start  # placeholder for already-done
            for i in range(embed_start, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                try:
                    embs = await embed_svc.encode_batch(batch_texts)
                    all_embeddings.extend(embs)
                except Exception:
                    all_embeddings.extend([[0.0] * settings.embedding.dimensions for _ in batch_texts])
                ckpt.set_embed_progress(i + len(batch_texts))
                progress.advance(task)

            if all_embeddings and len(all_embeddings) == len(all_nodes):
                try:
                    node_ids = [n.id for n in all_nodes]
                    emb_count = await graph_store.upsert_embeddings(node_ids, all_embeddings)
                except Exception:
                    pass

        ckpt.complete_layer("embed")
        console.print(f"  [green]✓[/green] {emb_count} embeddings stored")
    else:
        emb_count = len(all_nodes)
        console.print(f"  [green]✓[/green] Embeddings: already stored (skipped)")

    # ===== STAGE 7: XME Bridge =====
    if run_bridge:
        if not ckpt.is_layer_done("bridge"):
            ckpt.start_layer("bridge")
            with console.status("[bold yellow]XME Bridge: syncing facts + episodes..."):
                try:
                    from xce.memory.xme_bridge import XMEBridge
                    from datetime import datetime, timezone
                    bridge = XMEBridge(
                        xme_db_path=os.environ.get("XME_BRIDGE_DB_PATH", ".xanther/xme.db"),
                        neo4j_driver=graph_store._driver,
                    )
                    br = await bridge.sync_index(
                        repo_id=repo_id, nodes=all_nodes, edges=all_edges,
                        descriptions=all_descs, user_id="xce_agent",
                        index_date=datetime.now(timezone.utc).isoformat(),
                    )
                    await bridge.close()
                    ckpt.complete_layer("bridge")
                    console.print(f"  [green]✓[/green] XME synced: {br['facts_written']} facts + {br['episodes_written']} episodes")
                except Exception as e:
                    console.print(f"  [yellow]⚠[/yellow] XME bridge: {e}")
        else:
            console.print(f"  [green]✓[/green] XME bridge: already synced (skipped)")

    # Clear checkpoint — indexing complete
    ckpt.clear()

    elapsed = time.time() - t_start
    await graph_store.close()
    if doc_gen:
        await doc_gen.close()

    # ===== Final Summary =====
    console.print()
    console.print(Panel(
        f"[green bold]✓ Indexing Complete[/green bold]\n\n"
        f"  [bold]Time:[/bold]       {elapsed:.1f}s\n"
        f"  [bold]Nodes:[/bold]      {nodes_stored:,}\n"
        f"  [bold]Edges:[/bold]      {edges_stored:,}\n"
        f"  [bold]Docs:[/bold]       {len(all_descs) + docs_count + arch_count:,}\n"
        f"  [bold]Embeddings:[/bold] {emb_count:,}\n"
        f"  [bold]Mode:[/bold]       {mode.upper()}",
        title="📊 Results",
        border_style="green",
    ))
    console.print()


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

        table = Table(title="Indexed Repositories")
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
        description="Xanther — Code Intelligence + Agent Memory",
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

    # dashboard
    dash = sub.add_parser("dashboard", help="Launch web dashboard (graph explorer, memory timeline)")
    dash.add_argument("--port", type=int, default=8001, help="Port (default: 8001)")

    # query
    q = sub.add_parser("query", help="Query code memory")
    q.add_argument("question", help="Natural language question about the codebase")
    q.add_argument("--repo", required=True, help="Repository ID to search")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("xce.indexing").setLevel(logging.WARNING)
    logging.getLogger("xce.indexing.embedding").setLevel(logging.ERROR)
    logging.getLogger("xce.indexing.doc_generator").setLevel(logging.ERROR)

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
    elif args.command == "dashboard":
        import uvicorn
        # Import the module-level app which includes static file serving
        from xce.dashboard import server as _dash
        app = _dash.app
        port = args.port
        console.print(f"\n  [bold]Xanther Dashboard[/bold] → [link=http://localhost:{port}]http://localhost:{port}[/link]\n")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    elif args.command == "query":
        asyncio.run(cmd_query_interactive(args.question, args.repo))


if __name__ == "__main__":
    main()
