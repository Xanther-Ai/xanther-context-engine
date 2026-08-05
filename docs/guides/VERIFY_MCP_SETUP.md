# Verify Xanther MCP Setup

This guide helps you verify that Xanther is properly configured as an MCP in Kiro.

## Quick Checks

### 1. MCP Config Updated ✓
```bash
cat ~/.kiro/settings/mcp.json | grep -A 15 '"xanther"'
```

**Expected output**:
- Single `xanther` entry (not `xanther-local` or old remote)
- `command`: Points to `/venv/bin/xce-mcp-server`
- `env`: Contains `NEO4J_*` variables
- `autoApprove`: Lists all 4 tools

### 2. Console Script Installed ✓
```bash
ls -la /Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server
```

**Expected**: File exists and is executable

### 3. Neo4j Running ✓
```bash
curl -s -u neo4j:xce_dev_password http://localhost:7474/browser/ | head -1
```

**Expected**: Returns HTML with `<!doctype html>`

### 4. Dashboard API Running ✓ (Optional)
```bash
curl -s http://localhost:8080/health
```

**Expected**: Returns `{"status":"ok"}`

## Full Verification Flow

### Step 1: Kill Old Processes
If any old xanther MCPs are running, kill them:
```bash
pkill -f "xce.mcp_server --sse" || true
pkill -f "xce.server.http_mcp_server" || true
```

### Step 2: Verify Config
```bash
# View current MCP config
python3 -c "import json; c=json.load(open(open(open('/Users/rajbhattacharya/.kiro/settings/mcp.json').read().split('\"')[1])); print('OLD CONFIG')" 2>/dev/null || \
python3 -c "
import json
with open('/Users/rajbhattacharya/.kiro/settings/mcp.json') as f:
    config = json.load(f)
    xanther = config['mcpServers'].get('xanther', {})
    print(f'✓ Command: {xanther.get(\"command\", \"NOT SET\")}')
    print(f'✓ NEO4J_URI: {xanther.get(\"env\", {}).get(\"NEO4J_URI\", \"NOT SET\")}')
    print(f'✓ Auto-approved: {len(xanther.get(\"autoApprove\", []))} tools')
    
    # Check old configs removed
    if 'xanther-local' in config['mcpServers']:
        print('✗ ERROR: xanther-local still exists - should be removed')
    else:
        print('✓ xanther-local removed')
    
    # Count xanther entries
    xanther_count = len([k for k in config['mcpServers'] if 'xanther' in k.lower()])
    if xanther_count == 1:
        print(f'✓ Single xanther entry found')
    else:
        print(f'✗ ERROR: Found {xanther_count} xanther-related entries (should be 1)')
"
```

### Step 3: Test MCP Server
```bash
# Quick test: Does the server start and respond to MCP protocol?
python3 << 'EOF'
import json
import subprocess
import sys

proc = subprocess.Popen(
    ["/Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

# Send initialize
init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", 
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, 
                   "clientInfo": {"name": "test", "version": "1.0"}}}
proc.stdin.write(json.dumps(init) + "\n")
proc.stdin.flush()

response = proc.stdout.readline()
if "result" in response:
    print("✓ MCP server initialization successful")
else:
    print("✗ MCP server initialization failed")
    print(f"  Response: {response[:100]}")

proc.terminate()
proc.wait(timeout=2)
EOF
```

### Step 4: Restart Kiro
Kiro may need to reload the MCP config:
1. Command Palette → "Reload Window" (or restart Kiro)
2. Check MCP panel for "xanther" with ✓ status

### Step 5: Use in Code
In Kiro editor:
```python
# Option 1: Use MCP tool directly
# In a code comment or chat:
# "Search for user authentication patterns using xce_search"

# Option 2: Open assistant and use tool
# Cmd+K → "Use xce_search to find payment processing"
```

## Troubleshooting

### Issue: "xanther MCP not found"
**Solution**:
1. Check MCP config: `cat ~/.kiro/settings/mcp.json`
2. Verify command path exists: `ls /Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server`
3. Check it's executable: `file /Users/rajbhattacharya/Documents/Projects/xanther-context-engine/.venv/bin/xce-mcp-server`
4. Restart Kiro: Close and reopen

### Issue: "Connection refused" when using tool
**Solution**:
1. Check Neo4j running: `curl -u neo4j:xce_dev_password http://localhost:7474`
2. Check credentials in MCP config match `.env`
3. Check Neo4j has indexed data: http://localhost:7474 → Browser → Query
4. Start Neo4j if stopped: `./neo4j-community-5.26.0/bin/neo4j console`

### Issue: "Neo4j connection timeout"
**Solution**:
1. Make sure Neo4j is running
2. Check Neo4j auth is correct in MCP config
3. Verify Neo4j port (7687) is not blocked
4. Check `.env` file for correct credentials

### Issue: "Tool returns empty results"
**Solution**:
1. Index a repository first: `xanther-cli sync --local`
2. Check indexed data in Neo4j: http://localhost:7474 → MATCH (n) RETURN n LIMIT 10
3. Verify repository exists in Neo4j

## Files to Check

| File | Purpose | Status |
|------|---------|--------|
| `~/.kiro/settings/mcp.json` | MCP configuration | ✓ Updated |
| `xce/server/cli.py` | Entry point | ✓ Created |
| `xce/server/mcp_server.py` | MCP protocol | ✓ Existing |
| `pyproject.toml` | Console script | ✓ Updated |
| `.venv/bin/xce-mcp-server` | Executable | ✓ Installed |

## Performance Notes

- **First startup**: ~2-3 seconds to initialize agents and connect to Neo4j
- **Tool calls**: 1-3 seconds depending on query complexity
- **Concurrent calls**: MCP server handles one at a time (async queue)

## Security

The MCP config includes Neo4j credentials. This is safe for local development but:
- Do not commit credentials to version control
- Use environment variables for remote deployments
- Keep Neo4j access restricted to localhost

## Next Steps

1. ✓ Verify all checks above pass
2. ✓ Restart Kiro if any issues
3. ✓ Index your first repository: `xanther-cli sync --local`
4. ✓ Use XCE tools in code analysis tasks

## Support

For issues:
1. Check MCP_SETUP.md for architecture details
2. Review Neo4j logs: `./neo4j-community-5.26.0/logs/`
3. Check CLI output: `xce-mcp-server` runs in foreground
4. Inspect MCP protocol: Add debug logging in xce/server/cli.py
