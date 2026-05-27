"""Domain models for the Xanther Context Engine.

Dataclasses and enums used across XCE components are defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TypedDict


class NodeKind(Enum):
    """Kinds of AST nodes extracted from source code."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    IMPORT = "import"
    VARIABLE = "variable"
    DECORATOR = "decorator"
    ARGUMENT = "argument"


@dataclass
class ASTNode:
    """A single structural element extracted from source code."""

    id: str  # {repo_id}:{filepath}:{kind}:{name}
    kind: NodeKind
    name: str
    filepath: str
    start_line: int
    end_line: int
    source_text: str
    docstring: Optional[str] = None
    signature: Optional[str] = None
    parent_id: Optional[str] = None


@dataclass
class ASTEdge:
    """A directed relationship between two AST nodes."""

    source_id: str
    target_id: str
    relation: str  # "contains", "calls", "imports", "inherits", "decorates"


@dataclass
class GraphQuery:
    """A raw Cypher query with parameters."""

    cypher: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single result from a graph search or traversal."""

    node_id: str
    score: float
    node_data: dict[str, Any]
    path: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Documentation models (Task 4)
# ---------------------------------------------------------------------------


@dataclass
class ComponentDescription:
    """LLM-generated component-level description for an AST node."""

    node_id: str
    summary: str  # 1-2 sentence description
    responsibilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ComponentDoc:
    """Component-level design document for a function or method."""

    component_id: str
    algorithm_description: str
    data_flow: str
    error_handling: str
    edge_cases: list[str] = field(default_factory=list)


@dataclass
class ArchitectureDoc:
    """Architecture-level design document for a module/package."""

    module_path: str
    architectural_role: str  # e.g. "controller", "service", "model", "utility"
    design_patterns: list[str] = field(default_factory=list)
    integration_points: list[str] = field(default_factory=list)
    quality_attributes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Traversal models (Task 7)
# ---------------------------------------------------------------------------


class TraversalState(TypedDict):
    """State carried through LangGraph agent traversals."""

    query: str
    repo_id: str
    visited_nodes: list[str]
    collected_context: list[dict[str, Any]]
    current_depth: int
    max_depth: int
    reasoning_trace: list[str]


@dataclass
class TraversalResult:
    """Result returned by a traversal agent."""

    contexts: list[dict[str, Any]]
    reasoning: list[str]
    confidence: float
    nodes_visited: int


# ---------------------------------------------------------------------------
# Summarizer models (Task 8)
# ---------------------------------------------------------------------------


@dataclass
class SummarizationRequest:
    """Request to summarize traversal results."""

    traversal_results: list[TraversalResult]
    query: str
    max_tokens: int = 4000
    focus: str = "general"


@dataclass
class SummarizedContext:
    """Summarized context window for a coding agent."""

    summary: str
    key_facts: list[str]
    relevant_code_snippets: list[dict[str, str]]
    confidence: float
    token_count: int


# ---------------------------------------------------------------------------
# Reasoning Chain models (Task 13)
# ---------------------------------------------------------------------------


@dataclass
class ChainStep:
    """A single step in a multi-hop reasoning chain."""

    node_id: str
    node_name: str
    relationship: str  # How this step connects to the next
    insight: str  # One-sentence insight about this step's role
    source_snippet: Optional[str] = None


@dataclass
class ReasoningChain:
    """A multi-hop reasoning chain connecting 3-4 code elements."""

    chain_id: str
    steps: list[ChainStep]
    narrative: str  # Human-readable narrative connecting the steps
    confidence: float
    entry_node_id: str


# ---------------------------------------------------------------------------
# Test Patch Analyzer models (Task 14)
# ---------------------------------------------------------------------------


@dataclass
class TestPatchSignal:
    """Signals extracted from a SWE-bench test patch."""

    tested_files: list[str] = field(default_factory=list)
    tested_symbols: list[str] = field(default_factory=list)
    test_assertions: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    priority_score: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Patch Pattern Index models (Task 15)
# ---------------------------------------------------------------------------


@dataclass
class PatchPattern:
    """A gold patch pattern from a solved SWE-bench instance."""

    instance_id: str
    repo: str
    changed_files: list[str]
    changed_symbols: list[str]
    patch_type: str  # "bugfix", "feature", "refactor", "test"
    diff_text: str
    problem_statement: str
    structural_signature: str
    embedding: Optional[list[float]] = None


@dataclass
class SimilarPatch:
    """A similar patch found by the Patch Pattern Index."""

    pattern: PatchPattern
    similarity_score: float
    relevance_explanation: str


# ---------------------------------------------------------------------------
# Refinement Loop models (Task 16)
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """Result of running tests against a patch."""

    passed: bool
    failed_tests: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    coverage_delta: Optional[float] = None


@dataclass
class RefinementState:
    """State of the iterative refinement loop."""

    iteration: int
    max_iterations: int
    problem_statement: str
    repo_id: str
    current_context: Any  # SummarizedContext
    patch_attempts: list[str] = field(default_factory=list)
    test_results: list[TestResult] = field(default_factory=list)
    failure_analysis: list[str] = field(default_factory=list)
    converged: bool = False


# ---------------------------------------------------------------------------
# Complexity Router models (Task 17)
# ---------------------------------------------------------------------------


class ProblemComplexity(Enum):
    """Classification of problem complexity."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class RoutingDecision:
    """Routing decision from the complexity router."""

    complexity: ProblemComplexity
    pipeline_depth: str  # "shallow", "standard", "deep"
    model_tier: str  # "fast", "standard", "reasoning"
    skip_agents: list[str] = field(default_factory=list)
    estimated_cost_multiplier: float = 1.0
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Problem Decomposition models (Task 18)
# ---------------------------------------------------------------------------


@dataclass
class SubTask:
    """A sub-task from problem decomposition."""

    task_id: str
    description: str
    search_queries: list[str]
    target_agent: str  # "architecture", "trace", "impact", "search"
    priority: int = 1
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    """Result of problem decomposition."""

    original_problem: str
    sub_tasks: list[SubTask]
    execution_plan: list[list[str]]  # Parallelizable groups of task_ids
    estimated_traversals: int = 0
