# 🧠 Xanther — Code Intelligence + Agent Memory

**Open-source context engine for coding agents. 78.2% on SWE-bench Verified at $0.22/instance.**

Xanther combines structural code analysis (XCE) with persistent agent memory (XME) to give coding agents a shared, searchable understanding of your codebase that persists across sessions.

```bash
pip install xanther-xce
xanther index /path/to/repo
xanther query "how does auth work?" --repo my-repo
```

---

## Quick Start

### 1. Install

```bash
# From PyPI (recommended)
pip install xanther-xce

# Or from source
git clone https://github.com/Xanther-Ai/xanther-context-engine.git
cd xanther-context-engine
pip install -e .
```

### 2. Infrastructure (Neo4j required)

```bash
# Neo4j (knowledge graph + vector search)
docker run -d --name xce-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/xce_dev_password \
  neo4j:5-community
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — minimum needed:
#   NEO4J_PASSWORD=xce_dev_password
#   OPENROUTER_API_KEY=sk-or-...  (for LLM doc generation + embeddings)
```

### 4. Index a repo

```bash
# Fast mode — AST parse + memory sync only (30s)
xanther index /path/to/repo --mode xme

# Full mode — all 4 layers + memory sync (5-20 min, resumable)
xanther index /path/to/repo --mode full
```

### 5. Query

```bash
xanther query "how does the auth middleware handle JWT tokens?" --repo my-repo
```

### 6. Visualize

```bash
xanther dashboard
# → http://localhost:8001/graph.html
```

---

## E2E Setup Guide (Production)

### Prerequisites

| Component | Purpose | Install |
|-----------|---------|---------|
| Python 3.9+ | Runtime | `brew install python3` |
| Docker | Neo4j container | [docker.com](https://docker.com) |
| Neo4j 5.x | Graph + vector storage | Via Docker (see below) |
| OpenRouter API key | Embeddings + LLM docs | [openrouter.ai](https://openrouter.ai) |

### Step-by-Step Setup

```bash
# 1. Install Xanther
pip install xanther-xce

# 2. Start Neo4j
docker run -d --name xce-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/xce_dev_password \
  -v xce_neo4j_data:/data \
  neo4j:5-community

# 3. Set environment variables
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=xce_dev_password
export OPENROUTER_API_KEY=sk-or-v1-your-key-here

# 4. Index your repository
xanther index ~/Projects/my-app --mode full

# 5. Verify
xanther status
```

### With XME (Cross-Session Memory)

For full memory capabilities, also install the [Xanther Memory Engine](https://github.com/Xanther-Ai/xanther-memory-engine):

```bash
# Clone XME alongside XCE
git clone https://github.com/Xanther-Ai/xanther-memory-engine.git

# XCE auto-detects XME if it's a sibling directory
# Memory features are then available automatically
```

### Python API (Programmatic Setup)

```python
from xce.memory.setup import XCESetup

async def main():
    # One-liner setup (reads from env vars)
    xce = await XCESetup.create("/path/to/repo", repo_id="my-repo")

    # Query codebase
    ctx = await xce.query("how does auth work?")
    print(ctx["context_str"])  # LLM-ready context

    # Record what you learned
    await xce.record("fixed auth bug in middleware", files=["src/auth.py"])

    # Record architectural decisions
    await xce.decide("Use JWT for stateless auth", rationale="Scales horizontally")

    # Search past actions (cross-session memory)
    past = await xce.search_episodes("auth middleware fix")

    await xce.close()
```

### MCP Server (for Kiro, Claude Code, Cursor)

```bash
# Start as MCP server (stdio)
xce serve

# Start as SSE server (HTTP)
xce serve --sse --port 8000
```

Add to your IDE's MCP config:
```json
{
  "mcpServers": {
    "xanther-xce": {
      "command": "xce",
      "args": ["serve"]
    }
  }
}
```

### Auto-Recording Hooks (XME Memory)

Install hooks to automatically record agent actions into XME memory. Every turn, tool call, and session end is captured for cross-session recall.

```bash
# Install hooks for Kiro + Claude Code
xce memory hooks install /path/to/repo

# Preview what would be installed (dry run)
xce memory hooks install /path/to/repo --dry-run

# Remove hooks
xce memory hooks uninstall /path/to/repo
```

**What gets installed:**

| Hook | Event | What it records |
|------|-------|----------------|
| `xme-session-end` | `agentStop` | Flush journal, compact, save session |
| `xme-record-turn` | `promptSubmit` | User turn in journal |
| `xme-record-tool` | `postToolUse` | Tool calls in journal |

**Or via Python API:**

```python
from xce.memory.setup import XCESetup

xce = await XCESetup.create("/path/to/repo")
xce.install_hooks()  # Installs Kiro + Claude Code hooks
```

After installation, every agent session automatically builds cross-session memory — no manual recording needed.

---

## Indexing Modes

| Mode | Time | What it does | When to use |
|------|------|-------------|-------------|
| `xme` | 30-60s | AST parse + embeddings + XME memory sync | Quick iteration, memory-focused |
| `full` | 5-20min | All 4 layers + embeddings + memory | First-time deep index |
| `xce` | 5-20min | Code graph only, no memory sync | Pure code intelligence |

### Indexing Layers Explained

```
Layer 1: AST Parse (tree-sitter)
  → Classes, functions, methods, imports
  → All languages: Python, TS, JS, Go, Rust, Java, Kotlin, C#, Ruby, Swift, C, C++
  → ~30 seconds for most repos

Layer 2: Component Summaries (LLM)
  → One-sentence description of each function/class
  → Dependencies and responsibilities
  → ~2-5 minutes

Layer 3: Detailed Documentation (LLM)
  → Algorithm descriptions, data flow, error handling, edge cases
  → Parallelized (10 workers by default, set XCE_LAYER3_WORKERS)
  → ~5-10 minutes

Layer 4: Architecture (LLM)
  → High-level design per module
  → Design patterns, integration points, quality attributes
  → ~2-5 minutes

Embeddings: Vector Encoding (OpenRouter)
  → 512-dimensional vectors for each node
  → Enables semantic search via Neo4j vector index
  → ~1-2 minutes
```

### Incremental & Resumable

```bash
# Only re-index changed files (default)
xanther index /path/to/repo

# Force full re-index
xanther index /path/to/repo --full

# Only git-changed files
xanther index /path/to/repo --diff

# If interrupted (Ctrl+C), just re-run — picks up where it left off
xanther index /path/to/repo --mode full
```

### Smart Docs (Cost Optimization)

By default, Xanther skips generating LLM docs for trivial nodes (one-liners, getters/setters). This reduces LLM cost ~80% with minimal quality loss.

```bash
# Default (smart filtering ON)
xanther index /path/to/repo --mode full

# Generate docs for ALL nodes (slower, more expensive)
xanther index /path/to/repo --mode full --no-smart-docs
```

---

## CLI Commands

```bash
xanther index <path>              # Index a repository
xanther index <path> --mode xme   # Fast: AST + memory only (no LLM)
xanther index <path> --mode full  # Full: all layers + memory
xanther index <path> --mode xce   # XCE only (no memory sync)
xanther index <path> --diff       # Only index git-changed files
xanther index <path> --full       # Force re-index (no incremental)

xanther status                    # Show all indexed repositories
xanther dashboard                 # Launch graph visualization UI
xanther dashboard --port 8080     # Custom port

xanther query "question" --repo flask  # Query code memory
```

---

## Benchmarks (SWE-bench Verified)

| Model | Configuration | Resolve Rate | Cost/Instance |
|-------|--------------|--------------|---------------|
| Sonnet 4.0 (baseline) | mini-swe-agent | 66% | $1.50 |
| Sonnet 4.0 + XCE | Resolve@1 | **73.4%** | $1.20 |
| MiniMax M2.5 + XCE | SWE-bench Verified | **78.2%** | **$0.22** |
| Claude 4.5 Opus | Leaderboard | 76.8% | $8.50 |

**8,427 XCE tool calls** across 499 instances. Full results: [xanther.ai/benchmarks](https://xanther.ai/benchmarks/)

---

```
┌─────────────────────────────────────────────────────────┐
│                    xanther CLI                           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  XCE (Code Intelligence)         XME (Agent Memory)     │
│  ├─ Layer 1: AST Parse           ├─ Episodic Store      │
│  │  (tree-sitter, all langs)     │  (sessions, actions) │
│  ├─ Layer 2: Summaries           ├─ Fact Graph          │
│  │  (LLM descriptions)           │  (Neo4j temporal)    │
│  ├─ Layer 3: Detailed Docs       └─ Context Layer       │
│  │  (algorithm, data flow)          (live UPSERT)       │
│  ├─ Layer 4: Architecture                               │
│  │  (HLD per module)                                    │
│  └─ Embeddings (vector search)                          │
│                                                         │
│  XME Bridge: syncs code facts → memory                  │
│  CodeMemory: unified query interface                    │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Storage: Neo4j (graph) + SQLite (episodes) + OpenSearch│
│  Dashboard: localhost:8001/graph.html (vis-network)      │
└─────────────────────────────────────────────────────────┘
```

## Graph Visualization

The dashboard at `/graph.html` provides:

- **Interactive force-directed graph** of your codebase
- **Layer toggles:** L1 (AST) → L2 (Descriptions) → L3 (Docs) → L4 (Architecture)
- **Code Facts** — structural knowledge from indexing
- **Agent Memory** — decisions and actions from agent sessions
- **Color by Module** — clusters files by directory
- **Hierarchy view** — top-down L4→L3→L2→L1 layout
- **Search** — find and focus on any symbol
- **Click** any node for detailed info panel

---

## Supported Languages

Python, TypeScript, JavaScript, Go, Rust, Java, Kotlin, C#, Ruby, Swift, C, C++

---

## Environment Variables

See `.env.example` for full documentation. Key ones:

```bash
# Required
NEO4J_PASSWORD=xce_dev_password
OPENROUTER_API_KEY=sk-or-...       # for doc generation + embeddings

# Optional
XCE_DEEP_DOCS=true                 # Layer 3 (default: on)
XCE_ARCH_DOCS=true                 # Layer 4 (default: on)
XME_BRIDGE_ENABLED=true            # XME memory sync (default via --mode)
XCE_LLM_PROVIDER=openrouter        # force OpenRouter over AWS Bedrock
```

---

## API (for integrations)

When the dashboard is running:

```bash
GET /api/graph/repos                          # list indexed repos
GET /api/graph/nodes?repo_id=flask&limit=500  # AST nodes
GET /api/graph/edges?repo_id=flask&limit=1000 # edges (CALLS, IMPORTS, INHERITS)
GET /api/graph/layers?repo_id=flask&limit=300 # all layers (L1-L4 + memory)
```

---

## Project Structure

```
xce/
├── cli/interactive.py      # xanther CLI (index, status, dashboard, query)
├── indexing/
│   ├── indexer.py          # multi-layer indexing pipeline
│   ├── checkpoint.py       # resumable progress tracking
│   ├── doc_generator.py    # LLM doc generation (Layers 2-4)
│   └── embedding.py        # vector encoding
├── parsers/                # tree-sitter language parsers
├── graph/store.py          # Neo4j graph operations
├── memory/
│   ├── xme_bridge.py       # XCE → XME fact sync
│   └── code_memory.py      # unified query interface
├── dashboard/
│   ├── server.py           # FastAPI backend (30 routes)
│   ├── static/graph.html   # standalone graph visualization
│   └── ui/                 # React frontend (legacy)
└── models.py               # ASTNode, ComponentDesc, ArchitectureDoc
```

---

## License

MIT

## Links

- **Website:** [xanther.ai](https://xanther.ai)
- **Benchmarks:** [xanther.ai/benchmarks](https://xanther.ai/benchmarks/)
- **XCE (this repo):** [github.com/Xanther-Ai/xanther-context-engine](https://github.com/Xanther-Ai/xanther-context-engine)
- **XME (memory engine):** [github.com/Xanther-Ai/xanther-memory-engine](https://github.com/Xanther-Ai/xanther-memory-engine)
- **PyPI:** [pypi.org/project/xanther-xce](https://pypi.org/project/xanther-xce/) *(coming soon)*
