# Xanther-CLI Local Indexing - End-to-End Flow

## Overview

When you run `xanther-cli sync --local`, it triggers a complete multi-layer indexing pipeline that builds a knowledge graph in your local Neo4j database. Here's the complete flow:

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                      XANTHER-CLI (User Entry)                   │
│                   npx xanther-cli sync --local                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 1: CLI ORCHESTRATION                    │
│  • Detect changed files (git diff)                              │
│  • Call local indexing API on localhost:8080                    │
│  • POST /api/index with repo_path, repo_id, incremental flag    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           LAYER 2: DASHBOARD SERVER (Port 8080)                 │
│  • Receives index request via REST API                          │
│  • Manages progress tracking                                    │
│  • Coordinates all downstream services                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │  Parser │      │   Doc   │      │Embeddings│
    │ Registry│      │Generator│      │ Service │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                │                │
         └────────────────┼────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│     LAYER 3: INDEXING PIPELINE (Multi-Stage Processing)         │
│                                                                 │
│  Stage 1: AST Parsing                                           │
│  • tree-sitter parses source files                              │
│  • Extracts symbols: functions, classes, imports, etc.          │
│  • Builds call graphs                                           │
│  Output: ASTNode objects                                        │
│                                                                 │
│  Stage 2: Documentation Generation                              │
│  • AWS Bedrock (or OpenRouter) generates summaries              │
│  • Creates ComponentDescription docs                            │
│  • Extracts architectural roles                                 │
│  Output: Doc objects with context                               │
│                                                                 │
│  Stage 3: Embedding Generation                                  │
│  • AWS Bedrock embeddings for semantic search                   │
│  • Vectorizes symbol text, docs, context                        │
│  • 1536-dim embeddings for similarity matching                  │
│  Output: Vector embeddings                                      │
│                                                                 │
│  Stage 4: Graph Construction                                    │
│  • Creates Neo4j nodes: ASTNode, Doc, Architecture              │
│  • Creates edges: CALLS, IMPORTS, CONTAINS, PART_OF, etc.      │
│  • Establishes relationships between layers                     │
│  Output: Populated Neo4j graph                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│         LAYER 4: LOCAL NEO4J DATABASE (Port 7687)               │
│                                                                 │
│  Stores:                                                        │
│  ├─ ASTNode labels                                              │
│  │  ├─ Properties: name, kind, filepath, docstring, etc.        │
│  │  └─ Relationships: CALLS, IMPORTS, CONTAINS                 │
│  │                                                               │
│  ├─ ComponentDescription (optional)                             │
│  │  └─ Holds AI-generated documentation                         │
│  │                                                               │
│  └─ Embeddings (property on ASTNode)                            │
│     └─ For similarity-based semantic search                     │
│                                                                 │
│  Indexes created for query performance                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│       LAYER 5: MCP SERVER (Port 8001) - Query Interface         │
│                                                                 │
│  Tools available:                                               │
│  • xce_search - Find symbols by name/semantic similarity         │
│  • xce_architecture_context - Get architectural role             │
│  • xce_trace - Link code to requirements/tests                   │
│  • xce_impact_analysis - Calculate change blast radius           │
│                                                                 │
│  Powered by: LangGraph agents + GraphStore queries              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│      LAYER 6: IDE INTEGRATION (Kiro, Cursor, Claude Code)       │
│                                                                 │
│  MCP Config:                                                    │
│  {                                                              │
│    "xanther-local": {                                           │
│      "url": "http://localhost:8001/mcp/call",                   │
│      "autoApprove": ["xce_search", "xce_impact_analysis", ...]  │
│    }                                                            │
│  }                                                              │
│                                                                 │
│  Agent can now call xce_* tools for codebase understanding     │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Step-by-Step Flow

### Step 1: User Runs CLI Command
```bash
npx xanther-cli sync --local
```

**What happens:**
- Detects `.xanther/config.json`
- Gets `repo_id` and `repo_path`
- Runs `git diff --name-only HEAD~1` to find changed files
- Calls dashboard server API

### Step 2: CLI Sends HTTP Request to Dashboard
```
POST http://localhost:8080/api/index
{
  "repo_path": "/path/to/repo",
  "repo_id": "django-django",
  "incremental": true
}
```

### Step 3: Dashboard Server Receives Request
- Validates Neo4j connection
- Initializes progress tracker
- Creates GraphStore instance
- Calls `index_repository()` from xce.indexing.indexer

### Step 4: AST Parsing (Stage 1)
```python
# xce/indexing/indexer.py::index_repository()

1. Discover source files matching registered extensions
   - .py files (Python)
   - .ts/.tsx files (TypeScript)
   - .js files (JavaScript)
   - etc.

2. For each changed file:
   parser = registry.get_parser(filepath)  # Get tree-sitter parser
   nodes, edges = parser.parse_file(filepath, source, repo_id)
   
3. Extract:
   - Functions/methods
   - Classes
   - Import statements
   - Assignments
   - Call relationships (A calls B)
```

**Output:** `List[ASTNode]` with properties:
```python
{
  "id": "django-django:django/contrib/auth/models.py:class:User",
  "name": "User",
  "kind": "class",
  "filepath": "django/contrib/auth/models.py",
  "start_line": 42,
  "end_line": 156,
  "source_text": "class User(AbstractBaseUser):\n  ...",
  "docstring": "Django user model...",
  "repo_id": "django-django"
}
```

### Step 5: Documentation Generation (Stage 2)
```python
# xce/indexing/doc_generator.py

For each node with docstring:
  1. Send to AWS Bedrock (model: deepseek.v3.2)
  2. Prompt: "Summarize this code: {docstring + source}"
  3. Receive AI-generated description
  4. Create ComponentDescription doc node
  
Example prompt → response:
  Input: "def authenticate(self, username, password): ..."
  Output: "Authenticates users by validating credentials against database"
```

**Output:** ComponentDescription documents linked to nodes

### Step 6: Embedding Generation (Stage 3)
```python
# xce/indexing/embedding.py

For each ASTNode:
  1. Build text: name + docstring + source snippet
  2. Send to AWS Bedrock (model: amazon.titan-embed-text-v1)
  3. Get 1536-dimensional embedding vector
  4. Store embedding on node in Neo4j
  
result = await embedding_service.encode_batch(texts)
# Returns: List[List[float]] - shape (num_nodes, 1536)
```

**Output:** Embedding vectors for semantic similarity

### Step 7: Graph Construction (Stage 4)
```python
# xce/graph/store.py::upsert_nodes()

1. Create ASTNode nodes in Neo4j:
   CREATE (n:ASTNode {
     id: "...",
     name: "User",
     kind: "class",
     repo_id: "django-django",
     ...properties
   })

2. Create CONTAINS relationships (parent-child):
   CREATE (parent)-[:CONTAINS]->(child)
   
3. Create CALLS relationships (function calls):
   CREATE (caller)-[:CALLS]->(callee)
   
4. Create IMPORTS relationships:
   CREATE (file)-[:IMPORTS]->(module)
```

**Output:** Populated Neo4j graph with ~10,000+ nodes for large repos

### Step 8: Query Layer Available (Layer 5)
Once indexing complete, HTTP MCP server can query:

```python
# xce/server/http_mcp_server.py

@app.post("/mcp/call")
async def call_tool(request):
    tool_name = request.json()["name"]
    args = request.json()["arguments"]
    
    # Dispatch to agent
    if tool_name == "xce_search":
        agent = SearchDiscoveryAgent(graph_store)
        result = await agent.search(args["query"], args["repo_id"])
        return result.to_dict()
```

### Step 9: IDE Uses Local MCP
```json
// ~/.kiro/settings/mcp.json or ~/.cursor/mcp.json
{
  "xanther-local": {
    "url": "http://localhost:8001/mcp/call",
    "autoApprove": ["xce_search", "xce_impact_analysis", ...]
  }
}
```

Agent in IDE can now call:
```
User: "Find authentication methods and their callers"
↓
Agent: [calls xce_search("authenticate")]
↓
MCP Server: Searches local Neo4j
↓
Agent: Gets results with full context, docs, call chains
```

## Data Flow Example

### Input: Small Python file
```python
# test_module.py
class UserAuthenticator:
    def authenticate(self, username, password):
        return self._validate(username, password)
    
    def _validate(self, u, p):
        return len(u) > 0 and len(p) > 0
```

### Output After Indexing

**Neo4j Nodes Created:**
```
ASTNode:test_module(module)
├── ASTNode:UserAuthenticator(class)
│   ├── ASTNode:authenticate(method)
│   └── ASTNode:_validate(method)
└── Embeddings: [0.12, -0.45, 0.89, ...] (1536 dims)

Edges:
- (test_module)-[:CONTAINS]->(UserAuthenticator)
- (UserAuthenticator)-[:CONTAINS]->(authenticate)
- (authenticate)-[:CALLS]->(_validate)
```

**Queries Enabled:**
```
xce_search("authenticate")
→ Returns method with docs, signature, parent class

xce_impact_analysis(["test_module.py"])
→ Returns all 3 symbols as impacted

xce_architecture_context("UserAuthenticator")
→ Returns class role, parent relationships
```

## Time & Performance

- **Parsing:** ~100-500 files/sec (depends on file size)
- **Doc generation:** ~2-10 secs/method (API calls, batched)
- **Embeddings:** ~50-200 embeddings/sec (API calls, batched)
- **Graph storage:** ~100-1000 nodes/sec (batched Neo4j writes)

**Total for Django repo:**
- ~10,000 nodes
- ~15,000 edges
- ~30 mins for full indexing (includes doc gen + embeddings)
- ~5 mins for incremental (changed files only)

## Configuration Files

### `.xanther/config.json` (CLI Config)
```json
{
  "api_key": "xce_...",
  "repo_id": "django-django",
  "repo_url": "https://github.com/django/django",
  "branch": "main",
  "api_url": "http://localhost:8080",
  "mcp_url": "http://localhost:8001/mcp/call",
  "last_sync": "2026-06-05T02:00:00Z",
  "local_mode": true
}
```

### `.env` (XCE Config)
```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xce_dev_password
EMBEDDING_MODEL=amazon.titan-embed-text-v1
EMBEDDING_DIMENSIONS=1536
OPENROUTER_API_KEY=sk-or-v1-...  # For doc generation fallback
AWS_ACCESS_KEY_ID=...             # For Bedrock
AWS_SECRET_ACCESS_KEY=...
```

## Summary

**Full chain:**
```
CLI → Dashboard API → Indexer → 
  Parser → Docs → Embeddings → 
Neo4j → GraphStore → MCP Server → 
IDE Agent
```

**Each layer:**
1. **CLI**: Entry point, detects changes
2. **Dashboard**: REST API, progress tracking
3. **Indexer**: Orchestrates all stages
4. **Parser**: Extracts code structure (AST)
5. **Doc Gen**: Creates documentation
6. **Embeddings**: Vectorizes for search
7. **Neo4j**: Stores graph with indexes
8. **GraphStore**: Query abstraction
9. **MCP Server**: Agent tools interface
10. **IDE**: Uses tools for context

All layers working together create a complete local knowledge graph accessible to your coding agent!
