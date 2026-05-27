# Requirements: Xanther Context Engine (XCE)

## Requirement 1: AST Extraction & Indexing Pipeline

### 1.1 Parse Python source files into AST nodes
**User Story**: As a developer, I want the system to parse Python source files and extract all structural definitions (modules, classes, functions, methods, imports, variables, decorators, arguments) as AST nodes with full metadata (filepath, line numbers, source text, docstring, signature).

**Acceptance Criteria**:
- Given a valid Python source file, when `parse_file` is called, then it returns ASTNode objects for every top-level and nested class, function, method, import, variable, and decorator definition.
- Given an ASTNode, then it contains: `id` (format `{repo_id}:{filepath}:{kind}:{name}`), `kind` (valid NodeKind enum), `name`, `filepath`, `start_line`, `end_line`, `source_text`, and optional `docstring` and `signature`.
- Given a repository path, when `parse_repository` is called, then all `.py` files are discovered and parsed.

### 1.2 Extract intra-file and cross-file relationships as edges
**User Story**: As a developer, I want the parser to identify relationships between AST nodes (containment, calls, imports, inheritance, decorators) so the knowledge graph captures code structure.

**Acceptance Criteria**:
- Given a parsed file, then CONTAINS edges link parent nodes (modules, classes) to their children (functions, methods, variables).
- Given a parsed file with function calls, then CALLS edges link the calling function to the called function.
- Given a parsed file with import statements, then IMPORTS edges link the import node to the imported definition.
- Given a parsed file with class inheritance, then INHERITS edges link the child class to the parent class.
- Given a parsed file with decorators, then DECORATES edges link the decorator to the decorated definition.
- Given a multi-file repository, when `resolve_cross_file_imports` is called, then import statements are resolved to their target AST nodes across files.

### 1.3 AST Node ID uniqueness
**User Story**: As a developer, I want every AST node to have a unique identifier so nodes can be reliably referenced across the system.

**Acceptance Criteria**:
- Given any two distinct AST nodes produced by `parse_repository`, then their `id` fields are different.
- Given an AST node ID, then it follows the format `{repo_id}:{filepath}:{kind}:{name}`.

### 1.4 Edge referential integrity
**User Story**: As a developer, I want all edges to reference valid nodes so the graph has no dangling references.

**Acceptance Criteria**:
- Given any edge produced by parsing, then both `source_id` and `target_id` correspond to existing ASTNode IDs.
- Given any edge, then `source_id != target_id` (no self-referential edges).

---

## Requirement 2: Documentation Generation

### 2.1 Generate component descriptions for AST nodes
**User Story**: As a developer, I want the system to auto-generate concise component descriptions for every AST node so the knowledge graph contains human-readable summaries.

**Acceptance Criteria**:
- Given an indexed AST node, when doc generation completes, then a `ComponentDescription` exists with: `node_id`, `summary` (1-2 sentences), `responsibilities` list, and `dependencies` list.
- Given a batch of AST nodes, when `generate_batch` is called, then descriptions are generated for all nodes in the batch.
- Given all AST nodes in the repository, then every node has exactly one associated `ComponentDescription`.

### 2.2 Generate LLD documents for functions and methods
**User Story**: As a developer, I want low-level design documents generated for every function and method so the graph captures algorithm details, data flow, and error handling.

**Acceptance Criteria**:
- Given an AST node with kind FUNCTION or METHOD, when LLD generation completes, then an `LLDDocument` exists with: `component_id`, `algorithm_description`, `data_flow`, `error_handling`, and `edge_cases` list.
- Given an LLD document, then its `component_id` references an existing `ComponentDescription.node_id`.

### 2.3 Generate HLD documents for modules
**User Story**: As a developer, I want high-level design documents generated for every module/package so the graph captures architectural roles, design patterns, and integration points.

**Acceptance Criteria**:
- Given a module path in the repository, when HLD generation completes, then an `HLDDocument` exists with: `module_path`, `architectural_role`, `design_patterns` list, `integration_points` list, and `quality_attributes` list.
- Given an HLD document, then its `module_path` corresponds to an actual directory in the repository.

### 2.4 Batch processing for cost efficiency
**User Story**: As a developer, I want documentation generation to batch nodes together to minimize LLM API calls and reduce cost.

**Acceptance Criteria**:
- Given a configurable `batch_size`, when generating descriptions, then nodes are grouped into batches of at most `batch_size` nodes per LLM call.
- Given batch processing, then the output quality is equivalent to individual processing.

---

## Requirement 3: Graph Database Storage

### 3.1 Store AST nodes, edges, and documentation in Neo4j
**User Story**: As a developer, I want all extracted knowledge stored in a Neo4j graph database with proper schema, constraints, and indexes.

**Acceptance Criteria**:
- Given AST nodes, when `upsert_ast_nodes` is called, then nodes are stored with label `:ASTNode` and all metadata properties.
- Given AST edges, when `upsert_edges` is called, then relationships are created with the correct type (CONTAINS, CALLS, IMPORTS, INHERITS, DECORATES).
- Given documentation objects, when `upsert_documentation` is called, then they are attached to their corresponding AST nodes via DESCRIBED_BY, DETAILED_IN, or PART_OF_HLD relationships.
- Given the schema, then uniqueness constraints exist on `ASTNode.id` and `Repository.repo_id`.
- Given the schema, then indexes exist on `ASTNode.kind`, `ASTNode.filepath`, and `ASTNode.name`.

### 3.2 Upsert idempotency
**User Story**: As a developer, I want re-indexing to produce identical results so incremental updates are safe and predictable.

**Acceptance Criteria**:
- Given a repository indexed twice without changes, then the graph state after the second index is identical to the state after the first.
- Given an upsert operation, then existing nodes/edges are updated (not duplicated) if they already exist.

### 3.3 Semantic search via vector embeddings
**User Story**: As a developer, I want vector embeddings stored alongside AST nodes so the system supports semantic similarity search.

**Acceptance Criteria**:
- Given AST nodes, when embeddings are generated using the OpenRouter embedding API (e.g., `text-embedding-3-small`, 512 dimensions), then they are stored in a Neo4j vector index.
- Given a query embedding and `top_k`, when `semantic_search` is called, then it returns at most `top_k` results sorted by descending cosine similarity score.
- Given an optional `node_kinds` filter, then semantic search results are restricted to nodes of the specified kinds.

### 3.4 Repository data isolation
**User Story**: As a developer, I want each repository namespaced by `repo_id` so queries never leak data across repositories.

**Acceptance Criteria**:
- Given two indexed repositories with different `repo_id` values, when querying one, then no results from the other appear.
- Given all graph queries, then they are scoped to a single `repo_id`.

---

## Requirement 4: LangGraph Agent Traversal

### 4.1 Architecture Agent - Map files/symbols to HLD components
**User Story**: As a coding agent, I want to query "What is X and what HLD component does it belong to?" so I understand the architectural context of any file or symbol.

**Acceptance Criteria**:
- Given a file path or symbol name, when the Architecture Agent is queried, then it returns the matching AST nodes, their parent modules, HLD components, and sibling nodes.
- Given the query, then the response includes component descriptions and LLD documents for all collected context.
- Given the agent state machine (locate → expand → enrich → synthesize), then it terminates within `max_depth` iterations or when 30 context items are collected.

### 4.2 Traceability Agent - Trace code to design artifacts
**User Story**: As a coding agent, I want to trace "X from code up to its HLD component" so I can understand the design rationale behind any code element.

**Acceptance Criteria**:
- Given a source (code symbol) and target level (code/LLD/HLD), when the Traceability Agent is queried, then it returns a trace chain from the source through intermediate levels to the target.
- Given a trace from code to HLD, then the chain includes: ASTNode → ComponentDescription → LLDDocument → HLDDocument.

### 4.3 Impact Analysis Agent - Predict blast radius
**User Story**: As a coding agent, I want to analyze "the blast radius of changing X" so I can understand what other code will be affected by a change.

**Acceptance Criteria**:
- Given a list of changed files, when the Impact Analysis Agent is queried, then it returns all nodes within `max_depth` hops via reverse CALLS/IMPORTS edges.
- Given impacted nodes, then each has an `impact_score` in range (0, 1] where 1.0 = direct dependency, decaying as `1/(depth+1)`.
- Given file sets S1 ⊆ S2, then `impact_set(S1) ⊆ impact_set(S2)` (monotonicity).
- Given the analysis, then HLD components of impacted nodes are included in the context.
- Given the results, then nodes are ranked by impact score in descending order.

### 4.4 Search & Discovery Agent - Semantic and symbol search
**User Story**: As a coding agent, I want to "find all code symbols tagged with Y" so I can discover relevant code across the repository.

**Acceptance Criteria**:
- Given a query string and search type (semantic/symbol/tag), when the Search & Discovery Agent is queried, then it returns matching nodes with relevance scores.
- Given a semantic search, then results are ranked by embedding cosine similarity.
- Given a symbol search, then results match by exact or partial name match.

---

## Requirement 5: Context Summarization

### 5.1 Summarize traversal results within token budget
**User Story**: As a coding agent, I want traversal results distilled into a coherent, token-efficient context window so I can consume the information without exceeding my context limits.

**Acceptance Criteria**:
- Given traversal results and a `max_tokens` budget (> 800), when `summarize` is called, then the output `token_count <= max_tokens`.
- Given multiple traversal results, then contexts are merged and deduplicated by `node_id` (no duplicate node IDs in output).
- Given deduplicated contexts, then they are ranked by combined score: `0.6 * semantic_similarity + 0.4 * impact_score`.
- Given the summary, then code snippets are preserved verbatim (not paraphrased).

### 5.2 Use efficient model for summarization
**User Story**: As a system operator, I want summarization to use an efficient model (Kimi/GLM) instead of expensive models so cost is minimized.

**Acceptance Criteria**:
- Given the summarizer configuration, then it uses the Kimi thinking model or GLM for summarization.
- Given a summarization request, then the cost is significantly lower than using GPT-4 or Claude for the same task.

---

## Requirement 6: MCP Server Interface

### 6.1 Expose 5 MCP tools
**User Story**: As a coding agent, I want to access the context engine through standard MCP tools so I can query for architectural context, traces, impact analysis, search, and indexing.

**Acceptance Criteria**:
- Given the MCP server, then it exposes exactly 5 tools: `xce_architecture_context`, `xce_trace`, `xce_impact_analysis`, `xce_search`, `xce_index_repo`.
- Given each tool, then it has a valid JSON schema for its input parameters.
- Given a valid tool call, then it routes to the correct agent and returns a non-empty list of `TextContent` objects.
- Given an invalid tool call (bad arguments), then it returns a well-formed error message.

### 6.2 Support stdio and SSE transport
**User Story**: As a system operator, I want the MCP server to support both stdio (local) and SSE (remote) transport so it can be deployed flexibly.

**Acceptance Criteria**:
- Given a local deployment, then the MCP server communicates via stdio transport.
- Given a remote deployment, then the MCP server communicates via SSE over HTTPS with authentication tokens.

### 6.3 Input validation
**User Story**: As a system operator, I want all MCP tool arguments validated against their JSON schemas so malformed inputs are rejected gracefully.

**Acceptance Criteria**:
- Given a tool call with missing required arguments, then a 400-level error is returned.
- Given a tool call with arguments of wrong type, then a 400-level error is returned.
- Given a tool call with valid arguments, then it proceeds to the agent layer.

---

## Requirement 7: Incremental Indexing

### 7.1 Support incremental re-indexing
**User Story**: As a developer, I want to re-index only changed files so indexing is fast for iterative development.

**Acceptance Criteria**:
- Given `incremental=True`, when `index_repository` is called, then only files changed since the last index are reprocessed.
- Given unchanged files, then their existing AST nodes, edges, documentation, and embeddings are preserved.
- Given `incremental=False`, then all files are reprocessed regardless of change status.

---

## Requirement 8: Error Handling & Resilience

### 8.1 LLM rate limiting with exponential backoff
**User Story**: As a system operator, I want the system to handle LLM API rate limits gracefully so indexing doesn't fail on transient errors.

**Acceptance Criteria**:
- Given a 429 or 5xx response from the LLM API, then the system retries with exponential backoff (max 3 retries, base delay 2s with jitter).
- Given all retries exhausted, then the node is marked as "doc_pending" and processing continues with remaining nodes.

### 8.2 Neo4j connection loss with circuit breaker
**User Story**: As a system operator, I want the system to handle Neo4j outages gracefully so MCP clients get informative errors instead of hangs.

**Acceptance Criteria**:
- Given 3 consecutive Neo4j failures, then the circuit breaker opens for 30 seconds.
- Given an open circuit, then MCP clients receive "Context engine temporarily unavailable" error.
- Given the circuit breaker timeout expires, then a single probe query is attempted to test recovery.

### 8.3 Malformed source code graceful skip
**User Story**: As a developer, I want files with syntax errors to be skipped so they don't block indexing of the rest of the repository.

**Acceptance Criteria**:
- Given a Python file with syntax errors, when parsing, then the file is skipped with a logged warning.
- Given a skipped file, then all other files in the repository are still parsed and indexed.

### 8.4 Embedding dimension validation
**User Story**: As a system operator, I want embedding dimensions validated before storage so model changes don't corrupt the vector index.

**Acceptance Criteria**:
- Given embeddings with dimensions not matching the configured OpenRouter model (e.g., 512 for `text-embedding-3-small`), then the upsert is rejected with a clear error.
- Given an intentional model change, then a full re-embedding can be triggered.

---

## Requirement 9: SWE-bench Validation

### 9.1 Django subset test route
**User Story**: As a developer, I want to validate XCE against the SWE-bench Django subset during development so I can track progress toward the target resolve rate.

**Acceptance Criteria**:
- Given the SWE-bench Django subset (~50 instances), when the test harness runs, then it executes the full pipeline: index repo → query context → generate patch → evaluate.
- Given evaluation results, then metrics are computed: resolve rate, cost per instance (USD), latency per instance (seconds), error rate.
- Given results, then they are compared against baselines: Sonnet (56%), prior XCE (64%), Opus SOTA (62.7%).

### 9.2 CI integration with regression gate
**User Story**: As a developer, I want the test harness integrated into CI so regressions are caught before merge.

**Acceptance Criteria**:
- Given a CI run, then the Django subset test harness executes automatically.
- Given a resolve rate below 60% on the Django subset, then the CI job fails and blocks the merge.

---

## Requirement 10: Deployment & Hosting

### 10.1 Deploy on RunPod or AWS
**User Story**: As a system operator, I want the system deployable on RunPod or AWS, choosing whichever is cheaper for the workload.

**Acceptance Criteria**:
- Given the deployment, then all compute runs on a RunPod CPU pod (~$0.03/hr). No GPU required.
- Given the deployment, then embeddings are generated via the OpenRouter embedding API.
- Given the deployment, then summarization and doc generation use external LLM APIs (Kimi/GLM, OpenRouter).
- Given the deployment, then Neo4j runs as a container on the same pod with persistent volume.
- Given the deployment, then the MCP server runs as a FastAPI application with uvicorn.
- Given the deployment, then the system is designed for future upgrade to a hosted multi-tenant service.

### 10.2 Performance targets
**User Story**: As a system operator, I want the system to meet performance targets so it's practical for real-time coding assistance.

**Acceptance Criteria**:
- Given AST parsing, then throughput is at least 1000 files/minute.
- Given any MCP tool call (excluding indexing), then latency is under 3 seconds.
- Given graph traversals, then they complete in under 1 second.
- Given summarization, then it adds at most 1-2 seconds to the response.


---

## Requirement 11: Multi-hop Reasoning Chains

### 11.1 Construct reasoning chains from traversal results
**User Story**: As a coding agent, I want traversal results presented as multi-hop reasoning chains (3-4 connected insights) instead of flat node lists so I can follow the logical connections between code elements.

**Acceptance Criteria**:
- Given traversal results with at least 3 unique nodes, when `build_chains()` is called, then it returns 1-5 `ReasoningChain` objects.
- Given a `ReasoningChain`, then it has between 3 and `max_chain_length` (default 4) steps.
- Given consecutive steps `(s_i, s_{i+1})` in a chain, then there exists a graph edge (CALLS, IMPORTS, INHERITS, or CONTAINS) connecting `s_i.node_id` to `s_{i+1}.node_id`.
- Given a chain, then its `narrative` field is a non-empty human-readable explanation of how the steps connect.
- Given multiple chains, then they are ordered by descending relevance score to the original query.

### 11.2 Integrate reasoning chains into summarization
**User Story**: As a coding agent, I want the summarizer to use reasoning chains as the primary structure for context delivery so the information I receive tells a connected story.

**Acceptance Criteria**:
- Given reasoning chains and a summarization request, when `summarize()` is called, then the output organizes information by chain narrative rather than flat node listing.
- Given a chain with code snippets, then the snippets are preserved verbatim within the chain narrative.
- Given chains that exceed the token budget, then lower-relevance chains are dropped (not truncated mid-chain).

### 11.3 Fallback to flat context
**User Story**: As a system operator, I want the system to fall back to flat context delivery when chain construction fails so the pipeline never blocks on chain building.

**Acceptance Criteria**:
- Given traversal results with fewer than 3 connected nodes, when chain building fails, then the summarizer receives flat context as before.
- Given an LLM failure during narrative generation, then the system logs a warning and falls back to flat context.

---

## Requirement 12: Test-Aware Context Injection

### 12.1 Parse test patches to extract signals
**User Story**: As a developer, I want the system to parse SWE-bench test patches and extract which production code the tests exercise so context retrieval is guided by what the fix needs to touch.

**Acceptance Criteria**:
- Given a valid test patch diff, when `analyze()` is called, then it returns a `TestPatchSignal` with non-empty `tested_files` and `tested_symbols`.
- Given a test patch with import statements, then `tested_files` contains the file paths of all imported production modules.
- Given a test patch with function calls, then `tested_symbols` contains the names of all called production functions/classes (excluding test framework methods like `assertEqual`).
- Given a test patch with assertions, then `test_assertions` contains the raw assertion strings.
- Given a test patch with edge case patterns (None checks, empty collections, boundary values), then `edge_cases` lists the detected patterns.

### 12.2 Prioritize context retrieval using test signals
**User Story**: As a coding agent, I want tested symbols to be prioritized in context retrieval so the most relevant code appears first.

**Acceptance Criteria**:
- Given a `TestPatchSignal`, when injected into traversal state, then directly imported symbols have `priority_score = 1.0` and indirectly referenced symbols have `priority_score = 0.5`.
- Given test patch signals, when traversal agents run, then nodes matching tested symbols are visited before other nodes.
- Given a test patch signal with `tested_files`, then those files are always included in the context regardless of semantic similarity score.

### 12.3 Handle malformed test patches
**User Story**: As a system operator, I want malformed or empty test patches to be handled gracefully so the pipeline continues without test-aware prioritization.

**Acceptance Criteria**:
- Given an empty or malformed test patch, when `analyze()` is called, then it returns an empty `TestPatchSignal` (no files, no symbols).
- Given an empty `TestPatchSignal`, then the traversal agents use default priority (no boost).

---

## Requirement 13: Historical Patch Pattern Matching

### 13.1 Index gold patches from solved instances
**User Story**: As a developer, I want gold patches from previously solved SWE-bench instances indexed so they can be retrieved as few-shot examples for new problems.

**Acceptance Criteria**:
- Given a list of solved SWE-bench instances with gold patches, when `index_gold_patches()` is called, then each patch is stored as a `PatchPattern` with: `instance_id`, `repo`, `changed_files`, `changed_symbols`, `patch_type`, `diff_text`, `problem_statement`, `structural_signature`, and `embedding`.
- Given an indexed patch, then its `structural_signature` is a deterministic hash of `(changed_files, changed_symbols, patch_type)`.
- Given an indexed patch, then its `embedding` is generated from the `problem_statement` using the embedding service.

### 13.2 Retrieve similar patches for new problems
**User Story**: As a coding agent, I want to see similar past patches as few-shot examples so I can apply proven fix patterns to new problems.

**Acceptance Criteria**:
- Given a new problem statement and changed files, when `find_similar()` is called, then it returns at most `top_k` (default 3) `SimilarPatch` objects.
- Given similar patches, then `similarity_score` is computed as `0.4 * structural_overlap + 0.6 * semantic_similarity` where structural overlap is Jaccard similarity of changed files/symbols.
- Given similar patches, then they are ordered by descending `similarity_score`.
- Given similar patches, then each has a `relevance_explanation` describing why it's relevant.
- Given all returned patches, then `0.0 ≤ similarity_score ≤ 1.0`.

### 13.3 Growing index over time
**User Story**: As a developer, I want the patch index to grow as more instances are solved so the few-shot examples improve over time.

**Acceptance Criteria**:
- Given a newly solved instance, when its gold patch is indexed, then it becomes available for future `find_similar()` queries.
- Given duplicate indexing of the same instance, then the existing entry is updated (not duplicated).

---

## Requirement 14: Iterative Refinement Loop

### 14.1 Run context-patch-test-refine cycle
**User Story**: As a developer, I want the system to iteratively refine context based on test failure feedback so the coding agent can improve its patch across multiple attempts.

**Acceptance Criteria**:
- Given an initial context and test patch, when `run()` is called, then the loop executes: generate patch → run tests → analyze failures → refine context → retry.
- Given a maximum of 3 iterations, then the loop terminates after at most 3 iterations.
- Given tests that pass on any iteration, then the loop stops immediately and returns the successful patch.
- Given no progress between iterations (test pass rate does not improve), then the loop stops early.

### 14.2 Failure analysis drives context refinement
**User Story**: As a coding agent, I want test failure analysis to identify what context was missing so the next iteration retrieves better information.

**Acceptance Criteria**:
- Given a failed test result, when the Impact Analysis Agent analyzes the failure, then it produces a description of what broke and why.
- Given a failure analysis, when context is refined, then the new context includes additional information targeting the failure points.
- Given refined context, then it is merged with the previous context (not replaced) to preserve useful information.

### 14.3 Track all attempts and results
**User Story**: As a developer, I want all patch attempts and test results tracked so I can analyze the refinement process.

**Acceptance Criteria**:
- Given a completed refinement loop, then `len(patch_attempts) == len(test_results)`.
- Given a completed loop, then `failure_analysis` has one entry per failed iteration.
- Given the final state, then the best patch (highest test pass rate) is identifiable.

---

## Requirement 15: Smart Model Routing

### 15.1 Classify problem complexity
**User Story**: As a system operator, I want problems classified by complexity so simple fixes don't waste resources on the full traversal pipeline.

**Acceptance Criteria**:
- Given a problem statement and optional test patch signal, when `classify()` is called, then it returns a `RoutingDecision` with `complexity` in {SIMPLE, MODERATE, COMPLEX}.
- Given a SIMPLE problem (single file, obvious fix), then `pipeline_depth = "shallow"`, `model_tier = "fast"`, and `estimated_cost_multiplier ≤ 0.5`.
- Given a MODERATE problem (2-3 files, some cross-file deps), then `pipeline_depth = "standard"`, `model_tier = "standard"`, and `estimated_cost_multiplier ≤ 1.0`.
- Given a COMPLEX problem (multi-file, deep dependencies), then `pipeline_depth = "deep"`, `model_tier = "reasoning"`, and the full agent pipeline runs.

### 15.2 Route to appropriate pipeline depth
**User Story**: As a system operator, I want simple problems routed to a fast, cheap pipeline so cost and latency are minimized for easy fixes.

**Acceptance Criteria**:
- Given a SIMPLE routing decision, then only the Search agent runs (Architecture and Traceability agents are skipped).
- Given a MODERATE routing decision, then Search and Impact agents run (Architecture agent is skipped).
- Given a COMPLEX routing decision, then all agents run at full depth with Kimi thinking model for Impact Analysis and Reasoning Chain Builder.
- Given any routing decision, then `skip_agents` lists the agents that are not executed.

### 15.3 Escalate on misclassification
**User Story**: As a system operator, I want the system to escalate to a deeper pipeline when a shallow pipeline fails so misclassifications are self-correcting.

**Acceptance Criteria**:
- Given a SIMPLE classification where the shallow pipeline produces a failing patch, when the refinement loop detects no progress, then the complexity is escalated to MODERATE or COMPLEX.
- Given an escalation, then the next refinement iteration uses the deeper pipeline.

---

## Requirement 16: Problem Decomposition

### 16.1 Decompose problem into sub-tasks
**User Story**: As a coding agent, I want the problem statement broken into targeted sub-tasks so each sub-task gets its own focused traversal query.

**Acceptance Criteria**:
- Given a problem statement, when `decompose()` is called, then it returns 3-5 `SubTask` objects.
- Given a sub-task, then it has: `task_id`, `description`, `search_queries`, `target_agent` (one of "architecture", "trace", "impact", "search"), `priority`, and `depends_on`.
- Given sub-tasks, then they are validated against the graph — sub-tasks referencing non-existent symbols are removed (except "search" agent tasks).
- Given a test patch signal, then tested symbols appear as high-priority sub-tasks (priority 0).

### 16.2 Execute decomposition plan with parallelism
**User Story**: As a developer, I want independent sub-tasks executed in parallel so decomposition doesn't increase latency.

**Acceptance Criteria**:
- Given a decomposition result, when `execute_plan()` is called, then independent sub-tasks (no dependencies) run in parallel.
- Given sub-tasks with dependencies, then dependent tasks wait for their prerequisites to complete.
- Given the execution plan, then `flatten(execution_plan)` contains every `task_id` exactly once.
- Given all sub-task results, then they are aggregated into a combined list of `TraversalResult` objects.

### 16.3 Handle decomposition failures
**User Story**: As a system operator, I want decomposition failures to fall back to a single full-pipeline query so the system never blocks on decomposition.

**Acceptance Criteria**:
- Given an LLM failure during decomposition, then the system falls back to a single query using the full problem statement.
- Given sub-tasks that all fail validation, then the system falls back to a single semantic search query.
