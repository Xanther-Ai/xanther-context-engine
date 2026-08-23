# Xanther Memory Hooks — Setup Guide

## How Memory Works

Xanther uses a single `agentStop` hook that fires after every agent response. It reminds the agent to record meaningful actions into XME memory, which makes them searchable in future sessions.

```
Agent makes changes → agentStop fires → agent records summary → stored in Neo4j + SQLite → searchable via `xanther query`
```

## Prerequisites

1. **Xanther installed:** `pip install -e .` in the xanther-context-engine repo
2. **Neo4j running:** `docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/xce_dev_password neo4j:5`
3. **`.env` configured:** `NEO4J_PASSWORD=xce_dev_password`

## Hook Files

Located in `.kiro/hooks/`:

### `xme-session-end.kiro.hook` (active — the main one)

```json
{
  "name": "XME Memory Record",
  "version": "1.0.0",
  "when": { "type": "agentStop" },
  "then": {
    "type": "askAgent",
    "prompt": "If you made meaningful changes in this turn (file edits, commands), silently run: python3 .xanther/ingest_turn.py --action \"<1-sentence summary>\" --files \"<comma-separated files>\". If this was only a question/answer with no file changes, do nothing. Do not show output to user."
  }
}
```

This is an `askAgent` hook — after every response, it sends a reminder to the agent. The agent then decides whether to record memory (only if it made changes).

### `xme-record-turn.kiro.hook` and `xme-record-tool.kiro.hook`

Disabled (just echo). Left in place as placeholders for future use.

## Steering File

`.kiro/steering/xanther-memory.md` (auto-included in every conversation) provides the agent with instructions on how to use memory:

- `--action` for recording what was done
- `--decision` for architectural decisions
- `--fact` for important project facts
- `xanther query` before starting complex work

## Manual Memory Recording

If hooks aren't working or you want to manually record:

```bash
# Record an action
python3 .xanther/ingest_turn.py --action "built vis-network graph explorer" --files "xce/dashboard/static/graph.html"

# Record a decision
python3 .xanther/ingest_turn.py --decision "use vis-network instead of d3 for graph rendering"

# Record a fact
python3 .xanther/ingest_turn.py --fact "Flask repo has 2895 nodes and 5095 edges"
```

## Querying Memory

```bash
# Search all memory for this project
xanther query "graph visualization" --repo xanther-context-engine

# Searching returns both:
#   - Neo4j facts (decisions, project facts)
#   - SQLite episodes (past actions, session summaries)
```

## Verifying Memory Works

```bash
# 1. Record something
python3 .xanther/ingest_turn.py --fact "test fact for verification"

# 2. Query it back
xanther query "test verification" --repo xanther-context-engine
# Should show: Facts: 1 retrieved
```

## Troubleshooting

**"0 retrieved" on query:**
- Check Neo4j is running: `nc -z localhost 7687`
- Check `.env` has correct `NEO4J_PASSWORD`
- Rebuild FTS index if episodes aren't found:
  ```sql
  sqlite3 .xanther/xme.db "
    DROP TABLE IF EXISTS xme_episodes_fts;
    CREATE VIRTUAL TABLE xme_episodes_fts USING fts5(episode_id UNINDEXED, project_id UNINDEXED, transcript, summary);
    INSERT INTO xme_episodes_fts(episode_id, project_id, transcript, summary) SELECT episode_id, project_id, json_extract(data, '$.full_transcript'), summary FROM xme_episodes;
  "
  ```

**Hook not firing:**
- Check `.kiro/hooks/xme-session-end.kiro.hook` exists and has valid JSON
- Kiro hooks panel should show it as enabled
- The hook uses `askAgent` type — it sends a prompt to the agent, not a shell command

**"Command not found: xanther":**
- Run `pip install -e .` in the project root
- Or use full path: `.venv/bin/xanther`

## Architecture

```
.kiro/hooks/xme-session-end.kiro.hook   → askAgent: "record if you changed files"
    ↓
.kiro/steering/xanther-memory.md        → tells agent HOW to record
    ↓
.xanther/ingest_turn.py                 → CLI script: writes to Neo4j + SQLite
    ↓
Neo4j (facts) + .xanther/xme.db (episodes)  → searchable via xanther query
```
