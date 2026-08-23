# 🧠 Xanther — Code Intelligence + Agent Memory

**One command to map your codebase into a queryable knowledge graph with multi-layer visualization.**

Xanther combines structural code analysis (XCE) with persistent agent memory (XME) to give coding agents a shared, searchable understanding of your codebase that persists across sessions.

```bash
pip install -e .
xanther index /path/to/repo
xanther dashboard
# → open http://localhost:8001/graph.html
```

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/Xanther-Ai/xanther-context-engine.git
cd xanther-context-engine
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Infrastructure (Neo4j required)

```bash
# Neo4j (knowledge graph storage)
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/xce_dev_password \
  neo4j:5
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — minimum needed:
#   NEO4J_PASSWORD=xce_dev_password
#   OPENROUTER_API_KEY=sk-or-...  (for LLM doc generation)
```

### 4. Index a repo

```bash
# Fast mode — AST parse + memory sync only (30s)
xanther index /path/to/repo --mode xme

# Full mode — all 4 layers + memory sync (5-20 min, resumable)
xanther index /path/to/repo --mode full
```

### 5. Visualize

```bash
xanther dashboard
# → http://localhost:8001/graph.html
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

### Indexing Modes

| Mode | Time | What it does | When to use |
|------|------|-------------|-------------|
| `xme` | 30-60s | AST parse + embeddings + XME memory sync | Quick iteration, memory-focused |
| `full` | 5-20min | All 4 layers + embeddings + memory | First-time deep index |
| `xce` | 5-20min | Code graph only, no memory sync | Pure code intelligence |

### Resumable Indexing

If you Ctrl+C during `--mode full`, progress is saved. Restart the same command and it picks up from where it left off — no wasted LLM calls.

---

## Architecture

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

Apache 2.0

## Links

- **XCE (this repo):** https://github.com/Xanther-Ai/xanther-context-engine
- **XME (memory engine):** https://github.com/Xanther-Ai/xanther-memory-engine
