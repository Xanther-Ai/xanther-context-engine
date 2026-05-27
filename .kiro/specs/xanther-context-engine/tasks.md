# Tasks: Xanther Context Engine (XCE)

## Task 1: Project Scaffolding & Infrastructure Setup
- [ ] 1.1 Create Python project structure with pyproject.toml, package layout (xce/), and dev dependencies (pytest, pytest-asyncio, hypothesis, ruff), no GPU/torch dependencies
- [ ] 1.2 Set up Neo4j Docker Compose configuration for local development with volume persistence
- [ ] 1.3 Create configuration module (`xce/config.py`) with environment-based settings (Neo4j URI, OpenRouter API key, LLM API keys, embedding model name, embedding dimensions, batch sizes)
- [ ] 1.4 Set up CI pipeline skeleton (GitHub Actions or equivalent) with lint, type-check, and test stages

## Task 2: AST Parser Component
- [ ] 2.1 Implement `NodeKind` enum and `ASTNode`/`ASTEdge` dataclasses in `xce/models.py`
- [ ] 2.2 Implement `ASTParser.parse_file()` using Python `ast` module — extract modules, classes, functions, methods, imports, variables, decorators with full metadata (filepath, line numbers, source text, docstring, signature)
- [ ] 2.3 Implement intra-file edge extraction: CONTAINS (parent→child), CALLS (function→function), INHERITS (child→parent class), DECORATES (decorator→definition)
- [ ] 2.4 Implement `ASTParser.parse_repository()` — discover all `.py` files, parse each, collect all nodes and edges
- [ ] 2.5 Implement `resolve_cross_file_imports()` — resolve import statements to target ASTNode IDs across files, producing IMPORTS edges
- [ ] 2.6 Implement AST node ID generation following format `{repo_id}:{filepath}:{kind}:{name}`
- [ ] 2.7 Write unit tests for AST parser: test against known Python files, verify node counts, edge types, ID uniqueness, handling of syntax errors (graceful skip), edge cases (empty files, deeply nested classes, async functions, generators, decorators)

## Task 3: Graph Storage Component
- [ ] 3.1 Implement `GraphStore.__init__()` with Neo4j async driver connection pool setup
- [ ] 3.2 Implement schema initialization — create uniqueness constraints (`ASTNode.id`, `Repository.repo_id`), indexes (`kind`, `filepath`, `name`), and vector index (`embedding_idx` with configurable dimensions, cosine similarity)
- [ ] 3.3 Implement `upsert_ast_nodes()` — MERGE on `ASTNode.id`, set all properties
- [ ] 3.4 Implement `upsert_edges()` — MERGE relationships by source/target ID and relation type
- [ ] 3.5 Implement `upsert_documentation()` — attach ComponentDescription, LLDDocument, HLDDocument nodes via DESCRIBED_BY, DETAILED_IN, PART_OF_HLD relationships
- [ ] 3.6 Implement `upsert_embeddings()` — store vector embeddings on Embedding nodes linked to ASTNodes via HAS_EMBEDDING
- [ ] 3.7 Implement `semantic_search()` — vector similarity search with optional `node_kinds` filter, returning results sorted by descending score, bounded by `top_k`
- [ ] 3.8 Implement `execute_query()` and `get_neighbors()` for raw Cypher queries and neighbor traversal
- [ ] 3.9 Write unit tests for GraphStore: test CRUD operations, upsert idempotency, semantic search ranking, data isolation by `repo_id`, schema constraint enforcement

## Task 4: Documentation Generator Component
- [ ] 4.1 Implement `ComponentDescription`, `LLDDocument`, `HLDDocument` dataclasses in `xce/models.py`
- [ ] 4.2 Implement `DocGenerator.__init__()` with LLM client configuration and batch size
- [ ] 4.3 Implement `generate_component_desc()` — prompt LLM with AST node source text and context nodes, parse structured response into `ComponentDescription`
- [ ] 4.4 Implement `generate_lld()` — prompt LLM with function source, component description, and callee information, parse into `LLDDocument`
- [ ] 4.5 Implement `generate_hld()` — prompt LLM with module-level nodes and their descriptions, parse into `HLDDocument`
- [ ] 4.6 Implement `generate_batch()` — batch multiple nodes into a single LLM call for cost efficiency
- [ ] 4.7 Implement LLM retry logic with exponential backoff (max 3 retries, base 2s, jitter) for 429/5xx responses; mark failed nodes as "doc_pending"
- [ ] 4.8 Write unit tests with mocked LLM responses: verify prompt construction, batch grouping, retry behavior, "doc_pending" marking on exhausted retries

## Task 5: Embedding Service
- [ ] 5.1 Implement `EmbeddingService` using OpenRouter embedding API (e.g., `text-embedding-3-small`, 512 dimensions) via `openai` Python client
- [ ] 5.2 Implement `build_embedding_text()` — construct text representation from node name, kind, signature, docstring, and truncated source (≤512 tokens)
- [ ] 5.3 Implement `encode_batch()` — batch API calls with rate limiting and exponential backoff
- [ ] 5.4 Implement embedding dimension validation — reject vectors not matching configured model dimensions
- [ ] 5.5 Write unit tests: verify embedding dimensions, `build_embedding_text` output format, dimension validation rejection, rate limit retry behavior

## Task 6: Repository Indexing Pipeline
- [ ] 6.1 Implement `index_repository()` orchestrator — coordinate AST parsing, doc generation, graph storage, and embedding in the correct sequence
- [ ] 6.2 Implement incremental indexing — detect changed files since last index (via file hash or mtime), skip unchanged files
- [ ] 6.3 Implement module grouping (`group_by_module()`) for HLD generation — group AST nodes by their directory/package path
- [ ] 6.4 Write integration test: index a small test repository, verify graph contains expected nodes, edges, docs, and embeddings

## Task 7: LangGraph Traversal Agents
- [ ] 7.1 Implement `TraversalState` TypedDict and `TraversalResult` dataclass in `xce/models.py`
- [ ] 7.2 Implement Architecture Agent state machine (locate → expand → enrich → synthesize) using LangGraph `StateGraph` — locate nodes by name/path or semantic search, expand to parent modules and HLD components, enrich with documentation, terminate at max_depth or 30 context items
- [ ] 7.3 Implement Traceability Agent — build bidirectional trace chains: ASTNode → ComponentDescription → LLDDocument → HLDDocument, supporting both code-to-design and design-to-code directions
- [ ] 7.4 Implement Impact Analysis Agent — BFS walk of reverse CALLS/IMPORTS edges up to `max_depth`, score nodes as `1/(depth+1)`, collect HLD context for impacted components, rank by impact score
- [ ] 7.5 Implement Search & Discovery Agent — hybrid semantic (embedding similarity) + structural (name/path match) search, support search types: semantic, symbol, tag
- [ ] 7.6 Write unit tests for each agent with mocked GraphStore: verify state transitions, termination conditions, score calculations, result ordering

## Task 8: Context Summarizer
- [ ] 8.1 Implement `ContextSummarizer.__init__()` with Kimi/GLM model configuration and token budget
- [ ] 8.2 Implement context merging and deduplication — merge contexts from multiple traversal results, deduplicate by `node_id`
- [ ] 8.3 Implement relevance ranking — compute combined score: `0.6 * semantic_similarity + 0.4 * impact_score`, sort descending
- [ ] 8.4 Implement token budget enforcement — select contexts within `max_tokens - RESERVED_FOR_SUMMARY` (800 tokens reserved), truncate if needed
- [ ] 8.5 Implement LLM summarization — build summary prompt from selected contexts, call Kimi/GLM, extract key facts, preserve code snippets verbatim
- [ ] 8.6 Write unit tests: verify deduplication, token budget enforcement (property test: output ≤ max_tokens for any input), ranking order, code snippet preservation

## Task 9: MCP Server
- [ ] 9.1 Implement `XCEMCPServer` with MCP SDK — register 5 tools (`xce_architecture_context`, `xce_trace`, `xce_impact_analysis`, `xce_search`, `xce_index_repo`) with JSON schemas
- [ ] 9.2 Implement `handle_tool_call()` routing — dispatch to correct agent based on tool name, format agent results as `TextContent`
- [ ] 9.3 Implement input validation — validate all tool arguments against JSON schemas, return well-formed errors for invalid inputs
- [ ] 9.4 Implement stdio transport for local deployment and SSE transport (via FastAPI/uvicorn) for remote deployment with auth tokens
- [ ] 9.5 Write unit tests: verify tool registration, routing to correct agents, input validation error responses, response format

## Task 10: Error Handling & Resilience
- [ ] 10.1 Implement Neo4j circuit breaker — open after 3 consecutive failures, 30s timeout, half-open probe on timeout expiry
- [ ] 10.2 Implement graceful source code error handling — catch `SyntaxError` during AST parsing, log warning, skip file, continue with remaining files
- [ ] 10.3 Implement embedding dimension mismatch detection and rejection with clear error messages
- [ ] 10.4 Implement token budget overflow handling — post-truncate summarizer output if LLM exceeds budget
- [ ] 10.5 Write unit tests: verify circuit breaker state transitions, syntax error skip behavior, dimension rejection, overflow truncation

## Task 11: SWE-bench Test Harness
- [ ] 11.1 Implement `SWEBenchTestHarness` — load SWE-bench dataset, manage instances (instance_id, repo, base_commit, problem_statement, patches)
- [ ] 11.2 Implement `run_instance()` — orchestrate full pipeline per instance: checkout base commit → index repo → query context via MCP → generate patch → evaluate against gold patch
- [ ] 11.3 Implement `run_django_subset()` — run the Django subset (~50 instances) as the primary validation route
- [ ] 11.4 Implement `compute_metrics()` — aggregate resolve rate, cost per instance (USD), latency per instance (seconds), error rate
- [ ] 11.5 Implement `compare_to_baseline()` — compare against Sonnet (56%), prior XCE (64%), Opus SOTA (62.7%)
- [ ] 11.6 Integrate test harness into CI — run Django subset on PR, fail if resolve rate < 60%

## Task 12: Deployment Configuration
- [ ] 12.1 Create Dockerfile for XCE application (FastAPI + LangGraph agents + MCP server) — CPU-only, no GPU dependencies
- [ ] 12.2 Create Docker Compose for full local stack (XCE app + Neo4j)
- [ ] 12.3 Create RunPod deployment config — CPU pod with persistent volume for Neo4j data, environment variables for API keys (OpenRouter, Kimi/GLM, LLM provider)
- [ ] 12.4 Document deployment instructions, environment variables, API key setup, and cost estimates (~$22/mo RunPod CPU pod + API usage costs)


## Task 13: Multi-hop Reasoning Chain Builder
- [ ] 13.1 Implement `ReasoningChain`, `ChainStep` dataclasses in `xce/models.py`
- [ ] 13.2 Implement `ReasoningChainBuilder.__init__()` with graph store, LLM client, and max chain length configuration
- [ ] 13.3 Implement `_find_connected_paths()` — query Neo4j for paths of 3-4 connected nodes within traversal results using CALLS/IMPORTS/INHERITS/CONTAINS edges
- [ ] 13.4 Implement `build_chains()` — score candidate paths by semantic relevance to query, select top-k, generate narratives via LLM, fill per-step insights
- [ ] 13.5 Implement `_narrate_chain()` — prompt LLM to generate a concise narrative explaining how a chain of code elements connects
- [ ] 13.6 Integrate `ReasoningChainBuilder` into the summarization pipeline — chains are built after traversal and before summarization, summarizer organizes output by chain narrative
- [ ] 13.7 Implement fallback to flat context when chain building fails (fewer than 3 connected nodes or LLM failure)
- [ ] 13.8 Write unit tests: verify chain length bounds (3 ≤ len ≤ max), connectivity (consecutive steps connected by edges), relevance ordering, fallback behavior, narrative generation with mocked LLM

## Task 14: Test Patch Analyzer
- [ ] 14.1 Implement `TestPatchSignal` dataclass in `xce/models.py`
- [ ] 14.2 Implement `TestPatchAnalyzer.analyze()` — parse unified diff, extract added test code lines
- [ ] 14.3 Implement `_extract_imports()` — regex-based extraction of import statements from test patch to identify target production modules/files
- [ ] 14.4 Implement `_extract_tested_symbols()` — extract function/class names called or instantiated in test bodies, excluding test framework methods (assertEqual, assertTrue, setUp, etc.)
- [ ] 14.5 Implement `_extract_assertions()` — extract assert statements to capture expected behaviors
- [ ] 14.6 Implement `_extract_edge_cases()` — detect edge case patterns (None/null checks, empty collections, boundary values, exception handling)
- [ ] 14.7 Implement `boost_traversal_priority()` — inject test patch signals as high-priority seeds into traversal agent state, directly imported symbols get priority 1.0, indirectly referenced get 0.5
- [ ] 14.8 Implement graceful handling of malformed/empty test patches — return empty `TestPatchSignal`
- [ ] 14.9 Write unit tests: verify import extraction, symbol extraction (excluding test methods), assertion extraction, edge case detection, priority scoring bounds (0.5-1.0), malformed patch handling

## Task 15: Patch Pattern Index
- [ ] 15.1 Implement `PatchPattern`, `SimilarPatch` dataclasses in `xce/models.py`
- [ ] 15.2 Implement `PatchPatternIndex.__init__()` with graph store and embedding service
- [ ] 15.3 Implement `index_gold_patches()` — parse gold patches from solved SWE-bench instances, extract changed files/symbols, compute structural signature (deterministic hash), generate problem statement embedding, store in graph
- [ ] 15.4 Implement `_compute_structural_signature()` — deterministic hash of (sorted changed_files, sorted changed_symbols, patch_type)
- [ ] 15.5 Implement `find_similar()` — hybrid retrieval using structural matching (Jaccard similarity of files/symbols) and semantic matching (embedding cosine similarity of problem statements), combined score = 0.4 * structural + 0.6 * semantic
- [ ] 15.6 Implement `_compute_similarity()` — Jaccard similarity for structural overlap, cosine similarity for semantic, weighted combination
- [ ] 15.7 Implement upsert idempotency — re-indexing same instance updates existing entry, no duplicates
- [ ] 15.8 Write unit tests: verify structural signature determinism, similarity score bounds (0.0-1.0), ranking order, upsert idempotency, retrieval with known similar patches

## Task 16: Iterative Refinement Loop
- [ ] 16.1 Implement `RefinementState`, `TestResult` dataclasses in `xce/models.py`
- [ ] 16.2 Implement `RefinementLoop.__init__()` with MCP server, impact agent, summarizer, test runner, and max iterations configuration
- [ ] 16.3 Implement `run()` — orchestrate the iterative cycle: generate patch → run tests → check convergence → analyze failure → refine context → retry
- [ ] 16.4 Implement `_generate_patch()` — call coding agent with current context and history of prior attempts
- [ ] 16.5 Implement `_run_tests()` — apply patch to repo, execute test_patch tests, collect pass/fail results and error messages
- [ ] 16.6 Implement `_analyze_failure()` — use Impact Analysis Agent to diagnose test failures, produce description of what broke and why
- [ ] 16.7 Implement `_refine_context()` — query for additional context targeting failure points, merge with existing context
- [ ] 16.8 Implement `_should_stop()` — stop if tests pass, max iterations reached, or no progress (pass rate did not improve)
- [ ] 16.9 Write unit tests: verify termination within max_iterations, convergence detection (tests pass), stagnation detection (no progress), patch/test result count parity, context refinement merging

## Task 17: Complexity Router
- [ ] 17.1 Implement `ProblemComplexity` enum and `RoutingDecision` dataclass in `xce/models.py`
- [ ] 17.2 Implement `ComplexityRouter.__init__()` with graph store and LLM client
- [ ] 17.3 Implement `_heuristic_classify()` — fast classification based on: number of files in test patch signal, presence of cross-file keywords, problem statement length/complexity indicators
- [ ] 17.4 Implement `classify()` — combine heuristic classification with optional lightweight LLM confirmation for borderline cases
- [ ] 17.5 Implement `_build_routing()` — map SIMPLE → shallow/fast (skip Architecture+Traceability, cost 0.3x), MODERATE → standard (skip Architecture, cost 0.7x), COMPLEX → deep/reasoning (all agents + Kimi thinking, cost 1.5x)
- [ ] 17.6 Implement escalation logic — when shallow pipeline fails in refinement loop, escalate complexity to next tier
- [ ] 17.7 Write unit tests: verify classification for known simple/moderate/complex problems, routing rules (correct agents skipped per tier), cost multiplier bounds, escalation behavior

## Task 18: Problem Decomposition Agent
- [ ] 18.1 Implement `SubTask`, `DecompositionResult` dataclasses in `xce/models.py`
- [ ] 18.2 Implement `ProblemDecompositionAgent.__init__()` with LLM client and graph store
- [ ] 18.3 Implement `decompose()` — prompt LLM to break problem into 3-5 sub-tasks, parse response into `SubTask` objects with search queries and target agents
- [ ] 18.4 Implement `_validate_subtasks()` — check that referenced symbols/files exist in the graph, remove invalid sub-tasks (except "search" agent tasks which can search for anything)
- [ ] 18.5 Implement `_build_state_graph()` — LangGraph state machine: analyze_problem → generate_subtasks → validate_subtasks → plan_execution → END
- [ ] 18.6 Implement `execute_plan()` — topological sort of sub-tasks respecting dependencies, parallel execution of independent tasks, aggregate results
- [ ] 18.7 Implement `build_execution_plan()` — group independent sub-tasks for parallel execution, handle circular dependencies by breaking ties with priority
- [ ] 18.8 Implement test patch signal injection — add tested symbols as high-priority (priority 0) sub-tasks when `TestPatchSignal` is provided
- [ ] 18.9 Implement fallback — if decomposition fails (LLM error or all sub-tasks invalid), fall back to single full-pipeline query with original problem statement
- [ ] 18.10 Write unit tests: verify sub-task count (3-5), target agent validity, execution plan completeness (all tasks covered once), dependency ordering, test patch signal injection, fallback behavior, parallel execution grouping
