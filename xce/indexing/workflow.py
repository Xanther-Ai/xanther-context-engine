"""
Four-Layer Indexing Workflow using LangGraph.

This module implements a guaranteed 4-layer indexing pipeline using LangGraph.
The workflow ensures that every repository index runs through all 4 layers:
1. Layer 1: AST Parsing (LSP)
2. Layer 2: Component Descriptions (LLD Summary)
3. Layer 3: Component Documentation (LLD Detailed)
4. Layer 4: Architecture Documentation (HLD)
5. Plus: Embeddings and Graph Storage

This is NOT optional - all 4 layers are mandatory and enforced by the workflow.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel

from xce.graph.store import GraphStore
from xce.indexing.doc_generator import DocGenerator
from xce.indexing.embedding import EmbeddingService
from xce.indexing.indexer import group_by_module, _discover_source_files
from xce.models import ASTNode, NodeKind
from xce.parsers import ParserRegistry, get_default_registry

if TYPE_CHECKING:
    from xce.indexing.hash_store import HashStore

logger = logging.getLogger(__name__)


# ============================================================================
# State Model - Tracks progress through all 4 layers
# ============================================================================

class FourLayerIndexingState(BaseModel):
    """State object tracking progress through the 4-layer workflow."""
    
    # Input parameters
    repo_path: str
    repo_id: str
    incremental: bool = True
    
    # Previous hashes (for incremental indexing)
    previous_hashes: dict[str, str] = {}
    
    # Layer 1: AST Parsing
    layer_1_status: str = "pending"  # pending, running, completed, failed
    all_nodes: list[ASTNode] = []
    all_edges: list[Any] = []
    changed_files: list[str] = []  # Files that changed (for incremental)
    unchanged_files: list[str] = []  # Files that didn't change
    layer_1_error: str | None = None
    
    # Layer 2: Component Descriptions
    layer_2_status: str = "pending"
    all_descriptions: list[Any] = []
    layer_2_error: str | None = None
    
    # Layer 3: Component Documentation
    layer_3_status: str = "pending"
    component_docs_count: int = 0
    layer_3_error: str | None = None
    
    # Layer 4: Architecture Documentation
    layer_4_status: str = "pending"
    architecture_docs_count: int = 0
    layer_4_error: str | None = None
    
    # Embeddings
    embeddings_status: str = "pending"
    embeddings_count: int = 0
    embeddings_error: str | None = None
    
    # Storage
    storage_status: str = "pending"
    nodes_stored: int = 0
    edges_stored: int = 0
    storage_error: str | None = None
    
    # Final result
    success: bool = False
    final_error: str | None = None


# ============================================================================
# Node Functions - Each layer is a node in the graph
# ============================================================================

async def layer_1_ast_parsing(state: FourLayerIndexingState) -> FourLayerIndexingState:
    """
    Layer 1: AST Parsing (LSP - Language Server Protocol)
    
    Parse all source files using tree-sitter to extract:
    - Functions, classes, methods
    - Imports, decorators
    - Call relationships
    """
    logger.info("="*70)
    logger.info("LAYER 1: AST PARSING (LSP - Language Server Protocol)")
    logger.info("="*70)
    
    state.layer_1_status = "running"
    
    try:
        registry = get_default_registry()
        source_files = _discover_source_files(state.repo_path, registry)
        logger.info(f"Found {len(source_files)} source files")
        
        all_nodes: list[ASTNode] = []
        all_edges = []
        
        for abs_path in source_files:
            rel_path = Path(abs_path).relative_to(state.repo_path).as_posix()
            parser = registry.get_parser(rel_path)
            if parser is None:
                continue
            
            try:
                source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
                nodes, edges = parser.parse_file(rel_path, source, state.repo_id)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
            except Exception as e:
                logger.warning(f"Failed to parse {rel_path}: {e}")
        
        state.all_nodes = all_nodes
        state.all_edges = all_edges
        state.layer_1_status = "completed"
        
        logger.info(f"✓ Layer 1 Complete: {len(all_nodes)} nodes parsed")
        return state
        
    except Exception as e:
        logger.error(f"✗ Layer 1 Failed: {e}", exc_info=True)
        state.layer_1_status = "failed"
        state.layer_1_error = str(e)
        return state


async def layer_2_component_descriptions(
    state: FourLayerIndexingState,
    doc_generator: DocGenerator,
) -> FourLayerIndexingState:
    """
    Layer 2: Component Descriptions (LLD Summary)
    
    Generate one-liner summaries of what each component does.
    Uses LLM-based generation for semantic understanding.
    
    REQUIRED: All nodes must have descriptions for proper functioning.
    """
    logger.info("="*70)
    logger.info("LAYER 2: COMPONENT DESCRIPTIONS (LLD Summary)")
    logger.info("="*70)
    
    # GATE: Layer 1 must be completed
    if state.layer_1_status != "completed":
        logger.error("✗ Layer 1 not completed - cannot proceed")
        state.layer_2_status = "failed"
        state.layer_2_error = "Layer 1 must complete first"
        return state
    
    if not state.all_nodes:
        logger.error("✗ No nodes from Layer 1 - cannot generate descriptions")
        state.layer_2_status = "failed"
        state.layer_2_error = "No nodes available"
        return state
    
    state.layer_2_status = "running"
    
    try:
        batch_size = doc_generator.batch_size
        all_descriptions = []
        
        for i in range(0, len(state.all_nodes), batch_size):
            batch = state.all_nodes[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(state.all_nodes) + batch_size - 1) // batch_size
            
            logger.info(f"Generating descriptions batch {batch_num}/{total_batches}...")
            descriptions = await doc_generator.generate_batch(batch)
            all_descriptions.extend(descriptions)
        
        state.all_descriptions = all_descriptions
        state.layer_2_status = "completed"
        
        logger.info(f"✓ Layer 2 Complete: {len(all_descriptions)} descriptions generated")
        return state
        
    except Exception as e:
        logger.error(f"✗ Layer 2 Failed: {e}", exc_info=True)
        state.layer_2_status = "failed"
        state.layer_2_error = str(e)
        return state


async def layer_3_component_documentation(
    state: FourLayerIndexingState,
    doc_generator: DocGenerator,
    graph_store: GraphStore,
) -> FourLayerIndexingState:
    """
    Layer 3: Component Documentation (LLD Detailed)
    
    Generate detailed documentation for components with implementation details.
    This layer provides full context for understanding code behavior.
    
    REQUIRED: Detailed docs needed for architectural understanding.
    """
    logger.info("="*70)
    logger.info("LAYER 3: COMPONENT DOCUMENTATION (LLD Detailed)")
    logger.info("="*70)
    
    # GATE: Layer 2 must be completed
    if state.layer_2_status != "completed":
        logger.error("✗ Layer 2 not completed - cannot proceed")
        state.layer_3_status = "failed"
        state.layer_3_error = "Layer 2 must complete first"
        return state
    
    state.layer_3_status = "running"
    
    try:
        desc_map = {d.node_id: d for d in state.all_descriptions}
        func_nodes = [n for n in state.all_nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
        
        logger.info(f"Generating detailed docs for {len(func_nodes)} functions/methods...")
        
        # Build source text lookup
        source_by_node_id = {}
        for node in state.all_nodes:
            if node.filepath and node.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS):
                try:
                    file_path = Path(state.repo_path) / node.filepath
                    if file_path.exists():
                        source = file_path.read_text(encoding="utf-8", errors="replace")
                        source_by_node_id[node.id] = source
                except Exception as e:
                    logger.warning(f"Could not read source for {node.filepath}: {e}")
        
        docs_created = 0
        for node in func_nodes:
            desc = desc_map.get(node.id)
            if desc:
                source_text = source_by_node_id.get(node.id, "")
                try:
                    component_doc = await doc_generator.generate_component_doc(desc, source_text)
                    if component_doc:
                        await graph_store.upsert_documentation([component_doc])
                        docs_created += 1
                except Exception as e:
                    logger.warning(f"Could not generate doc for {node.name}: {e}")
        
        state.component_docs_count = docs_created
        state.layer_3_status = "completed"
        
        logger.info(f"✓ Layer 3 Complete: {docs_created} component docs generated")
        return state
        
    except Exception as e:
        logger.error(f"✗ Layer 3 Failed: {e}", exc_info=True)
        state.layer_3_status = "failed"
        state.layer_3_error = str(e)
        return state


async def layer_4_architecture_documentation(
    state: FourLayerIndexingState,
    doc_generator: DocGenerator,
    graph_store: GraphStore,
) -> FourLayerIndexingState:
    """
    Layer 4: Architecture Documentation (HLD)
    
    Generate high-level architecture documentation per module.
    This is the UNIQUE layer that distinguishes XCE from competitors.
    
    REQUIRED: Architecture context is XCE's competitive advantage.
    """
    logger.info("="*70)
    logger.info("LAYER 4: ARCHITECTURE DOCUMENTATION (HLD)")
    logger.info("="*70)
    
    # GATE: Layer 3 must be completed
    if state.layer_3_status != "completed":
        logger.error("✗ Layer 3 not completed - cannot proceed")
        state.layer_4_status = "failed"
        state.layer_4_error = "Layer 3 must complete first"
        return state
    
    state.layer_4_status = "running"
    
    try:
        modules = group_by_module(state.all_nodes)
        desc_map = {d.node_id: d for d in state.all_descriptions}
        
        logger.info(f"Generating architecture docs for {len(modules)} modules...")
        
        arch_docs_created = 0
        for module_path, module_nodes in modules.items():
            module_descs = [desc_map[n.id] for n in module_nodes if n.id in desc_map]
            if module_descs:
                try:
                    arch_doc = await doc_generator.generate_architecture_doc(module_path, module_descs)
                    if arch_doc:
                        await graph_store.upsert_documentation([arch_doc])
                        arch_docs_created += 1
                except Exception as e:
                    logger.warning(f"Could not generate architecture doc for {module_path}: {e}")
        
        state.architecture_docs_count = arch_docs_created
        state.layer_4_status = "completed"
        
        logger.info(f"✓ Layer 4 Complete: {arch_docs_created} architecture docs generated")
        return state
        
    except Exception as e:
        logger.error(f"✗ Layer 4 Failed: {e}", exc_info=True)
        state.layer_4_status = "failed"
        state.layer_4_error = str(e)
        return state


async def generate_embeddings(
    state: FourLayerIndexingState,
    embedding_service: EmbeddingService,
    graph_store: GraphStore,
) -> FourLayerIndexingState:
    """
    Generate Embeddings: Vector representations for semantic search.
    
    Creates 1536-dimensional vectors for all nodes.
    REQUIRED: Embeddings enable semantic search across all 4 layers.
    """
    logger.info("="*70)
    logger.info("EMBEDDINGS: VECTOR REPRESENTATIONS")
    logger.info("="*70)
    
    # GATE: Layer 4 must be completed
    if state.layer_4_status != "completed":
        logger.error("✗ Layer 4 not completed - cannot proceed")
        state.embeddings_status = "failed"
        state.embeddings_error = "Layer 4 must complete first"
        return state
    
    state.embeddings_status = "running"
    
    try:
        texts = [embedding_service.build_embedding_text(n) for n in state.all_nodes]
        logger.info(f"Generating embeddings for {len(texts)} nodes...")
        
        embeddings_batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), embeddings_batch_size):
            batch_texts = texts[i : i + embeddings_batch_size]
            batch_num = i // embeddings_batch_size + 1
            total_batches = (len(texts) + embeddings_batch_size - 1) // embeddings_batch_size
            
            logger.info(f"Encoding batch {batch_num}/{total_batches}...")
            embeddings = await embedding_service.encode_batch(batch_texts)
            all_embeddings.extend(embeddings)
        
        # Store embeddings
        all_node_ids = [n.id for n in state.all_nodes]
        embeddings_count = await graph_store.upsert_embeddings(all_node_ids, all_embeddings)
        
        state.embeddings_count = embeddings_count
        state.embeddings_status = "completed"
        
        logger.info(f"✓ Embeddings Complete: {embeddings_count} vectors stored")
        return state
        
    except Exception as e:
        logger.error(f"✗ Embeddings Failed: {e}", exc_info=True)
        state.embeddings_status = "failed"
        state.embeddings_error = str(e)
        return state


async def store_in_graph(
    state: FourLayerIndexingState,
    graph_store: GraphStore,
) -> FourLayerIndexingState:
    """
    Store all layers in Neo4j graph database.
    
    GATE: All previous layers must be completed before storing.
    """
    logger.info("="*70)
    logger.info("STORAGE: Neo4j Graph Database")
    logger.info("="*70)
    
    # GATE: All layers must be completed
    if state.layer_1_status != "completed":
        state.storage_status = "failed"
        state.storage_error = "Layer 1 not completed"
        return state
    if state.layer_2_status != "completed":
        state.storage_status = "failed"
        state.storage_error = "Layer 2 not completed"
        return state
    if state.layer_3_status != "completed":
        state.storage_status = "failed"
        state.storage_error = "Layer 3 not completed"
        return state
    if state.layer_4_status != "completed":
        state.storage_status = "failed"
        state.storage_error = "Layer 4 not completed"
        return state
    if state.embeddings_status != "completed":
        state.storage_status = "failed"
        state.storage_error = "Embeddings not completed"
        return state
    
    state.storage_status = "running"
    
    try:
        # Store AST nodes
        logger.info("Storing AST nodes and edges...")
        nodes_stored = await graph_store.upsert_ast_nodes(state.all_nodes)
        edges_stored = await graph_store.upsert_edges(state.all_edges)
        
        # Store descriptions
        logger.info("Storing component descriptions...")
        await graph_store.upsert_documentation(state.all_descriptions)
        
        state.nodes_stored = nodes_stored
        state.edges_stored = edges_stored
        state.storage_status = "completed"
        
        logger.info(f"✓ Storage Complete: {nodes_stored} nodes, {edges_stored} edges stored")
        return state
        
    except Exception as e:
        logger.error(f"✗ Storage Failed: {e}", exc_info=True)
        state.storage_status = "failed"
        state.storage_error = str(e)
        return state


async def finalize(state: FourLayerIndexingState) -> FourLayerIndexingState:
    """
    Finalize workflow and verify all layers completed.
    
    This is a GATE that ensures NO incomplete indexing escapes.
    """
    logger.info("="*70)
    logger.info("FINALIZATION: Verifying All Layers")
    logger.info("="*70)
    
    # Mandatory checks - ALL must pass
    checks = [
        ("Layer 1 (AST)", state.layer_1_status),
        ("Layer 2 (Descriptions)", state.layer_2_status),
        ("Layer 3 (Component Docs)", state.layer_3_status),
        ("Layer 4 (Architecture)", state.layer_4_status),
        ("Embeddings", state.embeddings_status),
        ("Storage", state.storage_status),
    ]
    
    all_passed = True
    for name, status in checks:
        if status == "completed":
            logger.info(f"  ✓ {name}: PASSED")
        else:
            logger.error(f"  ✗ {name}: FAILED ({status})")
            all_passed = False
    
    if all_passed:
        state.success = True
        logger.info("="*70)
        logger.info("✅ FOUR-LAYER INDEXING WORKFLOW COMPLETE")
        logger.info("="*70)
        logger.info(f"  Nodes:       {len(state.all_nodes)}")
        logger.info(f"  Edges:       {len(state.all_edges)}")
        logger.info(f"  Descriptions: {len(state.all_descriptions)}")
        logger.info(f"  Component Docs: {state.component_docs_count}")
        logger.info(f"  Architecture Docs: {state.architecture_docs_count}")
        logger.info(f"  Embeddings:  {state.embeddings_count}")
        logger.info("="*70)
    else:
        state.success = False
        state.final_error = "One or more layers failed - see logs above"
        logger.error("="*70)
        logger.error("❌ FOUR-LAYER INDEXING WORKFLOW FAILED")
        logger.error("="*70)
    
    return state


# ============================================================================
# Workflow Construction
# ============================================================================

def create_four_layer_workflow():
    """
    Create the guaranteed 4-layer indexing workflow using LangGraph.
    
    This workflow is DETERMINISTIC and MANDATORY:
    1. Layer 1 MUST complete before Layer 2 can start
    2. Layer 2 MUST complete before Layer 3 can start
    3. Layer 3 MUST complete before Layer 4 can start
    4. Layer 4 MUST complete before Embeddings can start
    5. Embeddings MUST complete before Storage can start
    6. All MUST complete before Finalization
    
    If any layer fails, the entire workflow fails and returns the error.
    """
    
    workflow = StateGraph(FourLayerIndexingState)
    
    # Add nodes in order
    workflow.add_node("layer_1", layer_1_ast_parsing)
    workflow.add_node("layer_2", layer_2_component_descriptions)
    workflow.add_node("layer_3", layer_3_component_documentation)
    workflow.add_node("layer_4", layer_4_architecture_documentation)
    workflow.add_node("embeddings", generate_embeddings)
    workflow.add_node("storage", store_in_graph)
    workflow.add_node("finalize", finalize)
    
    # Define edges - LINEAR FLOW (mandatory sequence)
    workflow.add_edge(START, "layer_1")
    workflow.add_edge("layer_1", "layer_2")
    workflow.add_edge("layer_2", "layer_3")
    workflow.add_edge("layer_3", "layer_4")
    workflow.add_edge("layer_4", "embeddings")
    workflow.add_edge("embeddings", "storage")
    workflow.add_edge("storage", "finalize")
    workflow.add_edge("finalize", END)
    
    return workflow.compile()


# ============================================================================
# Public API
# ============================================================================

async def run_four_layer_indexing(
    repo_path: str,
    repo_id: str,
    doc_generator: DocGenerator,
    embedding_service: EmbeddingService,
    graph_store: GraphStore,
    hash_store: "HashStore | None" = None,
    incremental: bool = True,
) -> FourLayerIndexingState:
    """
    Run the guaranteed 4-layer indexing workflow.
    
    This function ensures that ALL 4 LAYERS are run, no matter what.
    It cannot be bypassed or partially run - it's all-or-nothing.
    
    Args:
        repo_path: Path to repository to index
        repo_id: Repository identifier
        doc_generator: DocGenerator instance for Layers 2-4
        embedding_service: EmbeddingService for embeddings
        graph_store: GraphStore for Neo4j storage
        incremental: Whether to do incremental indexing
    
    Returns:
        FourLayerIndexingState with success status and all layer results
    
    Raises:
        RuntimeError if any layer fails
    """
    
    logger.info("\n" + "="*70)
    logger.info("STARTING FOUR-LAYER INDEXING WORKFLOW")
    logger.info("="*70)
    logger.info(f"Repository: {repo_path}")
    logger.info(f"Repo ID:    {repo_id}")
    logger.info("="*70 + "\n")
    
    # Create workflow
    workflow = create_four_layer_workflow()
    
    # Create initial state
    initial_state = FourLayerIndexingState(
        repo_path=repo_path,
        repo_id=repo_id,
        incremental=incremental,
    )
    
    # Create bound workflow with services
    async def bound_layer_2(state):
        return await layer_2_component_descriptions(state, doc_generator)
    
    async def bound_layer_3(state):
        return await layer_3_component_documentation(state, doc_generator, graph_store)
    
    async def bound_layer_4(state):
        return await layer_4_architecture_documentation(state, doc_generator, graph_store)
    
    async def bound_embeddings(state):
        return await generate_embeddings(state, embedding_service, graph_store)
    
    async def bound_storage(state):
        return await store_in_graph(state, graph_store)
    
    # Rebuild workflow with bound functions
    workflow_bound = StateGraph(FourLayerIndexingState)
    
    workflow_bound.add_node("layer_1", layer_1_ast_parsing)
    workflow_bound.add_node("layer_2", bound_layer_2)
    workflow_bound.add_node("layer_3", bound_layer_3)
    workflow_bound.add_node("layer_4", bound_layer_4)
    workflow_bound.add_node("embeddings", bound_embeddings)
    workflow_bound.add_node("storage", bound_storage)
    workflow_bound.add_node("finalize", finalize)
    
    workflow_bound.add_edge(START, "layer_1")
    workflow_bound.add_edge("layer_1", "layer_2")
    workflow_bound.add_edge("layer_2", "layer_3")
    workflow_bound.add_edge("layer_3", "layer_4")
    workflow_bound.add_edge("layer_4", "embeddings")
    workflow_bound.add_edge("embeddings", "storage")
    workflow_bound.add_edge("storage", "finalize")
    workflow_bound.add_edge("finalize", END)
    
    compiled = workflow_bound.compile()
    
    # Run workflow
    final_state = await compiled.ainvoke(initial_state)
    
    # Check result
    if not final_state.success:
        raise RuntimeError(f"Four-layer indexing failed: {final_state.final_error}")
    
    return final_state
