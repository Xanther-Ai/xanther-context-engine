---
name: xce
description: Set up Xanther Context Engine (XCE) — architecture-aware code intelligence for AI coding assistants
trigger: /xce
---

# XCE Setup Skill

When the user types `/xce`, execute this skill to set up Xanther Context Engine step by step.

## Instructions

Follow these steps IN ORDER. Check each one before proceeding. Do not skip steps.

---

### STEP 1 — Detect environment

Run these checks and report what you find:

```bash
python3 --version       # need 3.10+
docker --version        # need Docker running
git --version
```

If Python < 3.10: tell user to upgrade. Do not proceed.
If Docker not found: tell user to install Docker Desktop and restart.

---

### STEP 2 — Install XCE

```bash
pip install xanther-context-engine
```

Verify installation:
```bash
xce --help
```

If `xce` command not found, try: `python -m xce --help`

---

### STEP 3 — Start infrastructure

```bash
# In the project directory:
curl -fsSL https://raw.githubusercontent.com/Xanther-Ai/xanther-context-engine/main/docker-compose.yml -o docker-compose.xce.yml
docker compose -f docker-compose.xce.yml up -d neo4j
```

Wait for Neo4j to be ready:
```bash
until docker exec $(docker ps -qf "name=neo4j") cypher-shell -u neo4j -p xce_dev_password "RETURN 1" 2>/dev/null; do
  echo "Waiting for Neo4j..."; sleep 3
done
echo "✓ Neo4j ready"
```

---

### STEP 4 — Configure environment

Check if `.env` exists in current directory. If not, create it:

```bash
cat > .env << 'EOF'
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xce_dev_password
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_DIMENSIONS=512
EOF
```

Ask the user: "Do you have an OpenRouter API key for LLM-powered doc generation? (optional — XCE works without it but layers 2-4 will be skipped)"

If yes, append to .env:
```bash
echo "OPENROUTER_API_KEY=<their-key>" >> .env
```

---

### STEP 5 — Index the repository

Index the current directory:
```bash
xce index . --repo-id $(basename $(pwd)) --smart-docs
```

If `--smart-docs` fails, try without:
```bash
xce index . --repo-id $(basename $(pwd))
```

Watch for output. Indexing complete when you see:
```
✓ Indexing complete
  Nodes: ...
  Edges: ...
```

---

### STEP 6 — Verify the index

```bash
xce status
```

Should show the repo with node/edge counts. If count is 0, indexing failed — check .env.

---

### STEP 7 — Start MCP server

```bash
xce serve &
```

Wait 2 seconds, then verify:
```bash
curl -s http://localhost:8000/health 2>/dev/null || echo "stdio mode (no HTTP endpoint)"
```

Note: stdio mode is normal for local IDE use.

---

### STEP 8 — Configure IDE

**For Claude Code** — add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "xce": {
      "command": "xce-mcp-server",
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_PASSWORD": "xce_dev_password"
      }
    }
  }
}
```

**For Kiro** — add to `~/.kiro/settings/mcp.json` with the same structure.

Tell user to restart their IDE after adding the config.

---

### STEP 9 — Verify tools are available

After IDE restart, verify the tools are available by asking the user to type in Claude Code / Kiro:

```
What MCP tools do I have available?
```

They should see: `xce_architecture_context`, `xce_search`, `xce_impact_analysis`, `xce_trace`, `xce_index_repo`

---

### STEP 10 — First query

Run a test query to confirm XCE is working:
```
Use xce_architecture_context to explain how the main entry point of this codebase works
```

If this returns structured architectural context, XCE is working correctly.

---

## Troubleshooting

**"Neo4j connection refused"** → `docker compose -f docker-compose.xce.yml ps` — make sure neo4j is running
**"No nodes indexed"** → Check .env has correct NEO4J_PASSWORD, re-run `xce index .`
**"xce command not found"** → Run `pip install xanther-context-engine` and check PATH
**Slow indexing** → Use `--smart-docs` flag, or set `OPENROUTER_API_KEY` for faster parallel generation

## What you get

After setup, XCE gives your AI:
- `xce_architecture_context` — what does this file/function do architecturally?
- `xce_search` — find code by meaning, not just text
- `xce_impact_analysis` — what breaks if I change this?
- `xce_trace` — trace from code up to architectural documentation

SWE-bench Verified: MiniMax M2.5 + XCE = 78.2% (beats Claude Opus 4.5 at 16x lower cost)
