# Xanther XCE + XME — Repo Testing Plan

**Goal:** Determine empirically where XCE adds value on top of XME, and where XME alone is sufficient.  
**Comparison axis:** Answer quality from a small model (Qwen 2.5 7B or equivalent) under three conditions:
- `Baseline` — no context, raw question to model
- `XME only` — episodic + fact memory, no code graph
- `XCE + XME` — full stack with structural graph, Layers 2-4

---

## Scoring System

Each answer is scored 0–3:

| Score | Meaning |
|---|---|
| 0 | Hallucinated or completely wrong |
| 1 | Partially correct, missing key detail |
| 2 | Correct but imprecise or verbose |
| 3 | Correct, specific, traceable to actual code |

Aggregate: sum across all questions per repo, compare `XME only` vs `XCE + XME`.

---

## Test Repos

### Repo 1: `tiangolo/fastapi` — Architecture traversal test
**Why:** Clean layered architecture (routers → deps → models → DB). Well-known so answers are verifiable.  
**Size:** ~15k LOC Python  
**Clone:** `git clone --depth 1 https://github.com/tiangolo/fastapi`

**Questions:**
1. Which function is called when a 422 validation error is raised, and what file is it in?
2. What is the call path from `app.get("/items")` to the actual route handler function?
3. How does FastAPI inject dependencies — trace the call chain from request to dependency function.
4. What would break if you changed the signature of `Request.state`?
5. Show every place in the codebase where authentication is checked.

**What discriminates XCE:** Questions 1, 2, 3 require multi-hop graph traversal. XME alone returns keyword matches; XCE returns the actual call chain.

---

### Repo 2: `celery/celery` — Complex architecture + small model stress test
**Why:** Non-obvious internal flow. Brokers, backends, workers, tasks, canvas primitives. Even experienced engineers struggle with this. Perfect for testing if Layer 4 ArchitectureDocs help.  
**Size:** ~80k LOC Python  
**Clone:** `git clone --depth 1 https://github.com/celery/celery`

**Questions:**
1. How does a `chord` result get aggregated once all subtasks complete?
2. What is the execution path from `task.delay()` to the message appearing in the broker?
3. How does Celery know which worker should pick up a task?
4. What's the difference between `apply_async` and `delay` at the implementation level?
5. Which module is responsible for serializing task arguments, and what formats are supported?

**What discriminates XCE:** Layer 4 ArchitectureDocs should pre-explain the broker/backend/worker architecture in plain language, helping small models answer Q1, Q3 without reading 30 files.

---

### Repo 3: `encode/httpx` — Middleware/transport chain test
**Why:** Clear middleware chain with transport layer. Good for testing impact analysis.  
**Size:** ~8k LOC Python  
**Clone:** `git clone --depth 1 https://github.com/encode/httpx`

**Questions:**
1. How does a timeout get applied to a request — trace from `client.get(timeout=5)` to the socket call.
2. What runs between `client.send()` and the actual network I/O?
3. How does httpx handle redirects — which class/function controls the redirect loop?
4. What is the impact of changing `AsyncHTTPTransport._send`?
5. How does connection pooling work — which class manages the pool?

**What discriminates XCE:** Q4 is pure impact analysis (fan-in traversal). Q1, Q2 require call chain tracing XME cannot do.

---

### Repo 4: `expressjs/express` — JavaScript/TypeScript parser test
**Why:** Tests XCE's JS parser. Also well-understood so answers are verifiable.  
**Size:** ~3k LOC JS  
**Clone:** `git clone --depth 1 https://github.com/expressjs/express`

**Questions:**
1. How does middleware get applied to a route — trace `app.use()` to execution order.
2. What is called between `req` arriving and `next()` being invoked?
3. How does Express handle errors thrown inside route handlers?
4. What does `Router.prototype.route` actually do?
5. How does `res.json()` differ from `res.send()` at the implementation level?

**What discriminates XCE:** Tests JS parser quality. If XCE's JS parsing is weak, this will show it.

---

### Repo 5: `pallets/flask` — Knowledge-update test (episodic memory value)
**Why:** Flask has a well-documented history of changes (before/after_request, context vars, app factory pattern). Good for testing XME's episodic value: if we record agent sessions working on Flask, do later sessions benefit?  
**Size:** ~20k LOC Python  
**Clone:** `git clone --depth 1 https://github.com/pallets/flask`

**Questions (Round 1 — before any agent sessions recorded):**
1. How does `before_request` get called before a route handler?
2. How does Flask manage the application context vs request context?
3. What is the execution order when multiple blueprints register the same route?
4. How does `g` work — where is it stored and when is it cleared?
5. What happens if an exception is raised inside a `teardown_request` handler?

**Round 2 — after recording 3 agent sessions with answers about Flask:**  
Ask the same questions and measure if XME's episodic memory improves answer quality from the small model.

**What discriminates XME:** This repo specifically tests the episodic memory value proposition. If XME's recorded sessions meaningfully improve answers in Round 2, that's the clearest demonstration of what Graphify doesn't have.

---

## Test Execution Steps

### Setup (one time)

```bash
# Clone repos to a test directory
mkdir -p ~/xanther-test-repos && cd ~/xanther-test-repos
git clone --depth 1 https://github.com/tiangolo/fastapi
git clone --depth 1 https://github.com/celery/celery
git clone --depth 1 https://github.com/encode/httpx
git clone --depth 1 https://github.com/expressjs/express
git clone --depth 1 https://github.com/pallets/flask
```

### For each repo, run two indexing modes:

```bash
# Mode A: XME only (fast, no LLM docs, just AST + memory sync)
XME_BRIDGE_ENABLED=true python -m xce index ~/xanther-test-repos/fastapi \
  --repo-id fastapi-xme-only --mode xme

# Mode B: Full XCE + XME (all 4 layers + memory sync)
XME_BRIDGE_ENABLED=true python -m xce index ~/xanther-test-repos/fastapi \
  --repo-id fastapi-full --mode full
```

### For each mode, run the question set through the CodeMemory interface:

```python
from xce.memory.code_memory import CodeMemory
from neo4j import AsyncGraphDatabase
import asyncio

async def test_questions(repo_id, questions):
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "..."))
    mem = CodeMemory(neo4j_driver=driver, xme_db_path=".xanther/xme.db")
    await mem.init()
    
    results = []
    for q in questions:
        ctx = await mem.query(q, repo_id=repo_id)
        results.append({"question": q, "context_chars": len(ctx["context_str"]), "context": ctx["context_str"]})
    
    await mem.close()
    await driver.close()
    return results
```

Then feed each context + question to the small model and record the answer.

---

## Evaluation Criteria

After running all repos, answer:

| Question | Expected outcome |
|---|---|
| Do XCE's call chains improve Q1-Q2 style structural questions? | Should score 3 vs XME's 1-2 |
| Does Layer 4 ArchitectureDoc help the small model on Celery? | Should score 2-3 vs XME's 0-1 |
| Does XME's episodic memory improve Flask Round 2? | Should score 2-3 vs Round 1's 1 |
| Does XCE JS parsing work on Express? | Depends on parser quality |
| Is XME-only sufficient for simple factual questions? | Likely yes — XCE adds no value there |

---

## What We're Looking For

**XCE is worth the indexing cost if:**
- Structural traversal questions (call chains, impact analysis) score ≥2 higher than XME-only
- Layer 4 docs help small models answer architecture questions they'd otherwise hallucinate

**XME alone is sufficient if:**
- Most questions are factual lookups (what is X, what does Y return)
- The codebase is small enough to fit in context
- The agent is using a frontier model (GPT-4o, Claude 3.5)

**The episodic memory value is proven if:**
- Flask Round 2 scores meaningfully higher than Round 1
- That's the clearest differentiation from Graphify

---

## Output

Results go in `docs/test-results/` as `{repo}-{mode}-results.md` with:
- Question
- Context retrieved (first 500 chars)
- Model answer
- Score (0-3)
- Notes on what the context contained / missed
