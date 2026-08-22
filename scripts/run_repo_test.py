#!/usr/bin/env python3
"""
Xanther Repo Test Harness
=========================
Runs the standard question set against a repo in two modes (xme-only vs full)
and produces a markdown results file.

Usage:
    python scripts/run_repo_test.py --repo fastapi --mode xme
    python scripts/run_repo_test.py --repo fastapi --mode full
    python scripts/run_repo_test.py --repo fastapi --mode all   # runs both, writes comparison

Repos: fastapi | celery | httpx | express | flask
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Adjust paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Question sets per repo
# ---------------------------------------------------------------------------

QUESTIONS: dict[str, list[str]] = {
    "fastapi": [
        "Which function is called when a 422 validation error is raised, and what file is it in?",
        "What is the call path from app.get('/items') to the actual route handler function?",
        "How does FastAPI inject dependencies — trace the call chain from request to dependency function.",
        "What would break if you changed the signature of Request.state?",
        "Show every place in the codebase where authentication is checked.",
    ],
    "celery": [
        "How does a chord result get aggregated once all subtasks complete?",
        "What is the execution path from task.delay() to the message appearing in the broker?",
        "How does Celery know which worker should pick up a task?",
        "What is the difference between apply_async and delay at the implementation level?",
        "Which module is responsible for serializing task arguments, and what formats are supported?",
    ],
    "httpx": [
        "How does a timeout get applied to a request — trace from client.get(timeout=5) to the socket call.",
        "What runs between client.send() and the actual network I/O?",
        "How does httpx handle redirects — which class controls the redirect loop?",
        "What is the impact of changing AsyncHTTPTransport._send?",
        "How does connection pooling work — which class manages the pool?",
    ],
    "express": [
        "How does middleware get applied to a route — trace app.use() to execution order.",
        "What is called between req arriving and next() being invoked?",
        "How does Express handle errors thrown inside route handlers?",
        "What does Router.prototype.route actually do?",
        "How does res.json() differ from res.send() at the implementation level?",
    ],
    "flask": [
        "How does before_request get called before a route handler?",
        "How does Flask manage the application context vs request context?",
        "What is the execution order when multiple blueprints register the same route?",
        "How does g work — where is it stored and when is it cleared?",
        "What happens if an exception is raised inside a teardown_request handler?",
    ],
}

REPO_URLS = {
    "fastapi": "https://github.com/tiangolo/fastapi",
    "celery":  "https://github.com/celery/celery",
    "httpx":   "https://github.com/encode/httpx",
    "express": "https://github.com/expressjs/express",
    "flask":   "https://github.com/pallets/flask",
}

# ---------------------------------------------------------------------------
# Core test runner
# ---------------------------------------------------------------------------

async def run_test(repo_name: str, mode: str) -> list[dict]:
    """Index repo in given mode and run question set. Returns list of result dicts."""
    repo_dir = Path(os.path.expanduser("~/xanther-test-repos")) / repo_name
    if not repo_dir.exists():
        print(f"  Repo not found at {repo_dir} — run setup first")
        sys.exit(1)

    repo_id = f"{repo_name}-{mode}"
    xme_db = str(ROOT / f".xanther/test_{repo_id}.db")

    # Set env for mode
    os.environ["XME_BRIDGE_ENABLED"] = "true"
    os.environ["XME_BRIDGE_DB_PATH"] = xme_db

    if mode == "xme":
        # xme-only: no LLM docs
        os.environ["XCE_DEEP_DOCS"] = "false"
        os.environ["XCE_ARCH_DOCS"] = "false"
    else:
        # full: all layers
        os.environ["XCE_DEEP_DOCS"] = "true"
        os.environ["XCE_ARCH_DOCS"] = "true"

    # Step 1: Index
    print(f"\n{'='*60}")
    print(f"  Indexing {repo_name} [{mode.upper()} mode]")
    print(f"  repo_id: {repo_id}")
    print(f"  xme_db:  {xme_db}")
    print(f"{'='*60}")

    from xce.config import get_settings
    from xce.graph.store import GraphStore
    from xce.indexing.indexer import index_repository
    from xce.indexing.doc_generator import DocGenerator
    from xce.indexing.embedding import EmbeddingService

    settings = get_settings()
    graph_store = GraphStore(
        neo4j_uri=settings.neo4j.uri,
        neo4j_auth=settings.neo4j.auth,
        embedding_dimensions=settings.embedding.dimensions,
    )
    await graph_store.init_schema()

    doc_gen = DocGenerator(api_key=settings.openrouter_api_key or settings.kimi_api_key)
    embed_svc = EmbeddingService(
        api_key=settings.openrouter_api_key,
        model=settings.embedding.model,
        dimensions=settings.embedding.dimensions,
    )

    t0 = time.time()
    active_doc_gen = doc_gen if mode == "full" else None
    result, _ = await index_repository(
        str(repo_dir), repo_id,
        doc_generator=active_doc_gen,
        embedding_service=embed_svc,
        graph_store=graph_store,
        incremental=False,
        smart_docs=True,
    )
    index_time = time.time() - t0
    print(f"  ✓ Indexed in {index_time:.1f}s — nodes={result.nodes_count} edges={result.edges_count} docs={result.docs_count}")

    await graph_store.close()

    # Step 2: Query each question via CodeMemory
    from xce.memory.code_memory import CodeMemory
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(settings.neo4j.uri, auth=settings.neo4j.auth)
    mem = CodeMemory(
        neo4j_driver=driver,
        xme_db_path=xme_db,
    )
    await mem.init()

    questions = QUESTIONS[repo_name]
    results = []

    print(f"\n  Running {len(questions)} questions...")
    for i, q in enumerate(questions, 1):
        ctx_result = await mem.query(q, repo_id=repo_id)
        facts_count = len(ctx_result["facts"])
        episodes_count = len(ctx_result["episodes"])
        ctx_preview = ctx_result["context_str"][:400]

        results.append({
            "question_num": i,
            "question": q,
            "facts_retrieved": facts_count,
            "episodes_retrieved": episodes_count,
            "context_preview": ctx_preview,
            "context_len": len(ctx_result["context_str"]),
            "full_context": ctx_result["context_str"],
        })
        print(f"  Q{i}: {facts_count} facts + {episodes_count} episodes retrieved")

    await mem.close()
    await driver.close()

    return results, {
        "repo": repo_name,
        "mode": mode,
        "repo_id": repo_id,
        "index_time_s": round(index_time, 1),
        "nodes": result.nodes_count,
        "edges": result.edges_count,
        "docs": result.docs_count,
        "embeddings": result.embeddings_count,
    }


def write_results(repo_name: str, mode: str, questions_results: list[dict], stats: dict) -> Path:
    """Write a markdown results file."""
    out_dir = ROOT / "docs" / "test-results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{repo_name}-{mode}-results.md"

    lines = [
        f"# {repo_name} — {mode.upper()} mode results",
        f"",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Index time:** {stats['index_time_s']}s  ",
        f"**Nodes:** {stats['nodes']} | **Edges:** {stats['edges']} | **Docs:** {stats['docs']} | **Embeddings:** {stats['embeddings']}",
        f"",
        f"---",
        f"",
    ]

    for r in questions_results:
        lines += [
            f"## Q{r['question_num']}: {r['question']}",
            f"",
            f"**Facts retrieved:** {r['facts_retrieved']}  ",
            f"**Episodes retrieved:** {r['episodes_retrieved']}  ",
            f"**Context length:** {r['context_len']} chars",
            f"",
            f"**Context preview:**",
            f"```",
            r['context_preview'],
            f"```",
            f"",
            f"**Score (0-3):** _[ fill in after testing with model ]_",
            f"",
            f"**Model answer:** _[ fill in ]_",
            f"",
            f"**Notes:** _[ what was correct / wrong / missing ]_",
            f"",
            f"---",
            f"",
        ]

    out_path.write_text("\n".join(lines))
    print(f"\n  ✓ Results written to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Xanther repo test harness")
    parser.add_argument("--repo", required=True, choices=list(QUESTIONS.keys()),
                        help="Which repo to test")
    parser.add_argument("--mode", required=True, choices=["xme", "full", "all"],
                        help="xme=memory only, full=XCE+XME, all=run both")
    args = parser.parse_args()

    # Check repo is cloned
    repo_dir = Path(os.path.expanduser("~/xanther-test-repos")) / args.repo
    if not repo_dir.exists():
        url = REPO_URLS[args.repo]
        print(f"Repo not found. Clone it first:")
        print(f"  git clone --depth 1 {url} ~/xanther-test-repos/{args.repo}")
        sys.exit(1)

    modes = ["xme", "full"] if args.mode == "all" else [args.mode]

    for mode in modes:
        q_results, stats = asyncio.run(run_test(args.repo, mode))
        write_results(args.repo, mode, q_results, stats)

    print(f"\n✓ Done. Results in docs/test-results/")
    if args.mode == "all":
        print(f"  Compare: {args.repo}-xme-results.md vs {args.repo}-full-results.md")


if __name__ == "__main__":
    main()
