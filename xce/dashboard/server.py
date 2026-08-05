"""
XCE Dashboard Backend Server
FastAPI server with REST API and WebSocket for the XCE Local Dashboard
"""

import asyncio
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from neo4j import AsyncGraphDatabase

from .repo_manager import RepositoryManager, Repository, RepoStatus
from .progress import ProgressTracker
from .websocket import WebSocketManager
from .stats import StatsService
from .search import SearchService, SearchResult
from .export import ExportService
from .settings import SettingsManager, DashboardSettings
from xce.graph.store import GraphStore
from xce.indexing.hash_store import HashStore


# ============ Pydantic Models ============

class IndexRequest(BaseModel):
    """Request model for triggering repository indexing"""
    repo_path: str
    repo_id: str
    incremental: bool = True


class IndexResponse(BaseModel):
    """Response model for indexing operation"""
    status: str
    repo_id: str
    nodes_count: int = 0
    edges_count: int = 0
    docs_count: int = 0
    embeddings_count: int = 0
    message: str = ""


@dataclass
class DashboardState:
    """Application state for the dashboard"""
    graph_store = None  # Will be set after initialization
    hash_store = None  # PostgreSQL store for incremental indexing hashes
    settings: DashboardSettings = field(default_factory=DashboardSettings)
    repo_manager: Optional[RepositoryManager] = None
    progress_tracker: Optional[ProgressTracker] = None
    ws_manager: Optional[WebSocketManager] = None
    stats_service: Optional[StatsService] = None
    search_service: Optional[SearchService] = None
    export_service: Optional[ExportService] = None
    settings_manager: Optional[SettingsManager] = None


state = DashboardState()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title="XCE Dashboard API",
        description="Local dashboard API for XCE knowledge graph explorer",
        version="1.0.0"
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        """Initialize services on startup"""
        try:
            await initialize_services()
            print("✓ Dashboard services initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize dashboard services: {e}")
            import traceback
            traceback.print_exc()
            raise

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown"""
        if state.graph_store:
            await state.graph_store.close()

    # Health check
    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}

    # ============ Repository Endpoints ============

    @app.get("/api/repositories")
    async def list_repositories():
        """List all indexed repositories"""
        if not state.repo_manager:
            raise HTTPException(status_code=503, detail="Dashboard services not yet initialized")
        repos = await state.repo_manager.list_repositories()
        return {"repositories": [r.__dict__ for r in repos]}

    @app.post("/api/repositories")
    async def add_repository(path: str = Body(..., embed=True)):
        """Add a new repository for indexing"""
        try:
            repo = await state.repo_manager.add_repository(path)
            return repo.__dict__
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/repositories/{repo_id}")
    async def get_repository(repo_id: str):
        """Get repository details"""
        repo = await state.repo_manager.get_repository(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        
        # Get progress info if available
        progress_info = state.progress_tracker.get_progress(repo_id)
        progress_pct = 0
        if progress_info:
            if progress_info.status == "completed":
                progress_pct = 100
            elif progress_info.total_files > 0:
                progress_pct = int((progress_info.processed_files / progress_info.total_files) * 100)
        
        return {
            "repo_id": repo.repo_id,
            "name": repo.name,
            "path": repo.path,
            "status": repo.status.value if hasattr(repo.status, 'value') else repo.status,
            "node_count": repo.node_count,
            "edge_count": repo.edge_count,
            "doc_count": 0,  # Could be enhanced to count docs
            "error_message": repo.error_message,
            "created_at": repo.last_indexed.isoformat() if repo.last_indexed else "",
            "completed_at": repo.last_indexed.isoformat() if repo.last_indexed else None,
            "progress_pct": progress_pct
        }
    
    # ============ Index Status Endpoints ============
    
    @app.get("/api/index/status/{repo_id}")
    async def get_index_status(repo_id: str):
        """Get indexing status for a specific repository"""
        repo = await state.repo_manager.get_repository(repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")
        
        # Get progress info if available
        progress_info = state.progress_tracker.get_progress(repo_id)
        
        # Calculate progress percentage
        progress_pct = 0
        if progress_info:
            if progress_info.status == "completed":
                progress_pct = 100
            elif progress_info.total_files > 0:
                progress_pct = int((progress_info.processed_files / progress_info.total_files) * 100)
        
        # Determine status string
        status_str = "unknown"
        if progress_info:
            status_str = progress_info.status.value if hasattr(progress_info.status, 'value') else progress_info.status
        elif repo.status:
            status_str = repo.status.value if hasattr(repo.status, 'value') else repo.status
        
        return {
            "repo_id": repo_id,
            "status": status_str,
            "node_count": repo.node_count,
            "edge_count": repo.edge_count,
            "progress_pct": progress_pct,
            "current_file": progress_info.current_file if progress_info else None,
            "error_message": repo.error_message
        }

    # ============ Indexing Endpoints ============

    @app.post("/api/index", response_model=IndexResponse)
    async def trigger_index(request: IndexRequest):
        """Trigger local indexing for a repository with guaranteed 4-layer workflow"""
        from xce.indexing.embedding import EmbeddingService
        from xce.indexing.doc_generator import DocGenerator
        from xce.indexing.indexer import index_repository
        from xce.config import get_settings
        
        try:
            # Get settings from xce.config (environment variables)
            settings = get_settings()
            
            # Initialize GraphStore using dashboard settings (which has Neo4j credentials)
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            
            # Initialize HashStore for PostgreSQL (incremental indexing)
            hash_store = None
            postgres_uri = os.getenv("POSTGRES_URI")
            if postgres_uri:
                try:
                    hash_store = HashStore(postgres_uri)
                    await hash_store.connect()
                    logger.info("Connected to PostgreSQL for incremental indexing")
                except Exception as e:
                    logger.warning(f"Failed to connect to PostgreSQL: {e}. Incremental indexing disabled.")
            else:
                logger.info("POSTGRES_URI not set. Incremental indexing disabled.")
            
            # ✅ GUARANTEED: Always initialize DocGenerator with proper API key
            # Uses settings from xce.config which reads from environment variables
            doc_generator = DocGenerator(
                api_key=settings.openrouter_api_key or settings.kimi_api_key,
                model="openai/gpt-4o-mini",
                batch_size=state.settings.batch_size
            )
            
            # ✅ GUARANTEED: Always initialize EmbeddingService
            # Uses settings from xce.config which reads from environment variables
            embedding_service = EmbeddingService(
                api_key=settings.openrouter_api_key or settings.kimi_api_key,
                model=state.settings.embedding_model,
                dimensions=state.settings.embedding_dimensions
            )
            
            # Start progress tracking
            await state.progress_tracker.start_tracking(request.repo_id, 0)
            await state.progress_tracker.update_status(request.repo_id, "indexing")
            
            try:
                # ✅ Run the indexing pipeline with incremental support
                result, file_hashes = await index_repository(
                    repo_path=request.repo_path,
                    repo_id=request.repo_id,
                    doc_generator=doc_generator,
                    embedding_service=embedding_service,
                    graph_store=graph_store,
                    hash_store=hash_store,
                    incremental=request.incremental
                )
                
                await state.progress_tracker.update_status(request.repo_id, "completed")
                
                return IndexResponse(
                    status="completed",
                    repo_id=request.repo_id,
                    nodes_count=result.nodes_count,
                    edges_count=result.edges_count,
                    docs_count=result.docs_count,
                    embeddings_count=result.embeddings_count,
                    message=f"Successfully indexed: {result.nodes_count} nodes, {result.edges_count} edges, {result.docs_count} docs, {result.embeddings_count} embeddings"
                )
            finally:
                await graph_store.close()
                if hash_store:
                    await hash_store.close()
                
        except Exception as e:
            await state.progress_tracker.update_status(request.repo_id, "failed")
            raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")

    @app.delete("/api/repositories/{repo_id}")
    async def remove_repository(repo_id: str):
        """Remove a repository"""
        success = await state.repo_manager.remove_repository(repo_id)
        if not success:
            raise HTTPException(status_code=404, detail="Repository not found")
        return {"success": True}

    @app.post("/api/repositories/{repo_id}/reindex")
    async def reindex_repository(repo_id: str):
        """Re-index a repository"""
        try:
            repo = await state.repo_manager.reindex_repository(repo_id)
            return repo.__dict__
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/repositories/{repo_id}/stats")
    async def get_repository_stats(repo_id: str):
        """Get repository statistics"""
        try:
            stats = await state.stats_service.get_stats(repo_id)
            return stats.__dict__ if stats else None
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ============ Symbol Call Chain Endpoints ============

    @app.get("/api/symbol/{symbol_id}/callers")
    async def get_callers(
        symbol_id: str,
        depth: int = Query(1, ge=1, le=5, description="Depth of call chain to traverse (1-5)")
    ):
        """Find all callers of a function/method (up the call stack).
        
        Returns nodes that call the specified symbol, optionally at multiple
        depth levels to show the full call chain.
        """
        try:
            # Create a GraphStore instance for this request
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            try:
                callers = await graph_store.get_callers(symbol_id, depth)
                return {
                    "symbol_id": symbol_id,
                    "depth": depth,
                    "callers": callers,
                    "count": len(callers)
                }
            finally:
                await graph_store.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get callers: {str(e)}")

    @app.get("/api/symbol/{symbol_id}/callees")
    async def get_callees(
        symbol_id: str,
        depth: int = Query(1, ge=1, le=5, description="Depth of call chain to traverse (1-5)")
    ):
        """Find all callees of a function/method (down the call stack).
        
        Returns nodes that the specified symbol calls, optionally at multiple
        depth levels to show the full call chain.
        """
        try:
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            try:
                callees = await graph_store.get_callees(symbol_id, depth)
                return {
                    "symbol_id": symbol_id,
                    "depth": depth,
                    "callees": callees,
                    "count": len(callees)
                }
            finally:
                await graph_store.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get callees: {str(e)}")

    @app.get("/api/symbol/{symbol_id}/impact")
    async def get_impact_analysis(symbol_id: str):
        """Analyze impact of changes to a symbol.
        
        Returns:
        - risk_score: 0-1 score based on fan-in (how many callers)
        - direct_dependents: Files that directly call this symbol
        - test_files: Test files that exercise this symbol
        - propagation_depth: How far down the call chain goes
        """
        try:
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            try:
                impact = await graph_store.get_impact_analysis(symbol_id)
                return impact
            finally:
                await graph_store.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get impact analysis: {str(e)}")

    @app.get("/api/symbol/{symbol_id}/trace")
    async def get_traceability(symbol_id: str):
        """Trace symbol back to requirements/tests/architecture.
        
        Returns:
        - requirement_links: DESCRIBED_BY, DETAILED_IN edges
        - test_coverage: Test files that reference this symbol
        - architecture_context: PART_OF_ARCHITECTURE edges
        """
        try:
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            try:
                trace = await graph_store.get_traceability(symbol_id)
                return trace
            finally:
                await graph_store.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get traceability: {str(e)}")

    # ============ Graph Endpoints ============

    @app.get("/api/symbol/{symbol_id}/architecture")
    async def get_architecture_context(symbol_id: str):
        """Get architecture context for a symbol.
        
        Returns:
        - architectural_role: Role in the architecture
        - design_patterns: Design patterns used
        - integration_points: How it integrates with other parts
        - quality_attributes: Quality characteristics
        - module_path: Path in the module hierarchy
        """
        try:
            graph_store = GraphStore(
                neo4j_uri=state.settings.neo4j_uri,
                neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
                embedding_dimensions=state.settings.embedding_dimensions
            )
            try:
                # Get traceability which includes architecture_context
                trace = await graph_store.get_traceability(symbol_id)
                return {
                    "symbol_id": symbol_id,
                    "architecture_context": trace.get("architecture_context", []),
                    "has_architecture_context": trace.get("has_architecture_context", False)
                }
            finally:
                await graph_store.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get architecture context: {str(e)}")

    # ============ Graph Endpoints ============

    @app.get("/api/graph/nodes")
    async def get_nodes(
        repo_id: str = Query(...),
        kind: Optional[str] = Query(None),
        filepath: Optional[str] = Query(None),
        name: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000)
    ):
        """Get graph nodes with filters"""
        try:
            nodes = await state.repo_manager.get_graph_nodes(
                repo_id, kind=kind, filepath=filepath, name=name, limit=limit
            )
            return {"nodes": nodes, "total": len(nodes), "has_more": len(nodes) >= limit}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/graph/edges")
    async def get_edges(
        repo_id: str = Query(...),
        node_id: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000)
    ):
        """Get graph edges"""
        try:
            edges = await state.repo_manager.get_graph_edges(repo_id, node_id, limit)
            return {"edges": edges, "total": len(edges)}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ============ Search Endpoints ============

    @app.get("/api/search")
    async def search(
        q: str = Query(...),
        repo_id: Optional[str] = Query(None),
        kinds: Optional[str] = Query(None),
        extensions: Optional[str] = Query(None),
        limit: int = Query(20, ge=1, le=100)
    ):
        """Search the codebase using keyword search (no API key required)"""
        try:
            node_kinds = kinds.split(",") if kinds else None
            
            # Use keyword search directly from the driver
            async with state.repo_manager.driver.session() as session:
                cypher = """
                    MATCH (n:ASTNode)
                    WHERE n.name CONTAINS $term OR n.docstring CONTAINS $term OR n.filepath CONTAINS $term
                """
                params = {"term": q.lower(), "limit": limit}
                
                if repo_id:
                    cypher += " AND n.repo_id = $repo_id"
                    params["repo_id"] = repo_id
                
                if node_kinds:
                    cypher += " AND n.kind IN $node_kinds"
                    params["node_kinds"] = node_kinds
                
                cypher += """
                    RETURN n.id as node_id, n.name as name, n.filepath as filepath,
                           n.start_line as start_line, n.end_line as end_line,
                           n.kind as kind, 0.5 as score,
                           coalesce(n.docstring, left(n.source_text, 200)) as snippet
                    LIMIT $limit
                """
                
                result = await session.run(cypher, params)
                results = []
                async for record in result:
                    results.append({
                        "node_id": record["node_id"],
                        "name": record["name"],
                        "filepath": record["filepath"],
                        "start_line": record["start_line"] or 0,
                        "end_line": record["end_line"] or 0,
                        "kind": record["kind"],
                        "score": record["score"],
                        "snippet": record["snippet"] or ""
                    })
            
            return {
                "results": results,
                "query": q,
                "total": len(results)
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/search/history")
    async def get_search_history(limit: int = Query(10, ge=1, le=50)):
        """Get search history - not available in keyword-only mode"""
        return {"history": []}

    # ============ Progress Endpoints ============

    @app.get("/api/indexing/progress")
    async def get_progress(repo_id: Optional[str] = Query(None)):
        """Get indexing progress"""
        if repo_id:
            progress = state.progress_tracker.get_progress(repo_id)
            return progress.__dict__ if progress else {"status": "not_found"}
        
        # Return all active progress
        return {"progress": []}

    @app.post("/api/indexing/cancel/{repo_id}")
    async def cancel_indexing(repo_id: str):
        """Cancel ongoing indexing"""
        await state.progress_tracker.cancel(repo_id)
        return {"success": True}

    # ============ Settings Endpoints ============

    @app.get("/api/settings")
    async def get_settings():
        """Get current settings"""
        settings = state.settings_manager.load()
        # Don't return password
        return {
            "neo4j_uri": settings.neo4j_uri,
            "neo4j_user": settings.neo4j_user,
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "batch_size": settings.batch_size,
            "server_port": settings.server_port,
            "auth_enabled": settings.auth_enabled
        }

    @app.put("/api/settings")
    async def update_settings(settings_data: dict = Body(...)):
        """Update settings"""
        errors = state.settings_manager.validate(settings_data)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        
        state.settings_manager.save(settings_data)
        return {"success": True}

    # ============ Export Endpoints ============

    @app.post("/api/export/json")
    async def export_json(repo_id: str = Body(...), node_ids: list = Body(...)):
        """Export nodes to JSON"""
        try:
            result = await state.export_service.export_json(repo_id, node_ids)
            return {"data": result}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/export/csv")
    async def export_csv(repo_id: str = Body(...), node_ids: list = Body(...)):
        """Export nodes to CSV"""
        try:
            result = await state.export_service.export_csv(repo_id, node_ids)
            return {"data": result}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/export/dot")
    async def export_dot(repo_id: str = Body(...), node_ids: list = Body(...)):
        """Export nodes to DOT format"""
        try:
            result = await state.export_service.export_dot(repo_id, node_ids)
            return {"data": result}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ============ WebSocket Endpoint ============

    @app.websocket("/ws/progress")
    async def websocket_progress(websocket: WebSocket):
        """WebSocket for real-time progress updates"""
        await state.ws_manager.connect(websocket, "client")
        try:
            while True:
                # Keep connection alive, wait for messages
                data = await websocket.receive_text()
                # Handle client messages if needed
        except WebSocketDisconnect:
            state.ws_manager.disconnect("client")

    return app


async def initialize_services():
    """Initialize all dashboard services"""
    # Load settings
    settings_manager = SettingsManager(Path(".xce_config"))
    settings = settings_manager.load()
    state.settings = settings
    state.settings_manager = settings_manager

    # Initialize Neo4j connection
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password)
    )
    
    # Test connection
    try:
        await driver.verify_connectivity()
        print(f"Connected to Neo4j at {settings.neo4j_uri}")
    except Exception as e:
        print(f"Warning: Could not connect to Neo4j: {e}")

    # Initialize GraphStore - skip schema init during startup to avoid blocking
    # Schema will be initialized on first indexing request if needed
    state.graph_store = GraphStore(
        neo4j_uri=settings.neo4j_uri,
        neo4j_auth=(settings.neo4j_user, settings.neo4j_password),
        embedding_dimensions=settings.embedding_dimensions
    )

    # Initialize services
    state.ws_manager = WebSocketManager()
    state.progress_tracker = ProgressTracker(state.ws_manager)
    state.repo_manager = RepositoryManager(driver, state.progress_tracker)
    state.stats_service = StatsService(driver)
    state.export_service = ExportService(driver)
    
    # Search service - initialize lazily with fallback to keyword-only search
    # This avoids requiring API keys at startup
    state.search_service = None  # Will be created on first search request


# Create the app instance
app = create_app()

# Serve static frontend files
static_path = Path(__file__).parent / "static"


@app.get("/")
async def serve_frontend():
    """Serve the frontend"""
    index_file = static_path / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text())
    return HTMLResponse(content="<h1>XCE Dashboard</h1><p>Frontend not built. Run 'npm run build' in xce/dashboard/ui</p>")






@app.get("/{path:path}")
async def serve_static(path: str):
    """Serve static files"""
    static_file = static_path / path
    if static_file.exists() and static_file.is_file():
        return FileResponse(static_file)
    # Fallback to index.html for SPA routing
    index_file = static_path / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text())
    return HTMLResponse(content="Not found", status_code=404)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)