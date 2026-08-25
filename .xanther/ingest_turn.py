#!/usr/bin/env python3
"""Quick ingest a memory entry into XME with vector embeddings.

Usage:
    python .xanther/ingest_turn.py --action "fixed the graph tooltip width" --files "xce/dashboard/static/graph.html"
    python .xanther/ingest_turn.py --decision "split memory into code_facts vs agent_memory"
    python .xanther/ingest_turn.py --fact "Flask repo has 2895 AST nodes indexed"
"""
import asyncio
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_embedding_service():
    """Create EmbeddingService if API key is available."""
    try:
        from xce.indexing.embedding import EmbeddingService
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return None
        return EmbeddingService(
            api_key=api_key,
            model="openai/text-embedding-3-small",
            dimensions=512,
        )
    except Exception:
        return None


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", help="What was done (e.g. 'fixed tooltip width')")
    p.add_argument("--decision", help="Architectural decision made")
    p.add_argument("--fact", help="A fact to remember")
    p.add_argument("--files", help="Comma-separated files modified")
    p.add_argument("--repo-id", default="xanther-context-engine")
    args = p.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

    from xce.memory.code_memory import CodeMemory
    from neo4j import AsyncGraphDatabase

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD", "xce_dev_password")

    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    # Create embedding service for vector episode storage
    emb_svc = _get_embedding_service()

    mem = CodeMemory(
        neo4j_driver=driver,
        xme_db_path=".xanther/xme.db",
        embedding_service=emb_svc,
    )
    await mem.init()

    if args.action:
        files = args.files.split(",") if args.files else []
        ep_id = await mem.record_action(
            repo_id=args.repo_id,
            action=args.action,
            files=files,
            outcome="success",
        )
        print(f"✓ Action recorded: {args.action[:60]} (ep={ep_id})")

    if args.decision:
        await mem.record_decision(
            repo_id=args.repo_id,
            decision=args.decision,
            affected_files=args.files.split(",") if args.files else None,
        )
        print(f"✓ Decision recorded: {args.decision[:60]}")

    if args.fact:
        if mem._tfg:
            from datetime import datetime, timezone
            await mem._tfg.upsert_fact(
                user_id="xce_agent",
                attribute="project_fact",
                value=args.fact,
                fact_type="personal_fact",
                session_id=f"manual:{datetime.now().strftime('%Y%m%d')}",
                session_date=datetime.now(timezone.utc).isoformat(),
                embedding=None,
                project_id=args.repo_id,
            )
            print(f"✓ Fact recorded: {args.fact[:60]}")

    await mem.close()
    if emb_svc:
        await emb_svc.close()
    await driver.close()

asyncio.run(main())
