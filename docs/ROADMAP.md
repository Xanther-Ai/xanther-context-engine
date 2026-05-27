# Xanther Strategic Roadmap

## Vision

Xanther becomes the definitive codebase intelligence platform — combining the best of Serena (LSP-level navigation), Graphify (multi-modal knowledge graphs + visualization), and our own innovations (HLD/LLD depth, multi-hop traversal, impact analysis) into one tool that gets smarter over time.

The core engine is source-available under AGPL-3.0 (free for individuals and open source projects, enterprise use requires a commercial license). The memory engine (XME) is proprietary and hosted-only — the moat that makes Xanther indispensable for teams.

---

## Product Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      XANTHER (Unified Product)                    │
│         "The codebase intelligence layer that learns"             │
├──────────────────────────────────┬───────────────────────────────┤
│   XCE (Context Engine)           │   XME (Memory Engine)          │
│   Source-Available · AGPL-3.0    │   Proprietary · Hosted Only    │
│                                  │                               │
│   PARSE (from Serena + Graphify) │   SESSION MEMORY              │
│   • Tree-sitter (19+ languages)  │   • Session persistence       │
│   • LSP integration (go-to-def)  │   • Decision memory (ADRs)    │
│   • Multi-modal (docs, diagrams) │   • Failed approach tracking  │
│                                  │   • Cross-session learning    │
│   RELATE (from XCE)              │                               │
│   • Neo4j graph (persistent)     │   TEAM INTELLIGENCE           │
│   • Call/import/inherit edges    │   • Shared team memory        │
│   • Leiden community detection   │   • PR context integration    │
│   • God nodes + surprise edges   │   • Onboarding acceleration   │
│                                  │   • Usage analytics           │
│   AUGMENT (from XCE)             │                               │
│   • LLM-generated HLD/LLD       │   ENTERPRISE                  │
│   • Component descriptions       │   • SSO/SAML                  │
│   • Semantic embeddings          │   • Private deployment        │
│   • Privacy mode (no raw code)   │   • Audit logs                │
│                                  │   • SLA + support             │
│   TRAVERSE (from XCE)            │                               │
│   • Multi-hop LangGraph agents   │                               │
│   • Impact analysis (BFS)        │                               │
│   • Traceability (code→design)   │                               │
│   • Complexity routing           │                               │
│                                  │                               │
│   VISUALIZE (from Graphify)      │                               │
│   • Interactive graph.html       │                               │
│   • GRAPH_REPORT.md              │                               │
│   • Force-directed layout        │                               │
│   • Community color-coding       │                               │
│                                  │                               │
│   SERVE (from XCE)               │                               │
│   • MCP server (stdio + SSE)     │                               │
│   • 6+ tools for agents          │                               │
│   • Steering doc generation      │                               │
│   • Works with all MCP clients   │                               │
├──────────────────────────────────┴───────────────────────────────┤
│                    HOSTED TIER (xanther.ai)                        │
│   • Managed infrastructure (Neo4j, embeddings, auth, billing)     │
│   • Pre-indexed community repos (Django, React, FastAPI, etc.)    │
│   • XME included in all paid plans                                │
│   • Team features, analytics, enterprise support                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Licensing Strategy

**AGPL-3.0** for the open source core (XCE):
- Individuals and OSS projects: free forever
- Companies using it internally: free (AGPL allows internal use)
- Companies offering it as a service (SaaS): must open source their modifications OR buy a commercial license from us
- This prevents AWS/Cursor/etc. from wrapping XCE into their product without paying

**Commercial License** for enterprise:
- Companies that want to embed XCE in proprietary products
- Companies that want XME (memory layer)
- Companies that want private deployment + support + SLA
- Pricing: contact sales (enterprise tier)

**Why AGPL over MIT**:
- MIT: anyone can take your code, wrap it in a product, sell it, and give you nothing (the Elastic/AWS problem)
- AGPL: if they modify and serve it, they must open source their changes. If they don't want to, they pay you.
- This is the MongoDB, Grafana, Minio model — proven to work for developer tools

---

## Core Product Concept: Single Knowledge Interface

### The Problem Today

Developers manage context across dozens of disconnected files:
- `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md` — manually written, always stale
- `.cursor/rules/`, `.kiro/steering/`, `CLAUDE.md` — per-IDE steering files, duplicated
- ADRs in `docs/decisions/` — written once, never updated
- Spec files in `.kiro/specs/` — per-feature, fragmented
- Onboarding docs — outdated within a week of writing

**The result**: Devs spend time managing docs instead of coding. Agents get inconsistent context. New team members read stale information.

### The Xanther Solution: One Interface, Auto-Maintained

Xanther becomes the **single source of truth** for all project knowledge. It auto-generates and auto-updates everything from the graph:

```
┌─────────────────────────────────────────────────────────────┐
│                    xanther.yaml (single config)              │
│   repo_id, languages, output preferences                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    xanther index .
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    XANTHER GRAPH (Neo4j/SQLite)               │
│   Code nodes + edges + HLD + LLD + communities + memory      │
└──────────────────────────┬──────────────────────────────────┘
                           │
              xanther generate (auto-runs on git hooks)
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              AUTO-GENERATED OUTPUTS (always fresh)            │
│                                                             │
│   .xanther/                                                  │
│   ├── ARCHITECTURE.md      # Auto-generated from HLD layer  │
│   ├── COMPONENTS.md        # Component descriptions          │
│   ├── DEPENDENCIES.md      # Dependency graph summary        │
│   ├── ONBOARDING.md        # Auto-generated getting started │
│   ├── graph.html           # Interactive visualization       │
│   ├── graph.json           # Queryable graph export          │
│   ├── GRAPH_REPORT.md      # God nodes, surprises, health   │
│   ├── steering/            # Auto-generated for all IDEs     │
│   │   ├── cursor.md        # .cursor/rules content           │
│   │   ├── claude.md        # CLAUDE.md content               │
│   │   ├── kiro.md          # .kiro/steering content          │
│   │   └── opencode.md      # opencode steering               │
│   └── api-reference.md     # Auto-generated from code        │
│                                                             │
│   MCP Server (serves all of the above to any agent)          │
└─────────────────────────────────────────────────────────────┘
```

### How It Works

1. **`xanther init`** — One command. Creates `xanther.yaml` config. Indexes the repo. Generates all docs.

2. **`xanther watch`** (or git hook) — On every commit, re-indexes changed files, regenerates affected docs. ARCHITECTURE.md stays current automatically.

3. **MCP server** — Agents query the graph directly. They never need to read the markdown files — those are for humans.

4. **Single config** (`xanther.yaml`):
```yaml
repo_id: my-project
languages: auto  # auto-detect, or explicit list
outputs:
  architecture: true
  components: true
  dependencies: true
  onboarding: true
  graph_html: true
  steering:
    cursor: true
    claude: true
    kiro: true
mcp:
  mode: stdio  # or sse
  port: 8000
```

### What Gets Auto-Generated

| Output | Source | Updates When |
|--------|--------|-------------|
| `ARCHITECTURE.md` | HLD layer (module roles, patterns, integration points) | Module structure changes |
| `COMPONENTS.md` | ComponentDesc layer (per-class/function summaries) | Any code change |
| `DEPENDENCIES.md` | Import/call edges (dependency graph) | Import changes |
| `ONBOARDING.md` | God nodes + communities + entry points | Major structural changes |
| `graph.html` | Full graph visualization | Any change |
| `GRAPH_REPORT.md` | Graph metrics (god nodes, surprises, health) | Any change |
| Steering files | Tool descriptions + repo-specific context | Tool or config changes |
| `api-reference.md` | Function signatures + docstrings | Function changes |

### Why This Beats Separate Spec Files

| Current Approach | Xanther Approach |
|---|---|
| Write ARCHITECTURE.md manually | Auto-generated from graph, always current |
| Create .kiro/steering/ per feature | One `xanther.yaml`, steering auto-generated |
| Maintain ADRs in docs/ | Decisions stored in graph (XME), surfaced automatically |
| Onboarding docs go stale | Auto-regenerated from god nodes + entry points |
| Each IDE needs different config | Steering files generated for all IDEs simultaneously |
| Spec files per feature, fragmented | One graph contains everything, queryable |

### The Developer Experience

```bash
# First time setup (60 seconds)
pip install xanther
xanther init .

# That's it. You now have:
# - Full architecture docs in .xanther/
# - Interactive graph visualization
# - MCP server ready for any agent
# - Steering files for your IDE
# - Everything auto-updates on git commits

# Want to query it manually?
xanther query "how does authentication work?"
xanther impact "src/auth/login.py"
xanther explain "why does UserService depend on CacheManager?"

# Want to add it to your agent?
# Just add to MCP config (xanther init already told you how)
```

### How This Fits the Product

| Tier | What you get |
|------|-------------|
| **Community (AGPL)** | Local graph + auto-generated docs + MCP server + visualization |
| **Pro** | Hosted graph + XME memory + team sync |
| **Enterprise** | Private deploy + shared team memory + SSO + audit |

The free tier alone is more useful than Serena + Graphify combined. The paid tier adds memory and team features on top.

---

### Goal
Release XCE as the most complete codebase intelligence tool available — combining the best of Serena (LSP navigation, 40+ languages), Graphify (multi-modal, visualization, community detection), and XCE's unique strengths (HLD/LLD, traversal, impact analysis). Source-available under AGPL-3.0.

### 1.1 Multi-Language Support (19+ Languages)

**Refactored parser architecture:**

```
xce/parsers/
├── __init__.py              # Registry + auto-detection by extension
├── base.py                 # Abstract BaseParser interface
├── python_parser.py        # Python AST (existing, refactored)
├── typescript_parser.py    # tree-sitter TS/JS/TSX/JSX (existing, refactored)
├── go_parser.py            # tree-sitter Go
├── rust_parser.py          # tree-sitter Rust
├── java_parser.py          # tree-sitter Java
├── csharp_parser.py        # tree-sitter C#
├── ruby_parser.py          # tree-sitter Ruby
├── php_parser.py           # tree-sitter PHP
├── kotlin_parser.py        # tree-sitter Kotlin
├── swift_parser.py         # tree-sitter Swift
├── cpp_parser.py           # tree-sitter C/C++
├── scala_parser.py         # tree-sitter Scala
├── elixir_parser.py        # tree-sitter Elixir
├── lua_parser.py           # tree-sitter Lua
├── zig_parser.py           # tree-sitter Zig
├── haskell_parser.py       # tree-sitter Haskell
├── ocaml_parser.py         # tree-sitter OCaml
├── dart_parser.py          # tree-sitter Dart
└── sql_parser.py           # tree-sitter SQL (schemas, procedures)
```

**Parser interface:**
```python
class BaseParser(ABC):
    @abstractmethod
    def parse_file(self, filepath: str, source: str, repo_id: str) -> tuple[list[ASTNode], list[ASTEdge]]:
        """Parse a single file into nodes and edges."""

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return file extensions this parser handles."""

    @abstractmethod
    def language_name(self) -> str:
        """Return the language name for display."""
```

**Priority order:**
1. Go, Rust, Java, C# (most requested, largest enterprise codebases)
2. Ruby, PHP, Kotlin, Swift (popular ecosystems)
3. C/C++, Scala, Elixir, Dart (niche but valuable)
4. SQL, Lua, Zig, Haskell, OCaml (completeness)

### 1.2 Multi-Modal Input (From Graphify)

**New parsers for non-code content:**

```
xce/parsers/
├── markdown_parser.py      # Markdown → DocNodes (headings, links, code refs)
├── pdf_parser.py           # PDF → DocNodes (extracted text, diagrams)
├── image_parser.py         # Architecture diagrams → DocNodes (via vision LLM)
└── openapi_parser.py       # OpenAPI/Swagger → API endpoint nodes
```

**How it works:**
- Markdown files (README, ADRs, ARCHITECTURE.md) get parsed into `DocNode` types
- Links to code files create edges between `DocNode` and `ASTNode`
- Architecture diagrams get described by vision LLM, creating high-level nodes
- OpenAPI specs create API endpoint nodes linked to handler functions

### 1.3 Interactive Visualization (From Graphify)

**Outputs generated after indexing:**

```
xanther-out/
├── graph.html              # Interactive force-directed graph (D3.js)
├── GRAPH_REPORT.md         # Architecture summary, god nodes, surprises
├── graph.json              # Full graph export (queryable)
└── communities.json        # Leiden community assignments
```

**graph.html features:**
- Force-directed layout (D3.js, lightweight)
- Nodes colored by community (Leiden clustering)
- Node size by degree centrality (god nodes are bigger)
- Click node → show details (description, connections, HLD role)
- Search/filter by module, language, node type
- Surprise edges highlighted in red
- Exportable as PNG/SVG

**GRAPH_REPORT.md contents:**
- Top 10 god nodes (most connected components)
- Top 10 surprise edges (unexpected cross-module connections)
- Community summary (what each cluster does)
- Architecture health metrics (coupling, cohesion)
- Suggested questions for the agent

### 1.4 Community Detection + Graph Analytics (From Graphify)

**Leiden algorithm integration:**
- Run after graph construction
- Assigns each node to a community
- Communities become the basis for HLD generation (each community = one HLD module)
- Stored as `community_id` property on each ASTNode

**Graph metrics computed:**
- Degree centrality → god nodes
- Betweenness centrality → bridge nodes (critical paths)
- Cross-community edges → surprise connections
- Modularity score → architecture health

### 1.5 LSP Integration (From Serena)

**Optional LSP layer for enhanced precision:**
- If user has language server installed, XCE can use it for:
  - Precise go-to-definition (better than tree-sitter inference)
  - Find all references (exact, not heuristic)
  - Type information (for typed languages)
- Falls back to tree-sitter-only if no LSP available
- This makes XCE strictly better than Serena (has everything Serena has + more)

### 1.6 Steering Doc Auto-Generation

**After indexing, auto-generate all IDE steering files into `.xanther/steering/`:**
- `.cursor/rules/xanther.md` — for Cursor users
- `CLAUDE.md` section — for Claude Code users
- `.kiro/steering/xanther.md` — for Kiro users
- `opencode.md` section — for OpenCode users

**Content:**
```markdown
# Xanther Context Engine

Always query Xanther tools FIRST before using file search or grep.
Xanther provides architectural context that file-level tools cannot.

## Available Tools
- xanther_context: Full architectural context for a problem
- xanther_search: Semantic search across code and docs
- xanther_impact: What breaks if you change files
- xanther_trace: Trace code to design decisions
- xanther_graph: Get community/module structure

## When to use Xanther vs built-in tools
- Understanding architecture → xanther_context
- Finding related code → xanther_search
- Before making changes → xanther_impact
- Understanding why code exists → xanther_trace
- Only use grep/readFile for specific line-level content
```

### 1.7 Auto-Generated Documentation System

**The `.xanther/` output directory — single source of truth:**

After `xanther init`, the following are auto-generated and kept fresh:

```
.xanther/
├── ARCHITECTURE.md      # Generated from HLD layer
├── COMPONENTS.md        # All component descriptions
├── DEPENDENCIES.md      # Import/call graph summary
├── ONBOARDING.md        # Entry points, god nodes, getting started
├── graph.html           # Interactive D3.js visualization
├── graph.json           # Full graph export
├── GRAPH_REPORT.md      # Metrics, god nodes, surprises
├── steering/
│   ├── cursor.md        # Cursor rules
│   ├── claude.md        # CLAUDE.md content
│   ├── kiro.md          # Kiro steering
│   └── opencode.md      # OpenCode steering
└── xanther.yaml         # Single config file
```

**Auto-update triggers:**
- `xanther watch` — filesystem watcher, regenerates on save
- Git post-commit hook — regenerates affected docs on commit
- `xanther generate` — manual full regeneration

**Key principle**: Users never write or maintain these docs. Xanther generates them from the graph. If the code changes, the docs change. Always fresh, always accurate.

### 1.8 Local Mode (Zero Infrastructure)

**Two local modes:**

1. **SQLite mode** (zero dependencies):
   - Graph stored in SQLite with JSON columns
   - No Neo4j needed
   - Good for repos under 50K nodes
   - `pip install xanther && xanther init .`

2. **Docker mode** (full power):
   - Neo4j in Docker (auto-started)
   - Full vector search, graph traversal
   - Good for any size repo
   - `xanther init . --docker`

**Both modes include:**
- Local MCP server (stdio) — works with all agents
- Interactive graph.html output
- GRAPH_REPORT.md
- Steering doc generation

### 1.9 Pre-Indexed Community Repos

**Release as downloadable graph snapshots:**

Already indexed (from SWE-bench):
- Django, scikit-learn, sympy, matplotlib, pytest

New (index before launch):
- FastAPI, Flask, Express, Next.js, React
- Gin (Go), Actix (Rust), Spring Boot (Java)
- Rails (Ruby), Laravel (PHP)

**Users can:**
- Try Xanther on these repos instantly (no indexing wait)
- See what the graph looks like for a real codebase
- Query them via the hosted MCP server without signup

### 1.10 Repository Cleanup

- Remove all hardcoded secrets/keys
- Separate SaaS code into private `xanther-cloud` repo
- Add `.env.example` with all variables documented
- Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- Add `COMMERCIAL_LICENSE.md` explaining dual licensing
- CI: lint + type-check + test (already exists)
- Add integration tests for each parser

### 1.11 README & Documentation

**README structure:**
1. One-line description + badge row (stars, license, languages, PyPI)
2. "What is Xanther?" — 3 sentences
3. "3 Levels of Context" diagram
4. 60-second quickstart (local, no API key)
5. Interactive graph screenshot
6. Comparison table (vs Serena, vs Graphify, vs Sourcegraph)
7. SWE-bench results
8. MCP tools reference
9. Language support table
10. "Hosted tier" callout
11. Contributing guide link

**Documentation site** (GitHub Pages):
- Getting started guide
- Language-specific setup guides
- Architecture deep-dive
- API reference
- Comparison pages

### Success Metrics (Phase 1)
- 3,000+ GitHub stars in first month (Graphify got 5.6K, we should beat them)
- 500+ pip installs/week
- 20+ community PRs
- Featured in "awesome MCP", "awesome context engineering" lists
- 5+ blog posts/videos by community members

---

## Phase 2: Incremental Re-indexing & Freshness (Week 2-3)

### Goal
Solve the #1 technical criticism: stale indexes. Make Xanther always-fresh via git-diff based updates + semantic caching.

### Deliverables

1. **Git-Diff Watcher**
   - Monitor git commits (post-commit hook already exists in CLI)
   - Parse diff to identify changed files
   - Re-parse only changed files
   - Update affected edges (add new, remove stale)
   - Trigger via: post-commit hook, CLI command, or file watcher

2. **Subgraph Invalidation**
   - When a function signature changes → mark all callers as "needs re-enrichment"
   - When a file is deleted → remove all nodes + edges for that file
   - When a new file is added → full parse + relate + augment for that file only
   - HLD invalidation: only when module-level structure changes
   - Propagate invalidation through dependency edges

3. **Semantic Caching (From Graphify)**
   - Content-hash each file before processing
   - If hash unchanged → skip parsing entirely
   - Cache ComponentDesc/LLD/HLD by node content hash
   - Cache embeddings by node content hash
   - Result: re-indexing a 10K file repo with 5 changed files takes <10 seconds

4. **Incremental LLD/HLD Updates**
   - Re-generate ComponentDesc only for changed nodes
   - Re-generate LLD only for changed functions/methods
   - HLD: re-generate only when >5 LLD changes in a module (threshold-based)
   - Use git diff to determine blast radius

5. **Freshness Indicator**
   - Each node gets a `last_indexed_at` timestamp + `content_hash`
   - Query results include freshness score
   - Stale nodes trigger background re-indexing
   - API response includes: `"freshness": "current"` or `"freshness": "stale_by_3_commits"`

6. **Live Watch Mode**
   - `xanther watch` — watches filesystem for changes
   - On file save → re-index that file immediately
   - On git commit → re-index all changed files
   - Keeps graph always within seconds of HEAD

### Success Metrics
- Index stays <30 seconds behind HEAD for repos under 10K files
- Re-indexing a single file change takes <5 seconds
- Full re-index only needed for major refactors (>20% of files changed)
- `xanther watch` uses <100MB RAM in steady state

---

## Phase 3: XME — Xanther Memory Engine (Week 3-6)

### Goal
Build the proprietary memory layer that makes Xanther indispensable for teams. This is the moat nobody can replicate — not Serena, not Graphify, not Sourcegraph.

### Why XME Is the Moat

| Tool | Understands code now? | Remembers across sessions? | Learns from team? |
|------|----------------------|---------------------------|-------------------|
| Serena | ✅ (LSP) | ❌ | ❌ |
| Graphify | ✅ (graph) | ❌ | ❌ |
| Sourcegraph | ✅ (search) | ❌ | ❌ |
| Xanther (XCE only) | ✅ (deep) | ❌ | ❌ |
| **Xanther + XME** | ✅ (deep) | ✅ | ✅ |

### Architecture

```
Neo4j Graph (extended)
├── ASTNode, Edges, Embeddings (XCE - exists)
├── ComponentDesc, LLD, HLD (XCE - exists)
├── SessionNode (new)
│   ├── session_id, timestamp, agent_type, model
│   ├── problem_statement, outcome (success/failure)
│   ├── files_modified, tokens_used
│   └── summary (LLM-generated session recap)
├── DecisionNode (new)
│   ├── decision_id, timestamp, author
│   ├── context (why this decision was made)
│   ├── alternatives_considered
│   ├── outcome (validated/reverted/pending)
│   └── linked ADR path (if exists)
├── AttemptNode (new)
│   ├── attempt_id, session_id, timestamp
│   ├── approach_description
│   ├── result (success/failure/partial)
│   ├── failure_reason (if failed)
│   └── lessons_learned
└── New Relationships:
    ├── MODIFIED_IN (ASTNode → SessionNode)
    ├── DECIDED_IN (ASTNode → DecisionNode)
    ├── ATTEMPTED_ON (ASTNode → AttemptNode)
    ├── SUPERSEDES (DecisionNode → DecisionNode)
    └── LED_TO (AttemptNode → AttemptNode)
```

### New MCP Tools

| Tool | Description | Tier |
|------|-------------|------|
| `xanther_remember` | Store a decision/insight from current session | Hosted |
| `xanther_history` | Get modification history for a file/symbol | Hosted |
| `xanther_decisions` | Get architectural decisions affecting a component | Hosted |
| `xanther_attempts` | Get past approaches tried for similar problems | Hosted |

### How It Works

1. **Auto-capture**: At end of each agent session, XME summarizes what happened and stores it
2. **Decision prompting**: When agent makes an architectural choice, XME prompts "should I remember this?"
3. **Retrieval**: When agent starts a new task, XME provides relevant history alongside XCE's structural context
4. **Team sync**: One dev's session insights are available to all team members

### Pricing (Revised)

| Tier | XCE | XME | Price |
|------|-----|-----|-------|
| Community (AGPL) | Full local, all features | None | $0 |
| Pro (Individual) | Hosted + 10 repos | 90-day memory | $15/mo |
| Team | Hosted + unlimited repos | Shared team memory, unlimited | $25/user/mo |
| Enterprise | Private deploy + support | Full XME + SSO + audit | Custom (contact sales) |

**Enterprise license** (commercial, non-AGPL):
- Required if embedding Xanther in a proprietary product
- Required if offering Xanther as part of a SaaS
- Includes XME, priority support, SLA, private deployment
- Pricing: $500-5000/mo depending on team size

### Success Metrics
- 50% of hosted users activate memory features within first week
- Average session quality improves by 20% when memory is available (measured by first-attempt success rate)
- Teams report "onboarding time reduction" as top benefit

---

## Phase 4: Language Support Overhaul (Week 1-3, parallel with Phase 1)

### Goal
Support 19+ languages at launch — matching and exceeding both Serena (40 via LSP) and Graphify (19 via tree-sitter).

### Architecture

```
xce/parsers/
├── __init__.py          # Registry: extension → parser mapping
├── base.py             # Abstract BaseParser + NodeExtractor
├── python_parser.py    # Python AST (deep, existing)
├── treesitter_base.py  # Generic tree-sitter parser (shared logic)
├── typescript_parser.py # TS/JS/TSX/JSX (existing, refactored)
├── go_parser.py        # Go
├── rust_parser.py      # Rust
├── java_parser.py      # Java
├── csharp_parser.py    # C#
├── ruby_parser.py      # Ruby
├── php_parser.py       # PHP
├── kotlin_parser.py    # Kotlin
├── swift_parser.py     # Swift
├── cpp_parser.py       # C/C++
├── scala_parser.py     # Scala
├── elixir_parser.py    # Elixir
├── dart_parser.py      # Dart
├── sql_parser.py       # SQL schemas
├── markdown_parser.py  # Docs → DocNodes
└── openapi_parser.py   # API specs → EndpointNodes
```

### Key Insight: tree-sitter Generic Base

Most tree-sitter parsers share 80% of their logic. Build a `TreeSitterBaseParser` that:
- Loads the grammar
- Walks the tree
- Extracts common patterns (functions, classes, imports)
- Language-specific parsers only override the node-type mappings

```python
class TreeSitterBaseParser(BaseParser):
    """Generic tree-sitter parser. Subclass and set grammar + node mappings."""
    
    grammar: str  # e.g., "go", "rust", "java"
    
    # Override these per language:
    function_node_types: list[str]  # e.g., ["function_declaration", "method_declaration"]
    class_node_types: list[str]     # e.g., ["type_declaration", "class_declaration"]
    import_node_types: list[str]    # e.g., ["import_declaration"]
    call_node_types: list[str]      # e.g., ["call_expression"]
```

This means adding a new language is ~50 lines of config, not 500 lines of code.

### Priority Order (by community demand)
1. **Go** — #1 requested, huge in infra/backend
2. **Rust** — growing fast, complex codebases benefit most
3. **Java** — enterprise, massive codebases
4. **C#** — .NET ecosystem
5. **Ruby** — Rails
6. **PHP** — Laravel/WordPress
7. **Kotlin** — Android + backend
8. **Swift** — iOS
9. **C/C++** — systems programming
10. **Scala/Elixir/Dart** — completeness

### What Each Parser Must Extract (Minimum)
- Modules/packages
- Classes/structs/interfaces
- Functions/methods (with signatures)
- Imports/dependencies
- Inheritance/implementation relationships
- Call edges (function A calls function B)
- Contains edges (module contains class contains method)

### Success Metrics
- All 19 languages parse correctly on sample repos
- Each parser has >90% accuracy on node extraction (tested against known repos)
- Adding a new language takes <2 hours with the generic base

---

## Phase 5: Content & Marketing Plan (Ongoing)

### Launch Content (Week 1-2)

| Content | Channel | Goal |
|---------|---------|------|
| "Why we're releasing Xanther under AGPL" blog | Medium + Reddit + HN | Explain dual-license, build trust |
| "Xanther vs Serena vs Graphify: Honest Comparison" | Blog + landing page | Address the #1 objection, show we're the superset |
| "3 Levels of Context" explainer | Twitter thread + blog | Establish the framework |
| Launch video: "Index any repo in 60 seconds" | YouTube + Twitter | Show the product working |
| "From 30 users to open source" founder story | Indie Hackers + HN | Authentic narrative |
| Interactive demo: "Try Xanther on Django" | Website | Zero-friction trial |
| graph.html showcase (real repos) | Twitter + Reddit | Visual hook — people share pretty graphs |

### Ongoing Content (Monthly)

| Content | Channel | Goal |
|---------|---------|------|
| "Xanther + [Language] Setup Guide" | Blog + docs | SEO + onboarding per ecosystem |
| Community repo showcase (user-submitted graphs) | Twitter + Discord | Social proof |
| Benchmark updates (new models + Xanther) | Reddit + blog | Stay relevant as models improve |
| "How [Company] uses Xanther" case studies | Blog | Enterprise social proof |
| Contributor spotlights | Twitter + Discord | Community building |
| Monthly "What's New" changelog | Blog + Discord | Show momentum |
| "Xanther vs [new competitor]" comparisons | Blog | SEO + positioning |

### Reddit Strategy (Revised — Stop Getting Downvoted)

**Stop**:
- Long promotional posts in tool-specific subreddits
- Posts that read like ads
- Responding to every comment with "check out xanther.ai"

**Start**:
- Share the open source repo (not the paid product)
- "I built X, here's what I learned" framing
- Short, helpful comments on context engineering threads
- Let the community discover the hosted tier naturally
- Post in r/opensource, r/selfhosted, r/devtools (not just r/opencodeCLI)

### Community Building

- **Discord**: Active support, feature requests, showcase channel, weekly office hours
- **GitHub Discussions**: Technical conversations, RFCs for new features, language support requests
- **Contributor program**: Free Pro tier for meaningful PRs, "Xanther Champion" badge
- **Hacktoberfest**: Prepare "good first issue" labels for language parsers
- **Conference talks**: Submit to PyCon, JSConf, RustConf about context engineering

### SEO Strategy

Target keywords:
- "code context MCP server"
- "codebase knowledge graph"
- "AI coding agent context"
- "alternative to Serena MCP"
- "code architecture visualization"
- "context engineering tools"

Create landing pages for each: `/vs-serena`, `/vs-graphify`, `/vs-sourcegraph`

---

## Phase 6: Enterprise Features (Month 2-4)

### Goal
Build features that justify enterprise pricing ($500-5000/mo) and require commercial license.

### Deliverables

1. **SSO/SAML** — Enterprise auth (Okta, Azure AD, Google Workspace)
2. **Private deployment** — Run Xanther on customer's infrastructure (Helm chart, Docker Compose)
3. **Audit logs** — Who queried what, when, from which agent
4. **Role-based access** — Different repos/memory for different teams
5. **Usage analytics dashboard** — Token savings, query patterns, team productivity metrics
6. **SLA** — 99.9% uptime guarantee for hosted tier
7. **Priority support** — Dedicated Slack channel, 4-hour response time
8. **Custom integrations** — Jira, Linear, GitHub Issues → memory layer
9. **Compliance** — SOC 2 Type II (6-month process, start early)
10. **Data residency** — EU/US/APAC deployment options

### Enterprise Sales Motion
- Self-serve up to Team tier
- Enterprise requires demo call
- Land with one team (5-10 devs), expand to org
- ROI pitch: "Save $X/month in token costs, Y hours in onboarding time"

---

## Timeline Summary (Revised)

| Week | Phase | Key Milestone |
|------|-------|---------------|
| 1-3 | Phase 1 + 4 | Open source release: 19+ languages, visualization, multi-modal, local mode |
| 2-3 | Phase 2 | Incremental re-indexing + semantic caching |
| 3-6 | Phase 3 | XME beta (session memory, decisions, team sharing) |
| 1-6 | Phase 5 | Content pipeline running, community growing |
| 8-16 | Phase 6 | Enterprise features, first enterprise customers |

---

## Competitive Positioning (Final)

```
                         DEPTH OF UNDERSTANDING
                    (Syntax)              (Architecture + Intent)
                       │                        │
    PERSISTENCE   ─────┼────────────────────────┼─────
    (None)             │                        │
                       │  grep/ripgrep          │  Sourcegraph Cody
                       │  GitHub search         │  
                       │                        │
    ─────────────────  │  ─────────────────── ──┼─────
    (Session)          │                        │
                       │  Serena (LSP)          │  Graphify (graph)
                       │  IDE built-in tools    │  
                       │                        │
    ─────────────────  │  ──────────────────────┼─────
    (Persistent +      │                        │
     Team Memory)      │                        │  ★ XANTHER
                       │                        │  (graph + HLD/LLD + viz
                       │                        │   + memory + team intel
                       │                        │   + 19 languages + multi-modal)
                       │                        │
```

**Xanther = Serena + Graphify + Memory + Enterprise. In one tool.**

---

## Key Decisions (Final)

1. **License: AGPL-3.0** — Free for individuals/OSS, enterprise must buy commercial license
2. **Proprietary XME** — Memory is the paid moat, never open sourced
3. **Combined product** — Just "Xanther" to users (not XCE/XME separately)
4. **19+ languages at launch** — Match Graphify, exceed with depth
5. **Multi-modal** — Docs, diagrams, API specs alongside code
6. **Interactive visualization** — graph.html as a key differentiator
7. **Local-first** — Works without API key (SQLite mode), hosted for teams
8. **Complement + surpass** — "Everything Serena does + everything Graphify does + memory"
9. **Git-diff freshness** — Always-current index, not stale
10. **Steering docs** — Auto-generated, makes agents trust Xanther immediately

---

## Risks & Mitigations (Revised)

| Risk | Mitigation |
|------|-----------|
| AGPL scares some users | Clear messaging: "Free for all individual/internal use. Only SaaS providers need commercial license" |
| 19 languages is a lot of work | Generic tree-sitter base means each new language is ~50 lines of config |
| Graphify has head start on viz | Our viz is part of a deeper product, not standalone |
| Serena has 19.8K stars | We offer everything they do + more. Stars will follow. |
| Big company builds similar | AGPL prevents them from wrapping it. XME is proprietary. Speed of iteration. |
| Community doesn't form | Strong README + pre-indexed repos + good first issues + contributor rewards |
| Enterprise sales is hard | Start with self-serve, only go enterprise when demand appears |
| Neo4j is heavy for local | SQLite mode for small repos, Docker mode for large ones |
| XME doesn't resonate | Validate with 10 beta users before full build |
| Hosting costs grow | Tiered limits + efficient caching + enterprise revenue covers infra |
