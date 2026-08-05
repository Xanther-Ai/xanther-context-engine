"""Xanther Context Engine (XCE) — Graph RAG context retrieval for coding agents."""

__version__ = "0.1.0"

# Re-exports for backward compatibility
from xce.graph.store import GraphStore as GraphStore
from xce.indexing.doc_generator import DocGenerator as DocGenerator
from xce.indexing.embedding import EmbeddingService as EmbeddingService
from xce.indexing.indexer import IndexResult as IndexResult
from xce.indexing.summarizer import ContextSummarizer as ContextSummarizer
from xce.query.agents import (
    ArchitectureAgent as ArchitectureAgent,
    ImpactAnalysisAgent as ImpactAnalysisAgent,
    SearchDiscoveryAgent as SearchDiscoveryAgent,
    TraceabilityAgent as TraceabilityAgent,
)
from xce.query.decomposition import ProblemDecompositionAgent as ProblemDecompositionAgent
from xce.query.reasoning import ReasoningChainBuilder as ReasoningChainBuilder
from xce.query.refinement import RefinementLoop as RefinementLoop
try:
    from xce.server.mcp_server import XCEMCPServer as XCEMCPServer
except ImportError:
    # MCP package not installed, skip this import
    XCEMCPServer = None  # type: ignore
from xce.utils.circuit_breaker import (
    CircuitBreaker as CircuitBreaker,
    CircuitBreakerOpenError as CircuitBreakerOpenError,
)
from xce.utils.complexity_router import ComplexityRouter as ComplexityRouter
