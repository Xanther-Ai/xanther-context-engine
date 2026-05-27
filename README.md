# Xanther Context Engine (XCE)

[![CI](https://github.com/Xanther-Ai/xanther-context-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Xanther-Ai/xanther-context-engine/actions/workflows/ci.yml)

**Deep codebase understanding for coding agents.** XCE indexes your repository into a structured knowledge graph and serves precise architectural context via MCP — so your agent always knows where it is and what matters.

> On SWE-bench Verified: MiniMax M2.5 + XCE scored **78.2%**, beating Claude Opus 4.5 (76.8%) at **16x lower cost**. Sonnet 4.0 + XCE went from 66% → 73.4%. The improvement comes entirely from better context, not a better model.

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Start Neo4j
docker compose up neo4j -d

# 3. Index a repository
python -m xce.indexer /path/to/your/repo

# 4. Start MCP server
python -m xce.mcp_server
```

Your agent now has access to 5 tools: `xce_get_context`, `xce_search`, `xce_architecture_context`, `xce_trace`, `xce_impact_analysis`.

## How It Works — The PRAT Algorithm

PRAT (Persistent Recursive Abstract Tree) builds a multi-level structured index:

1. **AST Parsing** — Every function, class, and import extracted via tree-sitter (13 languages)
2. **Structural Analysis** — Call graphs, inheritance chains, module dependencies mapped
3. **Semantic Enrichment** — Each component gets a description of its role and architectural context via LLM
4. **Embedding** — Semantic vectors enable similarity search across the entire codebase
5. **Graph Storage** — Everything stored in Neo4j with relationships: CALLS, IMPORTS, CONTAINS, DEPENDS_ON

The key difference from embedding-only search (like Augment Code): PRAT captures **structural relationships** between components. Your agent can ask "what depends on this function?" and get a real answer — something embeddings alone cannot provide.

```
┌─────────────────────────────────────────────────────────┐
│                    HLD (High-Level Design)                │
│  Modules, architectural patterns, system boundaries      │
├─────────────────────────────────────────────────────────┤
│                    LLD (Low-Level Design)                 │
│  Components, classes, interfaces, data flow              │
├─────────────────────────────────────────────────────────┤
│                    Code Level                             │
│  Functions, methods, call graphs, dependencies           │
└─────────────────────────────────────────────────────────┘
```

## vs Other Tools

| Feature | XCE | Augment Code | Serena | Graphify |
|---------|-----|-------------|--------|----------|
| Architecture awareness | ✅ HLD→LLD→Code | ❌ Flat embeddings | ❌ Symbol-level only | ✅ Knowledge graph |
| Impact analysis | ✅ Predicts blast radius | ❌ | ❌ | ❌ |
| Call graph traversal | ✅ Full chain | ❌ | ✅ LSP-based | ❌ |
| Semantic search | ✅ Embeddings + graph | ✅ Embeddings | ❌ | ✅ |
| MCP native | ✅ | ✅ | ✅ | ✅ (--mcp) |
| Multi-language | ✅ 13 languages | ✅ | ✅ | ✅ |
| Self-hosted | ✅ | ❌ Cloud only | ✅ | ✅ |
| SWE-bench verified | 78.2% | Not published | Not published | Not published |

## MCP Tools

| Tool | Description |
|------|-------------|
| `xce_get_context` | Full architectural context for a problem. **Use first on any task.** |
| `xce_search` | Semantic search — find code by meaning, not just text |
| `xce_architecture_context` | Deep dive on a file/symbol — role, dependencies, callers |
| `xce_impact_analysis` | Predict what breaks before you change files |
| `xce_trace` | Trace from code up to high-level architecture |

## Supported Languages

| Language | Parser | Status |
|----------|--------|--------|
| Python | tree-sitter | ✅ Stable |
| TypeScript | tree-sitter | ✅ Stable |
| JavaScript | tree-sitter | ✅ Stable |
| Java | tree-sitter | ✅ Stable |
| Go | tree-sitter | ✅ Stable |
| Rust | tree-sitter | ✅ Stable |
| C# | tree-sitter | ✅ Stable |
| C/C++ | tree-sitter | ✅ Stable |
| Ruby | tree-sitter | ✅ Stable |
| PHP | tree-sitter | ✅ Stable |
| Kotlin | tree-sitter | ✅ Stable |
| Swift | tree-sitter | ✅ Stable |
| TSX/JSX | tree-sitter | ✅ Stable |

## Setup

### Prerequisites

- Python 3.12+
- Docker (for Neo4j)
- An LLM API key (OpenRouter, OpenAI, or Anthropic) for documentation generation

### Install

```bash
git clone https://github.com/Xanther-Ai/xanther-context-engine.git
cd xanther-context-engine
pip install -e .
```

### Start Neo4j

```bash
docker compose up neo4j -d
```

### Configure

```bash
cp .env.example .env
# Edit .env — add your LLM API key (OpenRouter recommended)
```

### Index a Repository

```bash
python -m xce.indexer /path/to/your/repo
```

This takes 2-10 minutes depending on repo size. Progress is logged.

### Start MCP Server (Local — stdio)

```bash
python -m xce.mcp_server
```

### Start MCP Server (Remote — SSE)

```bash
python -m xce.mcp_server --sse --port 8000
```

### Connect Your IDE

Add to your IDE's MCP config:

```json
{
  "mcpServers": {
    "xanther-xce": {
      "command": "python",
      "args": ["-m", "xce.mcp_server"],
      "cwd": "/path/to/xanther-context-engine"
    }
  }
}
```

Or for remote SSE:

```json
{
  "mcpServers": {
    "xanther-xce": {
      "url": "http://localhost:8000/sse?repo_id=YOUR_REPO_ID"
    }
  }
}
```

Works with: Claude Code, Kiro, Cursor, Windsurf, OpenCode, Cline.

## Docker (Full Stack)

```bash
docker compose up
```

This starts Neo4j + XCE MCP server. Index a repo, then connect your agent.

## Benchmark Results

All on [SWE-bench Verified](https://www.swebench.com/) (500 instances) using mini-swe-agent:

| Setup | Resolve Rate | Cost/Instance |
|-------|-------------|---------------|
| **MiniMax M2.5 + XCE** | **78.2%** | $0.22 |
| Claude 4.5 Opus (baseline) | 76.8% | $0.75 |
| MiniMax M2.5 (baseline) | 75.8% | $0.07 |
| **Sonnet 4.0 + XCE** | **73.4%** | $0.22 |
| Sonnet 4.0 (baseline) | 66.0% | $0.22 |

Full data: [github.com/Xanther-Ai/xce-benchmarks](https://github.com/Xanther-Ai/xce-benchmarks)

## Architecture

```
xce/
├── indexer.py          # Orchestrates the full indexing pipeline
├── parser.py           # Multi-language AST parsing (tree-sitter)
├── parsers/            # Language-specific parsers (13 languages)
├── graph_store.py      # Neo4j graph operations
├── embedding_service.py # Vector embeddings via OpenRouter/OpenAI
├── doc_generator.py    # LLM-powered documentation generation
├── mcp_server.py       # MCP server (stdio + SSE)
├── models.py           # Data models (ASTNode, NodeKind, etc.)
├── summarizer.py       # Code summarization
├── config.py           # Configuration management
└── agents.py           # LangGraph agents for complex queries
```

## Hosted Version

Don't want to self-host? Use the hosted version at [app.xanther.ai](https://app.xanther.ai):
- Free tier: 100 queries/month, 3 repos
- No infrastructure to manage
- Same engine, cloud-hosted

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repo
2. Create a feature branch
3. Submit a PR

Join [Discord](https://discord.com/invite/p27qtGkTYw) for discussion.

## Links

- [Website](https://xanther.ai)
- [Dashboard](https://app.xanther.ai)
- [Discord](https://discord.com/invite/p27qtGkTYw)
- [npm: xanther-cli](https://www.npmjs.com/package/xanther-cli)
- [Blog](https://medium.com/@xanther.ai)
- [Benchmarks](https://github.com/Xanther-Ai/xce-benchmarks)
- [Memory Engine](https://github.com/Xanther-Ai/xanther-memory-engine)

## License

MIT — see [LICENSE](LICENSE) for details.
