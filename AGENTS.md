# Agent Instructions — Using Xanther (XCE + XME)

This project is indexed by the **Xanther Context Engine (XCE)** and, optionally,
the **Xanther Memory Engine (XME)**. When these tools are available (via the MCP
server `xce serve`), use them to ground your work in real architectural context
instead of guessing.

> TL;DR: Before you read files blindly, ask XCE. Before a risky edit, run impact
> analysis. Prefer XCE's structured answers over broad text search.

---

## When to use XCE

Reach for XCE **before** manual exploration whenever you need to:

- **Understand a codebase or subsystem** → `xce_architecture_context`
- **Find where something lives** (by meaning, symbol, or tag) → `xce_search`
- **See the blast radius of a change** before editing → `xce_impact_analysis`
- **Follow a symbol up/down abstraction levels** (code ↔ component ↔ architecture)
  → `xce_trace`
- **Refresh the graph** after significant edits → `xce_index_repo`

Do **not** use XCE for trivial, directed lookups you can resolve instantly
(e.g., opening one known file). Use it for understanding, orientation, and
impact — where structural knowledge beats reading files one by one.

---

## Recommended workflow

1. **Orient first.** On an unfamiliar task, call `xce_architecture_context` on the
   relevant file/symbol, or `xce_search` with a natural-language query, to build a
   mental model before opening files.
2. **Trace relationships.** Use `xce_trace` to connect a function to its component
   and architecture docs (or vice versa) when you need the "why," not just the "what."
3. **Check impact before editing.** Run `xce_impact_analysis` with the files you
   plan to change. Review callers, dependents, and affected modules; adjust your
   plan for anything surprising.
4. **Make the change**, following the conventions you observed.
5. **Re-index if needed.** After non-trivial edits, `xce_index_repo` (incremental)
   keeps the graph in sync. If a post-commit hook is installed
   (`xanther git-hook install`), this happens automatically on commit.

---

## XCE tools (MCP)

All tools require a `repo_id` (the identifier the repo was indexed under).

| Tool | Purpose | Required args |
|------|---------|---------------|
| `xce_architecture_context` | Architectural context for a file or symbol | `file_or_symbol`, `repo_id` |
| `xce_search` | Search the knowledge graph | `query`, `repo_id` (+ `search_type`: `semantic` \| `symbol` \| `tag`) |
| `xce_impact_analysis` | Predict blast radius of proposed changes | `changed_files` (array), `repo_id` |
| `xce_trace` | Trace across abstraction levels | `source`, `target_level` (`code` \| `component` \| `architecture`), `repo_id` |
| `xce_index_repo` | Index / re-index a repository | `repo_path`, `repo_id` (+ `incremental`, default `true`) |

### Examples

```jsonc
// Understand a module before touching it
{ "tool": "xce_architecture_context",
  "args": { "file_or_symbol": "xce/indexing/indexer.py", "repo_id": "my-repo" } }

// Semantic search for behavior
{ "tool": "xce_search",
  "args": { "query": "how does incremental indexing decide what changed?",
            "repo_id": "my-repo", "search_type": "semantic" } }

// Check what a change would affect
{ "tool": "xce_impact_analysis",
  "args": { "changed_files": ["xce/graph/store.py"], "repo_id": "my-repo" } }

// Trace a function up to its architecture doc
{ "tool": "xce_trace",
  "args": { "source": "GraphStore.upsert_edges", "target_level": "architecture",
            "repo_id": "my-repo" } }
```

---

## XME (cross-session memory) — optional

When the XME tools are present, use memory to stay consistent across sessions:

- **Recall before acting** — search past decisions, attempts, and sessions so you
  don't repeat failed approaches or contradict prior architectural decisions.
- **Record after acting** — capture what you did, decisions made, and lessons
  learned so the next session (yours or a teammate's) benefits.

If auto-recording hooks are installed (`xanther memory hooks install`), turns and
tool calls are captured automatically — you don't need to record manually.

---

## Guidance

- Prefer XCE's structured, architecture-aware answers over broad grep/file reads
  when the goal is understanding or impact.
- Treat `xce_impact_analysis` output as a checklist: verify callers and dependents
  before considering an edit complete.
- Keep the graph fresh — re-index (or rely on the post-commit hook) after
  meaningful changes so future queries stay accurate.
- If a tool returns nothing useful, the repo may be unindexed or indexed under a
  different `repo_id`. Confirm with `xanther status`.
