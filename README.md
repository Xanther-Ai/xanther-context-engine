<div align="center">

# Xanther Context Engine (XCE)

**Architecture-aware code intelligence for AI coding assistants.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Tests](https://github.com/Xanther-Ai/xanther-context-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Xanther-Ai/xanther-context-engine/actions)

</div>

---

> AI assistants read your entire codebase every question. They grep instead of navigate. They miss architectural context that only a graph can provide. XCE fixes this.

XCE turns any codebase into a **queryable knowledge graph** — functions, classes, imports, call edges, architecture layers — and serves it to AI agents via MCP. Works with Claude Code, Kiro, Cursor, Codex, and any MCP-compatible tool.

```bash
pip install xanther-context-engine
xce index .                 # build the graph once
xce serve                   # start MCP server
```

One command. Your agent now navigates by structure instead of grepping through files.

---

## Architecture

```mermaid
graph TB
    subgraph "Your Codebase"
        SRC[Source Files<br/>Python · TS · Go · Rust · Java · 10+ more]
        DOCS[Docs & Configs<br/>Markdown · OpenAPI · SQL]
    end

    subgraph "XCE Indexing Pipeline"
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

## Four indexing layers

XCE enriches your code graph in four sequential layers:

| Layer | What it produces | LLM? |
|-------|-----------------|------|
| 1 — AST Parsing | Functions, classes, imports, call edges | No |
| 2 — Component Descriptions | 1-2 sentence summary per symbol | Yes |
| 3 — Component Docs | Algorithm, data flow, error handling | Yes |
| 4 — Architecture Docs | Module roles, design patterns, integration points | Yes |

Layer 1 is always free — just tree-sitter. Layers 2-4 use your LLM API key (optional, enable with `--smart-docs` to reduce cost ~80%).

---

## Quickstart

```bash
pip install xanther-context-engine
cp .env.example .env        # add NEO4J_PASSWORD + OPENROUTER_API_KEY
docker-compose up -d        # start Neo4j + PostgreSQL

xce index . --repo-id my-project --smart-docs
xce serve                   # MCP server on stdio
```

Add to your MCP config (`~/.kiro/settings/mcp.json` or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "xce": {
      "command": "xce-mcp-server",
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_PASSWORD": "your-password"
      }
    }
  }
}
```

---

## MCP tools (5)

| Tool | Description |
|------|-------------|
| `xce_architecture_context` | Full architectural context for a file or symbol |
| `xce_search` | Semantic + symbol search across the graph |
| `xce_impact_analysis` | Blast radius — what breaks if you change this? |
| `xce_trace` | Trace from code to component to architecture |
| `xce_index_repo` | Trigger incremental re-index |

With [XME installed](https://github.com/Xanther-Ai/xanther-memory-engine), 11 additional memory tools are available automatically.

---

## Language support

14 languages via tree-sitter, with more on the way:

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| TypeScript / JavaScript | `.ts` `.tsx` `.js` `.jsx` |
| Go | `.go` |
| Rust | `.rs` |
| Java | `.java` |
| C# | `.cs` |
| Kotlin | `.kt` |
| Ruby | `.rb` |
| PHP | `.php` |
| Swift | `.swift` |
| C / C++ | `.c` `.cpp` `.h` `.hpp` |

---

## Incremental indexing

XCE uses SHA-256 content hashing (stored in PostgreSQL) to re-index only changed files:

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant XCE as xce index
    participant PG as PostgreSQL
    participant NEO4J as Neo4j

    Dev->>XCE: xce index . (second run)
    XCE->>PG: get stored hashes
    PG-->>XCE: {file: hash, ...}
    XCE->>XCE: SHA-256 all files
    XCE->>XCE: diff — find changed files only
    XCE->>NEO4J: upsert changed nodes/edges
    XCE->>PG: update hashes
    XCE-->>Dev: ✓ 3 files re-indexed (97 skipped)
```

---

## Comparison

| | Graphify | Serena | Sourcegraph | **XCE** |
|--|---------|--------|-------------|---------|
| Code graph (AST) | ✅ | ✅ (LSP) | ✅ | ✅ |
| Architecture docs | ❌ | ❌ | ❌ | ✅ |
| Component descriptions | ❌ | ❌ | ❌ | ✅ |
| Semantic search | ❌ | ❌ | ✅ | ✅ |
| Impact analysis | ❌ | partial | partial | ✅ |
| Multi-language | ✅ (19) | ✅ (40 via LSP) | ✅ | ✅ (14) |
| MCP tools | 1 | ✅ | ❌ | ✅ (5) |
| Local-first | ✅ | ✅ | ❌ | ✅ |
| Persistent memory | ❌ | ❌ | ❌ | ✅ via XME |

---

## CLI reference

```bash
xce index <path> --repo-id <id>   # index a repository
xce index <path> --full           # force full re-index
xce index <path> --smart-docs     # skip trivial nodes (80% cheaper)
xce serve                         # MCP stdio server
xce serve --sse --port 8000       # MCP SSE server
xce status                        # list indexed repos
```

---

## Configuration

```bash
# Neo4j (required)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# LLM for doc generation (optional — layers 2-4)
OPENROUTER_API_KEY=sk-or-...
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSIONS=512

# PostgreSQL for incremental indexing (optional)
POSTGRES_URI=postgresql://xce:password@localhost:5432/xce_index
```

See [`.env.example`](.env.example) for the complete reference.

---

## With Xanther Memory Engine

XCE pairs with [XME](https://github.com/Xanther-Ai/xanther-memory-engine) to give agents both structural awareness (XCE) and session memory (XME):

```bash
pip install "xanther-context-engine[memory]"  # installs xme automatically
```

XCE facts link to XME decisions via `REFERENCES_CODE` — so "why did we build auth this way?" surfaces both the architectural context and the original decision.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Most useful contributions:
- New language parsers (add to `xce/parsers/`)
- Benchmark results on real codebases
- MCP client integration guides

---

## License

Apache 2.0. See [LICENSE](LICENSE).
