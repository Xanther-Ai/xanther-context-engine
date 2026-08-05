<div align="center">

# Xanther Context Engine (XCE)

**Architecture-aware code intelligence for AI coding assistants.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Tests](https://github.com/Xanther-Ai/xanther-context-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Xanther-Ai/xanther-context-engine/actions)

</div>

---

> On SWE-bench Verified: **MiniMax M2.5 + XCE scored 78.2%**, beating Claude Opus 4.5 (76.8%) at **16x lower cost**. Sonnet 4.0 + XCE went from 66% → 73.4%. The improvement comes entirely from better context, not a better model.

XCE turns any codebase into a **queryable knowledge graph** — functions, classes, imports, call edges, and full architecture layers — and serves it to AI agents via MCP. Works with Claude Code, Kiro, Cursor, Codex, and any MCP-compatible tool.

```bash
pip install xanther-context-engine
xce index . --repo-id my-project    # build the graph once
xce serve                           # start MCP server
```

One command. Your agent now navigates by structure instead of grepping through files.

---

## Benchmark Results

All on [SWE-bench Verified](https://www.swebench.com/) (500 instances) using mini-swe-agent:

| Setup | Resolve Rate | Cost/Instance | vs Baseline |
|-------|-------------|---------------|-------------|
| **MiniMax M2.5 + XCE** | **78.2%** | $0.22 | +2.4pp over Opus 4.5 at 16x lower cost |
| Claude 4.5 Opus (baseline) | 76.8% | $3.50 | — |
| MiniMax M2.5 (baseline) | 75.8% | $0.07 | — |
| **Sonnet 4.0 + XCE** | **73.4%** | $0.22 | +7.4pp over baseline |
| Sonnet 4.0 (baseline) | 66.0% | $0.22 | — |

Full benchmark data: [github.com/Xanther-Ai/xce-benchmarks](https://github.com/Xanther-Ai/xce-benchmarks)

```mermaid
xychart-beta
    title "SWE-bench Verified Resolve Rate (%)"
    x-axis ["Sonnet 4.0\nbaseline", "MiniMax M2.5\nbaseline", "Sonnet 4.0\n+ XCE", "Claude Opus 4.5\nbaseline", "MiniMax M2.5\n+ XCE"]
    y-axis "Resolve Rate (%)" 60 --> 80
    bar [66.0, 75.8, 73.4, 76.8, 78.2]
```

---

## Architecture

```mermaid
graph TB
    subgraph "Your Codebase"
        SRC[Source Files<br/>Python · TS · Go · Rust · Java · 10+ more]
        DOCS[Docs & Configs<br/>Markdown · OpenAPI · SQL]
    end

    subgraph "XCE PRAT Pipeline"
        direction LR
        L1[Layer 1<br/>AST Parsing<br/>tree-sitter]
        L2[Layer 2<br/>Component Descriptions<br/>LLM summaries]
        L3[Layer 3<br/>Component Docs<br/>Algorithm + data flow]
        L4[Layer 4<br/>Architecture Docs<br/>Module roles + patterns]
        L1 --> L2 --> L3 --> L4
    end

    subgraph "Knowledge Graph"
        NEO4J[(Neo4j<br/>ASTNodes · Edges<br/>ComponentDesc · ArchitectureDoc<br/>Vector Embeddings)]
    end

    subgraph "Serving Layer"
        MCP[MCP Server<br/>stdio · SSE]
        TOOLS[5 Tools<br/>architecture_context<br/>search · trace<br/>impact_analysis · index]
    end

    subgraph "AI Agents"
        CC[Claude Code]
        KIRO[Kiro]
        CURSOR[Cursor]
        CODEX[Codex]
    end

    SRC --> L1
    DOCS --> L1
    L4 --> NEO4J
    NEO4J --> MCP
    MCP --> TOOLS
    TOOLS --> CC & KIRO & CURSOR & CODEX
```

---

## Local Infrastructure

```mermaid
graph LR
    subgraph "Your Machine"
        subgraph "Docker Compose"
            N[(Neo4j:7687<br/>Graph + Vectors)]
            PG[(PostgreSQL:5432<br/>Incremental hashes)]
        end

        subgraph "XCE Process"
            IDX[xce index<br/>Parsing + LLM enrichment]
            SRV[xce serve<br/>MCP server stdio/SSE]
        end

        subgraph "IDE"
            MCP_CFG[mcp.json<br/>xce-mcp-server]
            AGENT[AI Agent]
        end
    end

    subgraph "External APIs (optional)"
        OR[OpenRouter API<br/>Embeddings + Doc generation]
    end

    IDX -- write nodes/edges --> N
    IDX -- write file hashes --> PG
    IDX -- incremental hash check --> PG
    SRV -- read graph --> N
    MCP_CFG -- spawn --> SRV
    AGENT -- MCP tool calls --> SRV
    IDX -. LLM calls .-> OR
```

---

## How it works — PRAT

PRAT (Persistent Recursive Abstract Tree) builds a multi-level structured index:

```mermaid
flowchart LR
    subgraph "Architecture Layer (HLD)"
        A[Module roles<br/>Design patterns<br/>Integration points<br/>Quality attributes]
    end
    subgraph "Component Layer (LLD)"
        B[Class/function summaries<br/>Algorithm descriptions<br/>Data flow<br/>Error handling]
    end
    subgraph "Code Layer (AST)"
        C[Functions · Classes<br/>Imports · Call edges<br/>Inheritance · Decorators]
    end
    C --> B --> A
```

The key difference from embedding-only search: PRAT captures **structural relationships**. Your agent can ask "what depends on this function?" and get a real traversal answer — not just semantically similar snippets.

---

## Four indexing layers

| Layer | What it produces | LLM? | Cost |
|-------|-----------------|------|------|
| 1 — AST Parsing | Functions, classes, imports, call edges | No | Free |
| 2 — Component Descriptions | 1-2 sentence summary per symbol | Yes | ~$0.002/file |
| 3 — Component Docs | Algorithm, data flow, error handling per function | Yes | ~$0.01/file |
| 4 — Architecture Docs | Module roles, design patterns, integration points | Yes | ~$0.05/module |

Use `--smart-docs` to skip trivial nodes (variables, tiny functions) — reduces cost ~80% with minimal quality loss.

---

## Quickstart

```bash
pip install xanther-context-engine
cp .env.example .env         # add NEO4J_PASSWORD + OPENROUTER_API_KEY
docker-compose up -d         # start Neo4j + PostgreSQL
xce index . --repo-id my-project --smart-docs
xce serve
```

Add to your MCP config (`~/.kiro/settings/mcp.json` or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "xce": {
      "command": "xce-mcp-server",
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_PASSWORD": "your-password",
        "OPENROUTER_API_KEY": "sk-or-..."
      }
    }
  }
}
```

Or remote SSE:
```json
{
  "mcpServers": {
    "xce": {
      "url": "http://localhost:8000/sse?repo_id=my-project"
    }
  }
}
```

Works with: **Claude Code, Kiro, Cursor, Windsurf, OpenCode, Cline**.

---

## MCP tools (5)

| Tool | Description |
|------|-------------|
| `xce_architecture_context` | Full architectural context for a file or symbol — role, callers, architectural layer |
| `xce_search` | Semantic + symbol search across the graph — finds by meaning, not just text |
| `xce_impact_analysis` | Blast radius — what breaks if you change this? Fan-in callers, test coverage |
| `xce_trace` | Trace from code → component description → architecture documentation |
| `xce_index_repo` | Trigger incremental re-index on changed files |

With [XME installed](https://github.com/Xanther-Ai/xanther-memory-engine), 11 additional memory tools are available automatically.

---

## Incremental indexing

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant XCE as xce index
    participant PG as PostgreSQL<br/>(file hashes)
    participant NEO4J as Neo4j

    Dev->>XCE: xce index . (second run)
    XCE->>PG: get stored file hashes
    PG-->>XCE: {file: sha256, ...}
    XCE->>XCE: compute current SHA-256s
    XCE->>XCE: diff → 3 changed, 97 unchanged
    XCE->>NEO4J: upsert only changed nodes/edges
    XCE->>PG: update hashes for changed files
    XCE-->>Dev: ✓ 3 files re-indexed (97 skipped)
```

---

## Language support

| Language | Extensions | Status |
|----------|-----------|--------|
| Python | `.py` | ✅ Stable |
| TypeScript / JavaScript | `.ts` `.tsx` `.js` `.jsx` | ✅ Stable |
| Go | `.go` | ✅ Stable |
| Rust | `.rs` | ✅ Stable |
| Java | `.java` | ✅ Stable |
| C# | `.cs` | ✅ Stable |
| Kotlin | `.kt` | ✅ Stable |
| Ruby | `.rb` | ✅ Stable |
| PHP | `.php` | ✅ Stable |
| Swift | `.swift` | ✅ Stable |
| C / C++ | `.c` `.cpp` `.h` `.hpp` | ✅ Stable |

---

## Comparison

| | XCE | Augment Code | Serena | Graphify |
|--|-----|-------------|--------|----------|
| Architecture awareness | ✅ Architecture→Component→Code | ❌ Flat embeddings | ❌ Symbol-level | ✅ Knowledge graph |
| Impact analysis | ✅ Blast radius + callers | ❌ | ❌ | ❌ |
| Call graph traversal | ✅ Multi-hop | ❌ | ✅ LSP-based | ❌ |
| Semantic search | ✅ Embeddings + graph | ✅ Embeddings | ❌ | ✅ |
| MCP native | ✅ | ✅ | ✅ | ✅ (`--mcp`) |
| Multi-language | ✅ 14 | ✅ | ✅ 40 via LSP | ✅ 19 |
| Self-hosted | ✅ | ❌ Cloud | ✅ | ✅ |
| SWE-bench | **78.2%** | Not published | Not published | Not published |
| Persistent memory | ✅ via XME | ❌ | ❌ | ❌ |

---

## Docker

Full stack with Docker Compose:

```bash
docker-compose up -d
```

Starts: Neo4j (graph store) + PostgreSQL (incremental hashing).

Then index and serve:
```bash
xce index /path/to/repo --repo-id my-project
xce serve --sse --port 8000   # remote agents connect via SSE
```

---

## CLI reference

```bash
xce index <path> --repo-id <id>    # index a repository
xce index <path> --full            # force full re-index
xce index <path> --smart-docs      # skip trivial nodes (~80% cost reduction)
xce serve                          # MCP stdio server (for local IDEs)
xce serve --sse --port 8000        # MCP SSE server (for remote agents)
xce status                         # list indexed repositories + stats
```

---

## Configuration

```bash
# Neo4j (required)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# LLM for doc generation (optional — layers 2-4)
# Get key at: https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-...
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSIONS=512

# PostgreSQL for incremental indexing (optional)
POSTGRES_URI=postgresql://xce:password@localhost:5432/xce_index
```

See [`.env.example`](.env.example) for full reference.

---

## Pre-indexed community repos

Already indexed and queryable via the hosted MCP server:
- Django, scikit-learn, sympy, matplotlib, pytest
- FastAPI, Flask, Express, React
- Coming soon: Gin (Go), Actix (Rust), Spring Boot (Java)

Try XCE on Django without indexing:
```json
{
  "mcpServers": {
    "xce-django": {
      "url": "https://mcp.xanther.ai/sse",
      "headers": { "Authorization": "Bearer xce_community_key" }
    }
  }
}
```

---

## With Xanther Memory Engine

XCE pairs with [XME](https://github.com/Xanther-Ai/xanther-memory-engine) to give agents both **structural code awareness** (XCE) and **persistent session memory** (XME):

```bash
pip install "xanther-context-engine[memory]"
```

XCE graph nodes link to XME decision facts via `REFERENCES_CODE` — so "why did we build auth this way?" surfaces both the architectural graph context and the original team decision.

---

## Package structure

```
xce/
├── __main__.py          # CLI entry point (xce index / xce serve / xce status)
├── models.py            # ASTNode, ASTEdge, NodeKind, SearchResult, etc.
├── config.py            # Environment-based configuration
├── parser.py            # Cross-file import resolution
├── parsers/             # 14 language parsers (tree-sitter based)
├── graph/
│   └── store.py         # Neo4j: upsert nodes/edges, semantic search, impact analysis
├── indexing/
│   ├── indexer.py       # Orchestrates 4-layer pipeline
│   ├── workflow.py      # LangGraph-enforced 4-layer workflow
│   ├── doc_generator.py # LLM doc generation (layers 2-4)
│   ├── embedding.py     # Vector embeddings via OpenRouter
│   └── hash_store.py    # PostgreSQL-backed incremental hash store
├── server/
│   └── mcp_server.py    # MCP server (stdio + SSE) — 5 XCE + 11 XME tools
├── query/
│   ├── agents.py        # LangGraph traversal agents
│   ├── decomposition.py # Problem decomposition
│   └── reasoning.py     # Multi-hop reasoning chains
└── utils/
    ├── circuit_breaker.py
    └── complexity_router.py
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Most useful contributions:
- New language parsers (`xce/parsers/`)
- Benchmark results on real codebases
- MCP client integration guides

Join [Discord](https://discord.com/invite/p27qtGkTYw) for discussion.

---

## Links

- [Website](https://xanther.ai)
- [Hosted dashboard](https://app.xanther.ai)
- [Discord](https://discord.com/invite/p27qtGkTYw)
- [Benchmarks](https://github.com/Xanther-Ai/xce-benchmarks)
- [Memory Engine (XME)](https://github.com/Xanther-Ai/xanther-memory-engine)
- [Blog](https://medium.com/@xanther.ai)

---

## License

Apache 2.0. See [LICENSE](LICENSE).
