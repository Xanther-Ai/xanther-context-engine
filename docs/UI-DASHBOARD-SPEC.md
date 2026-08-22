# Xanther Dashboard — UI Specification

## Overview

Local web dashboard at `localhost:8001` for visualizing code graphs, memory artifacts, and the PRAT algorithm layers. Launched via `xanther serve` or `xanther dashboard`.

## Architecture

```
Browser (localhost:8001)
    ↕ REST + WebSocket
FastAPI Backend (xce/dashboard/)
    ↕ Async Neo4j driver + SQLite
Neo4j (code graph) + SQLite (XME episodes)
```

Tech stack:
- **Backend:** FastAPI + Jinja2 templates (no separate React build step)
- **Frontend:** Vanilla JS + D3.js for graph + HTMX for interactivity
- **Graph renderer:** vis-network (interactive, handles 5k+ nodes)
- **Styling:** Tailwind CSS via CDN

## Views

### 1. Repository Selector (/)

Dashboard home. Shows all indexed repos with stats.

```
┌─────────────────────────────────────────────────┐
│  🧠 Xanther Dashboard                          │
├─────────────────────────────────────────────────┤
│  flask        2,895 nodes  5,095 edges   ➜     │
│  httpx        2,392 nodes  4,213 edges   ➜     │
│  celery      12,450 nodes 18,000 edges   ➜     │
└─────────────────────────────────────────────────┘
```

### 2. Code Graph Explorer (/repo/{repo_id}/graph)

Interactive force-directed graph of code symbols.

**Layers (PRAT visibility toggles):**
- **P (Parse):** Raw AST nodes — functions, classes, methods, modules
- **R (Relate):** Edges — CALLS, IMPORTS, INHERITS, CONTAINS
- **A (Annotate):** ComponentDescriptions, ComponentDocs overlaid on nodes
- **T (Traverse):** Highlighted paths (click "trace from A to B")

**Controls:**
- Layer toggles: [P] [R] [A] [T] — show/hide each PRAT layer
- Filter by kind: Functions | Classes | Methods | All
- Filter by module: dropdown of directories
- Search: type function name → zoom to node
- Depth slider: 1-hop, 2-hop, 3-hop from selected node

**Node rendering:**
- Color by module (directory)
- Size by fan-in (more callers = bigger node)
- Shape: circle=function, square=class, diamond=method
- On hover: show summary (Layer 2 annotation)
- On click: open detail panel

**Edge rendering:**
- CALLS: solid blue arrow
- IMPORTS: dashed green
- INHERITS: thick red
- CONTAINS: dotted gray

### 3. Node Detail Panel (/repo/{repo_id}/node/{node_id})

Slide-in panel when a node is clicked in the graph.

```
┌──────────────────────────────────────┐
│ class AsyncClient                    │
│ httpx/_client.py:45-320              │
├──────────────────────────────────────┤
│ Summary (Layer 2):                   │
│  "Async HTTP client for making..."   │
│                                      │
│ Algorithm (Layer 3):                 │
│  "Uses connection pooling via..."    │
│                                      │
│ Architecture (Layer 4):              │
│  Role: "core transport layer"        │
│  Patterns: ["facade", "builder"]     │
├──────────────────────────────────────┤
│ Callers (fan-in): 45 symbols         │
│ Callees (fan-out): 12 symbols        │
│ Impact score: 0.87 (high)            │
├──────────────────────────────────────┤
│ Memory (XME):                        │
│  • "Fixed timeout bug" (3 days ago)  │
│  • "Added retry logic" (1 week ago)  │
└──────────────────────────────────────┘
```

### 4. Memory Timeline (/repo/{repo_id}/memory)

Chronological view of all XME memory artifacts.

```
┌─────────────────────────────────────────────┐
│ 📅 Memory Timeline — flask                  │
├─────────────────────────────────────────────┤
│ Aug 22  [fact] function.run: Flask dev...   │
│ Aug 22  [fact] class.Flask: Main app...     │
│ Aug 21  [session] Fixed auth middleware     │
│ Aug 20  [decision] Use HS256 for JWT        │
│ ...                                         │
│                                             │
│ [Filter: facts | sessions | decisions]      │
│ [Search: ___________]                       │
└─────────────────────────────────────────────┘
```

### 5. Impact Analysis (/repo/{repo_id}/impact/{node_id})

"What breaks if I change this?"

- Shows blast radius as a radial graph
- Center: selected node
- Ring 1: direct callers (red if many)
- Ring 2: transitive callers
- Test files highlighted in green
- Risk score badge

### 6. PRAT Layer Inspector (/repo/{repo_id}/prat)

Shows all 4 PRAT layers side-by-side for a selected scope (file or module).

```
┌──────────┬──────────┬──────────┬──────────┐
│ P: Parse │ R: Relate│ A: Annot │ T: Trav  │
├──────────┼──────────┼──────────┼──────────┤
│ class Fl │ Flask    │ "Main    │ Request  │
│  __init__│  →run    │  app     │  →Flask  │
│  run()   │  →route  │  class"  │  →route  │
│  route() │  →bluepr │          │  →view   │
│  ...     │  ←Bluepr │ "Regist  │  →resp   │
│          │          │  routes" │          │
└──────────┴──────────┴──────────┴──────────┘
```

## API Endpoints

```
GET  /api/repos                          → list of {repo_id, nodes, edges}
GET  /api/repos/{id}/graph               → {nodes: [...], edges: [...]} for vis-network
GET  /api/repos/{id}/graph?module=flask   → filtered subgraph
GET  /api/repos/{id}/node/{node_id}      → full node detail + docs + memory
GET  /api/repos/{id}/impact/{node_id}    → impact analysis result
GET  /api/repos/{id}/memory              → memory timeline
GET  /api/repos/{id}/memory?type=fact    → filtered
GET  /api/repos/{id}/search?q=timeout    → search nodes + memory
POST /api/repos/{id}/trace               → {from: node_a, to: node_b} → path
```

## File Structure

```
xce/dashboard/
├── server.py           # FastAPI app, routes, WebSocket
├── api.py              # API endpoints (JSON)
├── templates/
│   ├── base.html       # layout + nav
│   ├── index.html      # repo selector
│   ├── graph.html      # code graph explorer
│   ├── node.html       # node detail partial
│   ├── memory.html     # memory timeline
│   ├── impact.html     # impact analysis view
│   └── prat.html       # PRAT layer inspector
└── static/
    ├── js/
    │   ├── graph.js    # vis-network graph logic
    │   ├── memory.js   # timeline rendering
    │   └── prat.js     # PRAT layer toggle
    └── css/
        └── dashboard.css
```

## Launch

```bash
xanther dashboard              # starts on localhost:8001
xanther dashboard --port 8080  # custom port
```

## Phase 1 (build now)
- Repo selector
- Code graph explorer with vis-network
- PRAT layer toggles
- Node detail panel
- Basic search

## Phase 2 (next sprint)
- Memory timeline
- Impact analysis view
- Jira/Linear integration (pull tickets, link to nodes)
- Export views as PNG/SVG

## Phase 3 (later)
- Real-time updates via WebSocket (watch for file changes)
- Multi-repo cross-graph view
- Agent session replay (watch what the agent did step by step)
