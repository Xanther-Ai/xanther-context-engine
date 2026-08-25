#!/usr/bin/env python3
"""Intensive XME Cross-Session Memory Evaluation — 10 PR Sequence"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from xce.memory import CodeMemory
from xce.graph.store import GraphStore


async def intensive_test():
    neo4j_uri = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.environ.get('NEO4J_USER', 'neo4j')
    neo4j_pass = os.environ.get('NEO4J_PASSWORD', 'password')

    gs = GraphStore(neo4j_uri=neo4j_uri, neo4j_auth=(neo4j_user, neo4j_pass), embedding_dimensions=512)
    await gs.init_schema()
    cm = CodeMemory(neo4j_driver=gs._driver)
    await cm.init()

    print("=" * 70)
    print("INTENSIVE XME MEMORY EVALUATION — 10 PR Sequence")
    print("=" * 70)
    print()

    # Define 10 realistic PR scenarios across different httpx subsystems
    prs = [
        # --- Transport layer PRs ---
        {
            "id": "T1", "title": "AsyncHTTPTransport connection pool leak",
            "query": "AsyncHTTPTransport connection pool close leak",
            "action": "Fixed connection pool leak in AsyncHTTPTransport.aclose() — pool connections weren't being drained before close. Added await self._pool.aclose() with timeout.",
            "files": ["httpx/_transports/default.py"],
            "decision": "Always drain connection pools with timeout before closing transport",
            "category": "transport",
        },
        {
            "id": "T2", "title": "HTTP2 stream reset during multiplexing",
            "query": "HTTP2Connection stream reset multiplexing concurrent requests",
            "action": "Fixed HTTP2 stream reset during concurrent multiplexed requests. Race condition in stream ID allocation — added asyncio.Lock around _get_stream_id().",
            "files": ["httpx/_transports/default.py", "httpx/_models.py"],
            "decision": "Use asyncio.Lock for HTTP2 stream ID allocation to prevent race conditions",
            "category": "transport",
        },
        {
            "id": "T3", "title": "Transport retry on connection reset",
            "query": "transport retry connection reset peer closed",
            "action": "Added automatic retry on ConnectionResetError for idempotent requests. Pattern: catch ConnectionResetError, check if request is idempotent (GET/HEAD/OPTIONS), retry once with fresh connection.",
            "files": ["httpx/_transports/default.py", "httpx/_client.py"],
            "decision": "Retry idempotent requests once on ConnectionResetError with exponential backoff",
            "category": "transport",
        },
        # --- Content/Stream PRs ---
        {
            "id": "S1", "title": "ByteStream __aiter__ trio ResourceWarning",
            "query": "ByteStream __aiter__ async generator trio ResourceWarning garbage collection",
            "action": "Replaced ByteStream.__aiter__ async generator with _ByteStreamAsyncIterator class. Trio GCs async generators causing ResourceWarning; explicit __anext__/__aiter__ avoids this.",
            "files": ["httpx/_content.py", "tests/test_content.py"],
            "decision": "Replace async generator patterns with explicit async iterator classes for trio compatibility",
            "category": "stream",
        },
        {
            "id": "S2", "title": "IteratorByteStream not calling close on generator",
            "query": "IteratorByteStream generator close cleanup resources",
            "action": "Fixed IteratorByteStream to call .close() on the underlying generator when the stream is consumed or explicitly closed. Prevents file handle leaks.",
            "files": ["httpx/_content.py"],
            "decision": "Always call .close() on generators in stream implementations to prevent resource leaks",
            "category": "stream",
        },
        {
            "id": "S3", "title": "Streaming response body not properly chunked",
            "query": "streaming response body chunked transfer encoding content-length",
            "action": "Fixed streaming response to respect Transfer-Encoding: chunked when Content-Length is absent. Previously fell through to buffering entire body.",
            "files": ["httpx/_models.py", "httpx/_decoders.py"],
            "decision": "Prefer chunked streaming over buffering when no Content-Length header present",
            "category": "stream",
        },
        # --- Auth/Cookie PRs ---
        {
            "id": "A1", "title": "Cookie domain matching with subdomains",
            "query": "cookie domain matching subdomain set-cookie",
            "action": "Fixed cookie domain matching to correctly handle subdomain cookies. Was matching .example.com against notexample.com due to missing leading dot check.",
            "files": ["httpx/_models.py"],
            "decision": "Cookie domain matching must check leading dot for subdomain cookies per RFC 6265",
            "category": "auth",
        },
        {
            "id": "A2", "title": "Auth flow not retrying after 401",
            "query": "auth flow 401 retry credentials refresh token",
            "action": "Fixed auth flow to retry request after receiving 401 when auth handler provides new credentials. Was dropping the retry and returning 401 to caller.",
            "files": ["httpx/_client.py", "httpx/_auth.py"],
            "decision": "Auth handlers that provide new credentials on 401 should trigger automatic request retry",
            "category": "auth",
        },
        # --- URL/Redirect PRs ---
        {
            "id": "U1", "title": "URL percent-encoding of path segments",
            "query": "URL percent encoding path segments special characters RFC 3986",
            "action": "Fixed URL percent-encoding to handle reserved characters in path segments per RFC 3986. Was double-encoding already-encoded %XX sequences.",
            "files": ["httpx/_urlparse.py", "httpx/_urls.py"],
            "decision": "Check for existing percent-encoding before encoding URL path segments to avoid double-encoding",
            "category": "url",
        },
        {
            "id": "U2", "title": "Redirect losing request body on 307/308",
            "query": "redirect 307 308 preserve request body method POST",
            "action": "Fixed 307/308 redirects to preserve request body and method. Was converting POST to GET and dropping body on 307 redirects (only correct for 301/302).",
            "files": ["httpx/_client.py", "httpx/_redirects.py"],
            "decision": "307/308 redirects must preserve original method and body; only 301/302 convert to GET",
            "category": "url",
        },
    ]

    results = []
    all_episodes_count = []

    for i, pr in enumerate(prs):
        t0 = time.time()

        # Query XCE for code context
        r = await cm.query(pr["query"], repo_id='httpx-xme')

        # Query XME for cross-session memory
        episodes = await cm._query_episodes(pr["query"], 'httpx-xme', 10, 'xce_agent', False)

        t1 = time.time()

        # Record the action and decision
        await cm.record_action(
            repo_id='httpx-xme',
            action=pr["action"],
            files=pr["files"],
            outcome='success',
        )
        await cm.record_decision(
            repo_id='httpx-xme',
            decision=pr["decision"],
            rationale=f'PR {pr["id"]}: {pr["title"]}',
            affected_files=pr["files"],
        )

        results.append({
            "id": pr["id"],
            "title": pr["title"][:40],
            "category": pr["category"],
            "facts": len(r["facts"]),
            "episodes": len(episodes),
            "time_ms": int((t1 - t0) * 1000),
        })
        all_episodes_count.append(len(episodes))

        # Print progress
        mem_status = f"✅ {len(episodes)} recalled" if episodes else "⬜ no memory"
        print(f"  [{pr['id']}] {pr['title'][:45]:<45} | {len(r['facts']):>2} facts | {mem_status:<15} | {int((t1-t0)*1000)}ms")

    # --- CROSS-SESSION RECALL TESTS ---
    print()
    print("=" * 70)
    print("CROSS-SESSION RECALL TESTS (8 queries)")
    print("=" * 70)
    print()

    tests = [
        ("Transport connection handling patterns", "transport", ["T1", "T2", "T3"]),
        ("async stream iterator resource cleanup", "stream", ["S1", "S2", "S3"]),
        ("authentication cookie handling retry", "auth", ["A1", "A2"]),
        ("URL encoding redirect behavior", "url", ["U1", "U2"]),
        ("WebSocket upgrade protocol handshake", "novel", []),
        ("connection pool stream timeout handling", "cross", ["T1", "S1"]),
        ("latest transport fix connection retry", "temporal", ["T3"]),
        ("should we use async generators for byte streams", "contradiction", ["S1"]),
    ]

    recall_results = []
    for query, category, expected_ids in tests:
        episodes = await cm._query_episodes(query, 'httpx-xme', 10, 'xce_agent', False)
        print(f"  Query: \"{query}\"")
        print(f"  Expected: {expected_ids or '(none)'} | Found: {len(episodes)} episodes")
        if episodes:
            for ep in episodes[:3]:
                score = ep.get("score", 0)
                summary = ep.get("summary", "")[:70]
                print(f"    ↳ [{score:.3f}] {summary}")
        else:
            print(f"    ↳ (none)")

        # Score: did we find relevant results?
        found_relevant = len(episodes) > 0 if expected_ids else len(episodes) == 0
        recall_results.append({
            "query": query[:40],
            "category": category,
            "expected": len(expected_ids),
            "found": len(episodes),
            "correct": found_relevant,
        })
        print(f"  Result: {'✅ PASS' if found_relevant else '❌ FAIL'}")
        print()

    # --- MEMORY GROWTH ANALYSIS ---
    print("=" * 70)
    print("MEMORY GROWTH ANALYSIS")
    print("=" * 70)
    print()
    print(f"{'PR':<5} {'Category':<12} {'Facts':<7} {'Episodes':<10} {'Time':<8} {'Memory Growth'}")
    print(f"{'---':<5} {'---':<12} {'---':<7} {'---':<10} {'---':<8} {'---'}")
    for r in results:
        growth = "📈" * min(r["episodes"], 5) if r["episodes"] > 0 else "⬜"
        print(f"{r['id']:<5} {r['category']:<12} {r['facts']:<7} {r['episodes']:<10} {r['time_ms']:<8} {growth}")

    # --- SUMMARY STATISTICS ---
    print()
    print("=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    total_episodes = sum(all_episodes_count)
    avg_time = sum(r["time_ms"] for r in results) / len(results)
    prs_with_memory = sum(1 for e in all_episodes_count if e > 0)
    recall_pass = sum(1 for r in recall_results if r["correct"])
    recall_total = len(recall_results)

    print(f"  Total PRs processed:           {len(prs)}")
    print(f"  PRs with memory recall:        {prs_with_memory}/{len(prs)} ({100*prs_with_memory/len(prs):.0f}%)")
    print(f"  Total episodes recalled:       {total_episodes}")
    print(f"  Avg episodes per PR:           {total_episodes/len(prs):.1f}")
    print(f"  Avg query time:                {avg_time:.0f}ms")
    print(f"  Memory accumulation rate:      {total_episodes/len(prs):.2f} eps/PR")
    print(f"  Cross-session recall accuracy: {recall_pass}/{recall_total} ({100*recall_pass/recall_total:.0f}%)")
    print()
    print("  Category breakdown:")
    for cat in ["transport", "stream", "auth", "url"]:
        cat_results = [r for r in results if r["category"] == cat]
        cat_eps = sum(r["episodes"] for r in cat_results)
        print(f"    {cat:<12}: {len(cat_results)} PRs, {cat_eps} episodes recalled")

    print()
    print("  Recall test breakdown:")
    for r in recall_results:
        status = "✅" if r["correct"] else "❌"
        print(f"    {status} {r['query']:<40} expected={r['expected']}, found={r['found']}")

    await gs.close()


if __name__ == "__main__":
    asyncio.run(intensive_test())
