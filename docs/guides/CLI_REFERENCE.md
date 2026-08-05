# XCE CLI Reference

```
python -m xce <command> [options]
```

---

## Commands

### `index` — Index a repository

```
python -m xce index <repo_path> [--repo-id ID] [--full] [--smart-docs]
```

| Argument | Default | Description |
|---|---|---|
| `repo_path` | required | Path to the repo directory to index |
| `--repo-id` | directory name | Unique identifier for this repo in the graph |
| `--full` | off | Force full re-index (ignore incremental hashes) |
| `--smart-docs` | off | Only generate docs for classes and functions ≥10 lines |
| `--log-level` | INFO | DEBUG / INFO / WARNING / ERROR |

**Examples:**

```bash
# Index XCE itself
python -m xce index xce/ --repo-id xanther-context-engine

# Index with smart docs (recommended — 80% cheaper)
python -m xce index xce/ --repo-id xanther-context-engine --smart-docs

# Full re-index, smart docs
python -m xce index /path/to/repo --repo-id my-project --full --smart-docs

# Debug logging
python -m xce index xce/ --repo-id xanther-context-engine --log-level DEBUG
```

**What `--smart-docs` skips:**
- Variables, imports, decorators (always skipped)
- Functions/methods with fewer than 10 lines of source
- Saves ~62% of LLM calls with negligible quality loss

---

### `status` — Show indexed repositories

```
python -m xce status
```

Lists all repos in the graph with node count and last indexed timestamp.

---

### `serve` — Start the MCP server

```
python -m xce serve [--sse] [--port PORT]
```

| Argument | Default | Description |
|---|---|---|
| `--sse` | off | Use HTTP/SSE transport instead of stdio |
| `--port` | 8000 | Port for SSE mode |

**Examples:**

```bash
# stdio (for IDE integration via mcp.json)
python -m xce serve

# HTTP mode
python -m xce serve --sse --port 8000
```

---

## Indexing Pipeline

Each `index` run executes these steps in order:

```
1. Discover source files (all registered extensions)
2. Filter unchanged files (incremental via PostgreSQL hashes)
3. Parse AST with tree-sitter (per-language parsers)
4. Resolve cross-file imports → edges
5. Store AST nodes + edges in Neo4j (MERGE/upsert)
6. Generate HLD ComponentDescription per node (LLM)  ← filtered by --smart-docs
7. Generate LDD ComponentDoc per function/method (LLM)
8. Generate ArchitectureDoc per module (LLM)
9. Generate vector embeddings (AWS Bedrock Titan / OpenRouter)
10. Store embeddings in Neo4j
11. Save file hashes to PostgreSQL
12. Update repository metadata in PostgreSQL
```

Steps 6-8 are LLM calls (the expensive/slow part). `--smart-docs` reduces step 6 by ~62%.

---

## Supported Languages

Python, TypeScript, JavaScript, Java, Kotlin, Go, Rust, C#, Ruby, Swift, C, C++

---

## Environment Variables

```bash
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xce_dev_password

# PostgreSQL (incremental hashing)
POSTGRES_URI=postgresql://xce:xce_dev_password@localhost:5432/xce_index

# AWS Bedrock (primary — auto-detected from credentials)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
EMBEDDING_MODEL=amazon.titan-embed-text-v1
EMBEDDING_DIMENSIONS=1536

# OpenRouter (fallback if no AWS credentials)
OPENROUTER_API_KEY=...
EMBEDDING_MODEL=openai/text-embedding-3-small

# Tuning
DOC_GEN_BATCH_SIZE=10
EMBEDDING_BATCH_SIZE=100
LOG_LEVEL=INFO
```
