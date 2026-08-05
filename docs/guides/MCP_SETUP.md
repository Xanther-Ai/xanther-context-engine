# Xanther MCP Setup - Command-Based Integration

## Overview
Xanther Context Engine is now available as a command-based MCP server in Kiro, integrated alongside Auggie and Serena.

## Configuration
The MCP configuration in `~/.kiro/settings/mcp.json` now includes:

```json
{
  "xanther": {
    "command": "/Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server",
    "args": [],
    "env": {
      "NEO4J_URI": "bolt://localhost:7687",
      "NEO4J_USER": "neo4j",
      "NEO4J_PASSWORD": "xce_dev_password"
    },
    "disabled": false,
    "autoApprove": [
      "xce_search",
      "xce_architecture_context",
      "xce_trace",
      "xce_impact_analysis"
    ]
  }
}
```

## What Was Done

### 1. Cleaned Up Old Xanther Configs
- ❌ Removed `xanther-local` (HTTP URL-based)
- ❌ Removed old `xanther` (remote https config)
- ✅ Replaced with single command-based `xanther` entry

### 2. Created Command-Based MCP Server
**File**: `xce/server/cli.py`
- Entry point for the MCP server
- Initializes all agents (Architecture, Traceability, Impact, Search)
- Connects to Neo4j with environment variables
- Runs MCP server over stdio transport
- Supports both stdio (default) and SSE modes

**Console Script**: Added to `pyproject.toml`
```toml
[project.scripts]
xce-mcp-server = "xce.server.cli:run"
```

### 3. Installation
```bash
cd /Users/rajbhattacharya/Documents/Projects/xanther-context-engine
pip install -e .
# Installs xce-mcp-server console script to venv
```

### 4. Available Tools
All 4 XCE tools are auto-approved and available in Kiro:

1. **xce_search** - Semantic/symbol/tag search in knowledge graph
2. **xce_architecture_context** - Architecture context for files/symbols
3. **xce_trace** - Trace relationships between code and design artifacts
4. **xce_impact_analysis** - Predict blast radius for code changes
5. **xce_index_repo** - Index or re-index repositories (optional 5th tool)

## How It Works

### Kiro Integration
When you use `xce_search` or other XCE tools in Kiro:
1. Kiro invokes: `/path/to/.venv/bin/xce-mcp-server`
2. The server initializes with environment variables from MCP config
3. Agents connect to Neo4j (localhost:7687)
4. Tool calls routed through MCP protocol over stdio
5. Results returned to Kiro

### Multi-Layer Architecture
The MCP server accesses the complete 4-layer indexing system:
- **Layer 1**: LSP AST Nodes (tree-sitter)
- **Layer 2**: LLD Summaries (component descriptions)
- **Layer 3**: LLD Detailed (component documentation)
- **Layer 4**: HLD (architecture documentation)

All accessed via agents and Neo4j knowledge graph.

## Requirements

### Running Services
The following services must be running for XCE to function:

1. **Neo4j** (Port 7687)
   - Database storing indexed code graph
   - Auth: neo4j / xce_dev_password
   - Start: `./neo4j-community-5.26.0/bin/neo4j start`

2. **Dashboard API** (Port 8080) - *Optional but recommended*
   - Provides HTTP endpoints for programmatic access
   - Start: `python3 -m xce.dashboard.server`

3. **HTTP MCP Server** (Port 8001) - *Optional if using command-based only*
   - Legacy HTTP transport for testing
   - Start: `python3 -m xce.server.http_mcp_server`

### Local Environment
The server uses environment variables from the MCP config:
- `NEO4J_URI`: Connection URL (default: bolt://localhost:7687)
- `NEO4J_USER`: Username (default: neo4j)
- `NEO4J_PASSWORD`: Password (from .env)

## Testing

### Quick Test
```bash
# Test MCP server responds to protocol
/Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server &
sleep 2
# Send MCP messages via stdin
pkill -f xce-mcp-server
```

### Use in Kiro
1. Open any file in Kiro
2. Press Cmd+K to open the command palette
3. Type: `mcp_xanther_xce_search`
4. Or use `mcp_xanther_xce_architecture_context` etc.

## Troubleshooting

### Server Won't Start
- Check Neo4j is running: `curl http://localhost:7687`
- Check environment variables are set: `echo $NEO4J_PASSWORD`
- Check Python path: `/Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/python3 -c "import xce; print(xce.__file__)"`

### Tool Returns Error
- Check Neo4j has indexed data: Visit http://localhost:7474 (Neo4j UI)
- Check MCP config has correct Neo4j credentials
- Check tool arguments match schema in `xce/server/mcp_server.py`

### Integration with Kiro
- MCP config should be in `~/.kiro/settings/mcp.json`
- Tool names must be in autoApprove list for auto-approval
- Can view/manage MCPs in Kiro: Command palette → "MCP"

## Files Modified/Created

### New Files
- `xce/server/cli.py` - MCP server entry point
- `MCP_SETUP.md` - This file

### Modified Files
- `pyproject.toml` - Added console script entry point
- `~/.kiro/settings/mcp.json` - Replaced xanther configs

### Unchanged But Important
- `xce/server/mcp_server.py` - Core MCP protocol implementation
- `xce/server/http_mcp_server.py` - Legacy HTTP transport (still available)
- `xce/query/agents.py` - All 4 agents used by MCP server

## Next Steps

1. **Verify Neo4j is Running**
   ```bash
   curl -u neo4j:xce_dev_password http://localhost:7687/db/data/
   ```

2. **Index a Repository** (if not already done)
   ```bash
   cd /path/to/repo
   xanther-cli sync --local
   ```

3. **Use in Kiro**
   - Type `#File` or `#Folder` to grab context
   - Use XCE tools to search and analyze code
   - Tools will automatically use the configured Neo4j database

## Architecture Diagram

```
Kiro IDE
   │
   └──→ MCP Config (mcp.json)
        │
        ├──→ command: xce-mcp-server
        ├──→ env: NEO4J_* credentials
        │
        └──→ /venv/bin/xce-mcp-server
             │
             ├──→ xce/server/cli.py (initialization)
             │
             ├──→ GraphStore (Neo4j connection)
             │   └──→ bolt://localhost:7687
             │
             ├──→ Agents (4 LangGraph agents)
             │   ├──→ ArchitectureAgent
             │   ├──→ TraceabilityAgent
             │   ├──→ ImpactAnalysisAgent
             │   └──→ SearchDiscoveryAgent
             │
             └──→ MCP Server (stdio transport)
                  │
                  ├──→ /tools/list
                  └──→ /tools/call (4 tools)
```

## Multi-Layer Indexing

The XCE MCP server provides access to all 4 layers of indexing:

### Layer 1: LSP (Language Server Protocol)
- Tree-sitter AST parsing
- Symbol location, type, kind
- Direct code references

### Layer 2: LLD Summary (Component Description)
- High-level component summaries
- Function/class descriptions
- Technical purpose and role

### Layer 3: LLD Detailed (Component Documentation)
- Full component documentation
- Implementation details
- Dependencies and patterns

### Layer 4: HLD (Architecture)
- System-wide architecture context
- Quality attributes
- Integration patterns
- Design decisions

All layers stored as embeddings in Neo4j and queried via agents.
