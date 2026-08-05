# Xanther Context Engine — Getting Started

> **Architecture-aware code intelligence for coding agents.**  
> Index any repo once, query its structure forever.

---

## Prerequisites

- Docker Desktop running (Neo4j + PostgreSQL via `docker-compose up -d`)
- Python 3.9+ with the venv activated (`source .venv/bin/activate`)
- AWS credentials in `.env` (for Bedrock embeddings + doc generation)

Or start services manually:

```bash
# Neo4j
export JAVA_HOME="$(pwd)/jdk-21.0.11+10/Contents/Home"
neo4j-community-5.26.0/bin/neo4j start

# PostgreSQL (via Docker)
docker-compose up -d postgres
```

---

## Index a Repository

Single command — handles everything end-to-end:

```bash
# Index the XCE codebase itself
python -m xce index xce/ --repo-id xanther-context-engine

# Index any other repo
python -m xce index /path/to/repo --repo-id my-project

# Smart docs mode — 80% cheaper, skips trivial nodes
python -m xce index xce/ --repo-id xanther-context-engine --smart-docs

# Force full re-index (ignore incremental hashes)
python -m xce index xce/ --repo-id xanther-context-engine --full --smart-docs
```

**What happens in one run:**
1. Parse AST (tree-sitter — Python, Java, TS, Go, Rust, Kotlin, C#, Ruby, Swift...)
2. Store nodes + edges in Neo4j
3. Generate HLD/LDD docs via AWS Bedrock DeepSeek V3
4. Generate vector embeddings via AWS Bedrock Titan
5. Save file hashes to PostgreSQL (enables incremental re-indexing)

**Output:**
```
✓ Indexing complete (45.2s)
  Nodes:      2,603
  Edges:      3,841
  Docs:       984
  Embeddings: 2,603
```

---

## Check Status

```bash
python -m xce status
```

---

## Start the MCP Server

```bash
# stdio mode (for IDE integration)
python -m xce serve

# HTTP/SSE mode
python -m xce serve --sse --port 8000
```

---

## Query via MCP Tools

Once the MCP server is running, tools available to coding agents:

| Tool | What it does |
|---|---|
| `xce_search` | Semantic search across indexed code |
| `xce_architecture_context` | HLD/LDD docs + architecture role for a symbol |
| `xce_trace` | Traceability: test coverage, requirement links |
| `xce_impact_analysis` | Risk score + callers + affected files for a change |

---

## Query via REST (Dashboard API)

```bash
python -m xce.dashboard.server  # port 8080

# Find callers of a function (depth 1-5)
curl 'http://localhost:8080/api/symbol/xanther-context-engine:xce/graph/store.py:get_callers/callers?depth=2'

# Impact analysis
curl 'http://localhost:8080/api/symbol/xanther-context-engine:xce/graph/store.py:upsert_ast_nodes/impact'

# List all indexed repos
curl 'http://localhost:8080/api/repositories'
```

---

## Smart Docs Flag

By default, docs are generated for every node. Use `--smart-docs` to filter:

| Node type | Default | `--smart-docs` |
|---|---|---|
| Functions/methods ≥ 10 lines | ✅ doc | ✅ doc |
| Classes | ✅ doc | ✅ doc |
| Modules | ✅ doc | ✅ doc (arch only) |
| Functions < 10 lines | ✅ doc | ❌ skip |
| Variables | ✅ doc | ❌ skip |
| Imports | ✅ doc | ❌ skip |
| Decorators | ✅ doc | ❌ skip |

Result: **~62% fewer LLM calls**, ~80% lower cost, with negligible quality loss.

---

## Multi-Repo Support

Each repo gets its own `--repo-id` namespace. All live in the same Neo4j instance:

```bash
python -m xce index /path/to/backend   --repo-id my-backend
python -m xce index /path/to/frontend  --repo-id my-frontend
python -m xce index /path/to/infra     --repo-id my-infra
```

Queries always scope to a specific `repo_id`.

---

## Supported Languages

| Language | Status |
|---|---|
| Python | ✅ Full |
| TypeScript / JavaScript | ✅ Full |
| Java | ✅ Full |
| Kotlin | ✅ Full |
| Go | ✅ Full |
| Rust | ✅ Full |
| C# | ✅ Full |
| Ruby | ✅ Full |
| Swift | ✅ Full |
| C / C++ | ✅ Full |
| PHP | ⚠️ Partial (tree-sitter-php compat issue) |

---

## Incremental Re-indexing

After the first index, subsequent runs only process **changed files**:

```bash
# Make changes to your code, then:
python -m xce index xce/ --repo-id xanther-context-engine
# → Only re-parses files whose SHA-256 hash changed
# → Skips unchanged files entirely
```

File hashes are stored in PostgreSQL. Pass `--full` to force a complete re-index.

---

## Environment Variables (.env)

```bash
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xce_dev_password

# PostgreSQL (incremental hashing)
POSTGRES_URI=postgresql://xce:xce_dev_password@localhost:5432/xce_index

# AWS Bedrock (embeddings + doc generation)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
EMBEDDING_MODEL=amazon.titan-embed-text-v1
EMBEDDING_DIMENSIONS=1536

# Optional: OpenRouter fallback
OPENROUTER_API_KEY=...
```

---

## Troubleshooting

**"No module named 'boto3'"**
```bash
pip install boto3==1.34.162
```

**"PHP parser failed to load"**  
Harmless — tree-sitter-php has a minor API incompatibility. All other languages work fine.

**Indexing is slow**  
Doc generation calls AWS Bedrock per node (~1-3s each). Use `--smart-docs` to cut calls by 80%.

**Neo4j connection refused**
```bash
export JAVA_HOME="$(pwd)/jdk-21.0.11+10/Contents/Home"
neo4j-community-5.26.0/bin/neo4j start
```

---

## Further Reading

- `docs/architecture/COMPLETE_ARCHITECTURE.md` — Full system design
- `docs/architecture/MULTI_LAYER_INDEXING.md` — 4-layer indexing pipeline detail
- `docs/guides/MCP_SETUP.md` — IDE integration setup
