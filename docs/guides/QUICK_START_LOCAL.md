# Xanther Local - Quick Start Guide

Get your codebase indexed and queryable in 5 minutes.

---

## Prerequisites

- Node.js (for xanther-cli)
- Python 3.9+ (for xce)
- Docker or local Neo4j installation

## Installation

### 1. Ensure Services Are Running

```bash
# Terminal 1: Neo4j
cd neo4j-community-5.26.0
export JAVA_HOME=$(pwd)/jdk-21.0.11+10/Contents/Home
bin/neo4j console

# Terminal 2: HTTP MCP Server
cd /path/to/xanther-context-engine
python3 -m xce.server.http_mcp_server

# Terminal 3: Dashboard API
cd /path/to/xanther-context-engine
python3 -m xce.dashboard.server
```

**Verify services:**
```bash
curl http://localhost:8080/api/health    # Should return {"status":"healthy"}
curl http://localhost:8001/mcp/call      # Should be accessible
```

### 2. Configure xanther-cli for Local Mode

```bash
# Install or update xanther-cli
npm install -g xanther-cli

# OR use npx
npx xanther-cli --version
```

---

## Usage

### Index a Repository

```bash
cd /path/to/your/repository

# Initialize for local indexing
npx xanther-cli init --local

# Trigger indexing
npx xanther-cli sync --local
```

**What you'll see:**
```
  Xanther CLI — Sync

  Repository: https://github.com/user/repo
  Branch:     main
  Mode:       LOCAL

⠙ Starting local indexing...
✓ Indexing completed

  Results:
    Nodes:      1,234
    Edges:      5,678
    Docs:       1,234
    Embeddings: 1,234
```

### Query Your Code

#### Via REST API

```bash
# Find who calls a specific function
curl -X GET 'http://localhost:8080/api/symbol/user-repo:module.function/callers?depth=2'

# Analyze impact of changes
curl -X GET 'http://localhost:8080/api/symbol/user-repo:module.function/impact'

# Get traceability links
curl -X GET 'http://localhost:8080/api/symbol/user-repo:module.function/trace'
```

#### Via MCP Server (Kiro/Cursor)

The MCP server is pre-configured in `~/.kiro/settings/mcp.json`. Use in your IDE:

```
Available tools:
- xce_search: Search code semantically
- xce_architecture_context: Get module overview
- xce_trace: Build call chains
- xce_impact_analysis: Find affected code
```

---

## Configuration

### Local Mode Settings

The CLI saves configuration to `~/.xanther/config.json`:

```json
{
  "repo_url": "https://github.com/user/repo",
  "branch": "main",
  "repo_id": "user/repo",
  "use_local": true,
  "local_api_url": "http://localhost:8080"
}
```

### Environment Variables

```bash
# .env file in xanther-context-engine/
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xce_dev_password

# Optional: For better doc generation and embeddings
OPENROUTER_API_KEY=sk-or-v1-xxx
```

---

## Troubleshooting

### "Cannot connect to localhost:8080"

Dashboard API not running:
```bash
python3 -m xce.dashboard.server
```

### "Neo4j connection failed"

Neo4j not running:
```bash
cd neo4j-community-5.26.0
export JAVA_HOME=$(pwd)/jdk-21.0.11+10/Contents/Home
bin/neo4j console
```

### Indexing is slow

This is normal! Large repositories take time:
- Small repos (< 100 files): 30 seconds - 2 minutes
- Medium repos (100-1000 files): 5-15 minutes  
- Large repos (1000+ files): 30+ minutes

Incremental syncs are much faster (only changed files).

### "Indexing failed" error

Check logs in dashboard API terminal. Common issues:
- Missing API key for doc/embedding generation (optional - will skip these)
- Invalid repository path
- Neo4j authentication failure

---

## Features

### ✅ Code Search
Search across your entire codebase semantically or by symbol name.

### ✅ Call Chains
Trace function calls up (who calls me?) and down (who do I call?).

### ✅ Impact Analysis
When you change a function, see:
- What code depends on it
- Which tests exercise it
- Risk score based on fan-in

### ✅ Traceability
Link code to:
- Requirements and specifications
- Test files
- Architecture documentation

### ✅ IDE Integration
Use all features directly in Kiro, Cursor, or VS Code via MCP server.

---

## Performance Expectations

| Operation | Time |
|-----------|------|
| Index Django (~10k nodes) | 15-35 min |
| Index medium repo (1k nodes) | 2-5 min |
| Incremental sync | 30 sec - 2 min |
| Callers query | < 100ms |
| Impact analysis | < 500ms |
| Semantic search | < 200ms |

---

## What Gets Indexed

- **Functions/Methods**: Signatures, docstrings, implementations
- **Classes**: Hierarchy, interfaces, properties
- **Modules**: Imports, exports, dependencies
- **Variables**: Constants, configuration, types
- **Call Relationships**: Who calls whom
- **Containment**: Module structure
- **Inheritance**: Class hierarchies
- **Imports**: Module dependencies

Supported languages:
- ✅ Python
- ✅ TypeScript/JavaScript
- ✅ Java
- ⏳ More coming (extensible parser framework)

---

## API Reference

### POST /api/index

Trigger local indexing.

**Request:**
```json
{
  "repo_path": "/path/to/repo",
  "repo_id": "org/repo",
  "incremental": true
}
```

**Response:**
```json
{
  "status": "completed",
  "repo_id": "org/repo",
  "nodes_count": 1234,
  "edges_count": 5678,
  "docs_count": 1234,
  "embeddings_count": 1234
}
```

### GET /api/symbol/{symbol_id}/callers

Find who calls a symbol.

**Query params:**
- `depth` (1-5): How many levels deep to traverse. Default: 1

**Response:**
```json
{
  "symbol_id": "user/repo:module.function",
  "depth": 1,
  "callers": [
    {
      "node_id": "user/repo:other.caller",
      "name": "caller_function",
      "kind": "function",
      "filepath": "src/other.py",
      "start_line": 42,
      "call_depth": 1
    }
  ],
  "count": 1
}
```

### GET /api/symbol/{symbol_id}/callees

Find what a symbol calls (opposite of callers).

Same response format as `/callers`.

### GET /api/symbol/{symbol_id}/architecture

Get architecture context for a symbol.

**Response:**
```json
{
  "symbol_id": "user/repo:module.class",
  "architecture_context": [
    {
      "module_path": "src/core",
      "architectural_role": "Data processor",
      "design_patterns": ["Adapter", "Strategy"],
      "integration_points": ["src/io", "src/cache"],
      "quality_attributes": ["Scalability", "Reliability"]
    }
  ],
  "has_architecture_context": true
}
```

### GET /api/symbol/{symbol_id}/impact

Analyze change impact.

**Response:**
```json
{
  "symbol_id": "user/repo:module.function",
  "risk_score": 0.85,
  "direct_callers_count": 3,
  "direct_dependents": [...],
  "test_files": [...]
}
```

---

## Examples

### Example 1: Find all callers of a function

```bash
# Get immediate callers
curl 'http://localhost:8080/api/symbol/myapp-repo:auth.authenticate/callers?depth=1'

# Get callers up to 3 levels deep
curl 'http://localhost:8080/api/symbol/myapp-repo:auth.authenticate/callers?depth=3'
```

### Example 2: Understand function dependencies

```bash
# What does this function call?
curl 'http://localhost:8080/api/symbol/myapp-repo:core.process/callees'

# What calls it?
curl 'http://localhost:8080/api/symbol/myapp-repo:core.process/callers'
```

### Example 3: Understand architecture context

```bash
# Get architectural role and design patterns
curl 'http://localhost:8080/api/symbol/myapp-repo:core.processor/architecture'

# Response includes:
# - architectural_role: Role in the system
# - design_patterns: Patterns used (Adapter, Strategy, etc.)
# - integration_points: Other modules it connects to
# - quality_attributes: Non-functional properties
```

### Example 4: Assess refactoring risk

```bash
# How risky is changing this?
curl 'http://localhost:8080/api/symbol/myapp-repo:utils.format_data/impact'

# Response includes:
# - risk_score (0-1): How many things depend on it
# - direct_dependents: Files that directly use it
# - test_files: Tests that exercise it
```

---

## Support

For issues or questions:
1. Check `IMPLEMENTATION_STATUS.md` for detailed documentation
2. Review `LOCAL_INDEXING_FLOW.md` for architecture
3. Check logs in your terminal windows
4. Verify services are running with the checks above

---

## Advanced: Running Without API Keys

```bash
# You don't need API keys to index locally!
# The system will:
# ✓ Parse code and extract structure
# ✓ Store in Neo4j
# ✗ Skip doc generation (requires OpenRouter or AWS)
# ✗ Skip embeddings (requires OpenRouter or AWS)

# This is fine! You can still:
# - Search by symbol name
# - Trace calls and dependencies
# - Analyze impact
```

To enable docs and embeddings:

```bash
# Set either OpenRouter OR AWS credentials in .env
OPENROUTER_API_KEY=sk-or-v1-xxx

# OR
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1
```

---

**Ready to go!** Start with:
```bash
npx xanther-cli init --local
npx xanther-cli sync --local
```

Your code is now queryable from anywhere!
