# End-to-End Multi-Layer RAG Setup - Complete Guide

## Overview

Xanther is now fully operational with complete **multi-layer graph RAG** architecture:

```
4-Layer Indexing Architecture
├── Layer 1: LSP (Code Level)
│   └── Tree-sitter AST parsing → ASTNode records
├── Layer 2: LLD Summary (Component Descriptions)
│   └── Component summaries → DESCRIBED_BY relationships
├── Layer 3: LLD Detailed (Component Documentation)
│   └── Full documentation → DETAILED_IN relationships
└── Layer 4: HLD (Architecture Level)
    └── Architecture docs → PART_OF_ARCHITECTURE relationships

All layers: 1536-dim embeddings in Neo4j, searchable via MCP tools
```

## Complete Setup Checklist

### ✓ Database & Indexing
- [x] Neo4j running (port 7687)
- [x] 4-layer indexing pipeline implemented
- [x] Embeddings stored in Neo4j
- [x] Knowledge graph constructed

### ✓ Query/Retrieval Layer
- [x] 4 LangGraph agents implemented
  - ArchitectureAgent (HLD queries)
  - TraceabilityAgent (relationship queries)
  - ImpactAnalysisAgent (blast radius)
  - SearchDiscoveryAgent (semantic search)
- [x] GraphStore wrapper for Neo4j
- [x] Multi-layer search implemented

### ✓ API Layer
- [x] Dashboard API (port 8080) - HTTP endpoints
- [x] HTTP MCP Server (port 8001) - Legacy transport
- [x] MCP Server (stdio) - Native MCP protocol

### ✓ CLI & Tools
- [x] xanther-cli with `--local` support
- [x] Multi-layer indexing command
- [x] xce-mcp-server console script

### ✓ IDE Integration
- [x] Kiro MCP configuration
- [x] 4 auto-approved tools
- [x] Command-based MCP server

## Architecture Diagram: Full Stack

```
┌─────────────────────────────────────────────────────────────┐
│                        KIRO IDE                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Editor + Command Palette                             │  │
│  │  (Cmd+K → xce_search, xce_architecture_context, etc) │  │
│  └───────────┬───────────────────────────────────────────┘  │
└──────────────┼──────────────────────────────────────────────┘
               │
               ↓ (MCP Protocol via stdio)
┌─────────────────────────────────────────────────────────────┐
│  ~/.kiro/settings/mcp.json                                  │
│  {                                                           │
│    "xanther": {                                              │
│      "command": "xce-mcp-server",                           │
│      "env": { NEO4J_* }                                     │
│    }                                                         │
│  }                                                           │
└──────────────┬──────────────────────────────────────────────┘
               │
               ↓ (Invoked by Kiro)
┌─────────────────────────────────────────────────────────────┐
│  xce/server/cli.py::run()                                   │
│  ├── Initialize GraphStore                                  │
│  ├── Initialize 4 Agents                                    │
│  └── Start MCP Server (stdio)                              │
└──────────────┬──────────────────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────────────────┐
│  xce/server/mcp_server.py::XCEMCPServer                      │
│  ├── /tools/list                                            │
│  ├── /tools/call (xce_search)                              │
│  ├── /tools/call (xce_architecture_context)                │
│  ├── /tools/call (xce_trace)                               │
│  └── /tools/call (xce_impact_analysis)                     │
└──────────────┬──────────────────────────────────────────────┘
               │
               ↓ (LangGraph)
┌─────────────────────────────────────────────────────────────┐
│  4 Agent Classes (xce/query/agents.py)                       │
│  ├── SearchDiscoveryAgent (semantic search)                 │
│  ├── ArchitectureAgent (HLD context)                        │
│  ├── TraceabilityAgent (code-to-arch tracing)              │
│  └── ImpactAnalysisAgent (blast radius)                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               ↓ (GraphStore)
┌─────────────────────────────────────────────────────────────┐
│  xce/graph/store.py::GraphStore                             │
│  ├── Neo4j Connection (bolt://localhost:7687)              │
│  ├── Query Methods                                          │
│  ├── Search Embeddings                                      │
│  └── Traverse Relationships                                 │
└──────────────┬──────────────────────────────────────────────┘
               │
               ↓ (Cypher Queries)
┌─────────────────────────────────────────────────────────────┐
│  NEO4J DATABASE (bolt://localhost:7687)                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Layer 1 & 2: LSP + Component Summaries (ASTNode)   │   │
│  │  ├── Nodes: Functions, Classes, Methods             │   │
│  │  ├── Properties: name, type, kind, signature       │   │
│  │  └── Edges: CALLS, INHERITS_FROM, USES             │   │
│  ├─ [DESCRIBED_BY] → Component Description (LLD-S)    │   │
│  │                                                      │   │
│  │ Layer 3: LLD Detailed Documentation                │   │
│  ├─ [DETAILED_IN] → Component Doc (LLD-D)             │   │
│  │                                                      │   │
│  │ Layer 4: HLD Architecture                          │   │
│  └─ [PART_OF_ARCHITECTURE] → Architecture Doc         │   │
│  │                                                      │   │
│  │ All Layers: HAS_EMBEDDING → 1536-dim Vectors      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Multi-Layer Indexing Data Flow

### Indexing Pipeline
```
1. PARSING (Layer 1: LSP)
   └── Input: Source code files
   └── Tool: tree-sitter
   └── Output: ASTNode records (functions, classes, methods)
   └── Storage: Neo4j nodes with full signature

2. COMPONENT SUMMARIZATION (Layer 2: LLD Summary)
   └── Input: ASTNode + source code
   └── Process: LLM-based summary generation
   └── Output: One-liner component descriptions
   └── Storage: Neo4j relationship DESCRIBED_BY

3. DOCUMENTATION GENERATION (Layer 3: LLD Detailed)
   └── Input: Component + full context
   └── Process: Detailed documentation generation
   └── Output: Full component documentation
   └── Storage: Neo4j relationship DETAILED_IN

4. ARCHITECTURE SYNTHESIS (Layer 4: HLD)
   └── Input: All components + relationships
   └── Process: System architecture generation
   └── Output: Architecture patterns, quality attributes
   └── Storage: Neo4j relationship PART_OF_ARCHITECTURE

5. EMBEDDING GENERATION (All Layers)
   └── Input: All text from layers 1-4
   └── Tool: OpenRouter (1536-dim embeddings)
   └── Storage: HAS_EMBEDDING relationships
   └── Purpose: Semantic search across all layers
```

### Querying Pipeline
```
User Query (from Kiro)
    │
    ↓
1. SEARCH DISCOVERY (xce_search)
   └── Semantic search via embeddings
   └── Symbol search via Neo4j indexes
   └── Tag search via Neo4j labels

2. ARCHITECTURE CONTEXT (xce_architecture_context)
   └── Query by symbol or file
   └── Traverse HLD relationships
   └── Return architecture docs + patterns

3. TRACEABILITY (xce_trace)
   └── Start from code symbol
   └── Traverse layers: LSP → LLD-S → LLD-D → HLD
   └── Return relationships and documentation

4. IMPACT ANALYSIS (xce_impact_analysis)
   └── Input: Changed files/symbols
   └── Query: Callers and callees
   └── Return: Blast radius + affected components

All queries powered by LangGraph agents and Neo4j.
```

## Running the Complete System

### 1. Start Neo4j
```bash
cd /Users/rajbhattacharya/Documents/Projects/xanther-context-engine
./neo4j-community-5.26.0/bin/neo4j console
# Verify: http://localhost:7474 (username: neo4j, password: xce_dev_password)
```

### 2. Index a Repository (Fill Neo4j)
```bash
cd /path/to/your/repo
xanther-cli sync --local
# Or with full re-index:
xanther-cli sync --local --full
# This runs the complete 4-layer pipeline
```

### 3. Verify Indexing
```bash
# Check Neo4j has data
curl -u neo4j:xce_dev_password http://localhost:7474/db/data/

# Or visit Neo4j Browser: http://localhost:7474
# Query: MATCH (n) RETURN n LIMIT 10
```

### 4. Restart Kiro
```bash
# Close and reopen Kiro
# MCP panel should show "xanther" with checkmark ✓
```

### 5. Use in Kiro
```
# Open any file and press Cmd+K
# Search: "xce_search neural networks" 
# Get context: "xce_architecture_context PaymentProcessor"
# Analyze impact: "xce_impact_analysis src/auth.py src/api.py"
```

## Architecture Quality Attributes

The 4-layer RAG provides:

### 1. Precision
- Layer 1 (LSP): Exact symbol locations and types
- Layer 2-3 (LLD): Detailed implementation context
- Layer 4 (HLD): Architectural constraints
- Result: Highly accurate context retrieval

### 2. Completeness
- All 4 abstraction levels indexed
- No information loss between layers
- Full code-to-architecture traceability
- Semantic search via embeddings

### 3. Navigability
- Multiple entry points (search, trace, architecture)
- Cross-layer relationships
- Impact propagation (LSP → HLD)
- Agent-guided traversal

### 4. Scalability
- Neo4j handles 1M+ nodes efficiently
- Batch indexing supported
- Incremental updates available
- Caching via embeddings

### 5. Extensibility
- Add new layers (Domain-specific?)
- Add new agents (custom analysis?)
- Add new tools (specific languages?)
- Modular LangGraph design

## Common Use Cases

### 1. Code Understanding
```
Query: xce_search "payment processing"
→ Find all payment-related code
→ Get LSP locations (Layer 1)
→ Get component descriptions (Layer 2)
→ Get full documentation (Layer 3)
→ See architecture patterns (Layer 4)
```

### 2. Impact Analysis
```
Query: xce_impact_analysis [changed_files]
→ Find all callers/callees
→ Traverse dependency graph
→ Identify affected components
→ Return architecture impact
```

### 3. Architecture Navigation
```
Query: xce_architecture_context "UserService"
→ Find symbol in Layer 1
→ Get component description (Layer 2)
→ Get full documentation (Layer 3)
→ Get architectural role (Layer 4)
→ See integrations and patterns
```

### 4. Traceability
```
Query: xce_trace "authenticateUser()" target_level="architecture"
→ Start at LSP (function definition)
→ Get component role (Layer 2)
→ Get design decisions (Layer 3)
→ Get architectural patterns (Layer 4)
→ Return complete trace
```

## Key Files

| Component | File | Purpose |
|-----------|------|---------|
| **CLI** | `xanther-cli/src/commands/sync.ts` | Local indexing support |
| **Indexing** | `xce/indexing/indexer.py` | 4-layer pipeline |
| **Doc Gen** | `xce/indexing/doc_generator.py` | Layer 2-4 generation |
| **Agents** | `xce/query/agents.py` | 4 LangGraph agents |
| **Storage** | `xce/graph/store.py` | Neo4j integration |
| **API** | `xce/dashboard/server.py` | HTTP endpoints |
| **MCP** | `xce/server/mcp_server.py` | MCP protocol |
| **CLI** | `xce/server/cli.py` | MCP entry point |

## Verification Commands

```bash
# 1. Check Neo4j running
curl -u neo4j:xce_dev_password http://localhost:7474/browser/ | head -1

# 2. Check MCP config
cat ~/.kiro/settings/mcp.json | grep -A 15 '"xanther"'

# 3. Check CLI works
xanther-cli init --local

# 4. Check indexing works
xanther-cli sync --local --help

# 5. Test MCP server
/Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server &
sleep 1
pkill -f xce-mcp-server
```

## Summary

**Multi-Layer Graph RAG is fully operational:**

✓ All 4 indexing layers implemented  
✓ Neo4j storing complete knowledge graph  
✓ All 4 agents functional  
✓ MCP tools available in Kiro  
✓ CLI supports local indexing  
✓ End-to-end traceability  

**Ready for production use in:**
- Code understanding
- Architecture analysis
- Impact assessment
- Traceability queries
- Design decisions
- Quality analysis

**Next Steps:**
1. Index your first repository
2. Explore with xce_search
3. Use in code analysis tasks
4. Build custom agents for specialized queries
