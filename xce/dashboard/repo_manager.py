"""
Repository Manager for XCE Dashboard
Handles tracking and management of indexed repositories
"""

import asyncio
import hashlib
import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from neo4j import AsyncGraphDatabase, AsyncDriver
import logging

logger = logging.getLogger(__name__)


class RepoStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


@dataclass
class Repository:
    """Repository data model"""
    repo_id: str
    name: str
    path: str
    status: RepoStatus
    node_count: int = 0
    edge_count: int = 0
    last_indexed: Optional[datetime] = None
    error_message: Optional[str] = None


class RepositoryManager:
    """Manages indexed repositories"""
    
    def __init__(self, driver: AsyncGraphDatabase.driver, progress_tracker):
        self._driver = driver
        self.progress_tracker = progress_tracker
        self._repositories: Dict[str, Repository] = {}
        self._indexing_tasks: Dict[str, asyncio.Task] = {}
    
    @property
    def driver(self):
        return self._driver

    async def add_repository(self, path: str) -> Repository:
        """Add a new repository for indexing"""
        path = os.path.abspath(path)
        
        if not os.path.isdir(path):
            raise ValueError(f"Path does not exist: {path}")
        
        repo_id = self._generate_repo_id(path)
        
        if repo_id in self._repositories:
            raise ValueError(f"Repository already exists: {path}")
        
        repo = Repository(
            repo_id=repo_id,
            name=os.path.basename(path),
            path=path,
            status=RepoStatus.PENDING
        )
        self._repositories[repo_id] = repo
        
        # Start indexing in background
        asyncio.create_task(self._index_repository(repo_id))
        
        return repo
    
    async def remove_repository(self, repo_id: str) -> bool:
        """Remove a repository and all its data"""
        if repo_id not in self._repositories:
            return False
        
        # Cancel indexing if in progress
        if repo_id in self._indexing_tasks:
            self._indexing_tasks[repo_id].cancel()
            del self._indexing_tasks[repo_id]
        
        # Delete from database
        async with self.driver.session() as session:
            await session.run("""
                MATCH (r:Repository {repo_id: $repo_id})
                DETACH DELETE r
            """, repo_id=repo_id)
        
        del self._repositories[repo_id]
        return True
    
    async def reindex_repository(self, repo_id: str) -> Repository:
        """Re-index an existing repository"""
        if repo_id not in self._repositories:
            raise ValueError(f"Repository not found: {repo_id}")
        
        repo = self._repositories[repo_id]
        repo.status = RepoStatus.PENDING
        
        # Start re-indexing
        asyncio.create_task(self._index_repository(repo_id))
        
        return repo
    
    async def get_repository(self, repo_id: str) -> Optional[Repository]:
        """Get repository by ID"""
        return self._repositories.get(repo_id)
    
    async def list_repositories(self) -> List[Repository]:
        """List all repositories - query fresh counts from database"""
        repos = []
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (r:Repository) 
                RETURN r.repo_id as repo_id, r.name as name, r.path as path,
                       r.node_count as node_count, r.edge_count as edge_count,
                       r.last_indexed as last_indexed
            """)
            async for record in result:
                repo_id = record["repo_id"]
                
                # Get actual node count from database
                count_result = await session.run("""
                    MATCH (n:ASTNode {repo_id: $repo_id})
                    RETURN count(n) as count
                """, repo_id=repo_id)
                count_record = await count_result.single()
                node_count = count_record["count"] if count_record else 0
                
                # Get edge count
                edge_result = await session.run("""
                    MATCH (a:ASTNode {repo_id: $repo_id})-[r]->(b:ASTNode {repo_id: $repo_id})
                    RETURN count(r) as count
                """, repo_id=repo_id)
                edge_record = await edge_result.single()
                edge_count = edge_record["count"] if edge_record else 0
                
                repo = Repository(
                    repo_id=repo_id,
                    name=record["name"],
                    path=record["path"],
                    status=RepoStatus.INDEXED,
                    node_count=node_count,
                    edge_count=edge_count,
                    last_indexed=record.get("last_indexed")
                )
                repos.append(repo)
                self._repositories[repo_id] = repo
            return repos
    
    async def update_status(self, repo_id: str, status: RepoStatus, error: Optional[str] = None):
        """Update repository status"""
        if repo_id in self._repositories:
            self._repositories[repo_id].status = status
            self._repositories[repo_id].error_message = error
    
    async def get_graph_nodes(self, repo_id: str, kind: str = None, 
                              filepath: str = None, name: str = None, 
                              limit: int = 100) -> List[Dict[str, Any]]:
        """Get graph nodes with filters"""
        async with self.driver.session() as session:
            query = "MATCH (n:ASTNode {repo_id: $repo_id})"
            params = {"repo_id": repo_id, "limit": limit}
            
            if kind:
                query += " WHERE n.kind = $kind"
                params["kind"] = kind
            
            if filepath:
                query += " WHERE n.filepath CONTAINS $filepath"
                params["filepath"] = filepath
            
            if name:
                query += " WHERE n.name CONTAINS $name"
                params["name"] = name
            
            query += " RETURN n LIMIT $limit"
            
            result = await session.run(query, params)
            nodes = []
            async for record in result:
                node = record["n"]
                nodes.append({
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "kind": node.get("kind"),
                    "filepath": node.get("filepath"),
                    "start_line": node.get("start_line"),
                    "end_line": node.get("end_line")
                })
            return nodes
    
    async def get_graph_edges(self, repo_id: str, node_id: str = None, 
                              limit: int = 100) -> List[Dict[str, Any]]:
        """Get graph edges"""
        async with self.driver.session() as session:
            if node_id:
                query = """
                    MATCH (a:ASTNode {repo_id: $repo_id, id: $node_id})-[r]->(b:ASTNode {repo_id: $repo_id})
                    RETURN a.id as source, b.id as target, type(r) as relation
                    LIMIT $limit
                """
                params = {"repo_id": repo_id, "node_id": node_id, "limit": limit}
            else:
                query = """
                    MATCH (a:ASTNode {repo_id: $repo_id})-[r]->(b:ASTNode {repo_id: $repo_id})
                    RETURN a.id as source, b.id as target, type(r) as relation
                    LIMIT $limit
                """
                params = {"repo_id": repo_id, "limit": limit}
            
            result = await session.run(query, params)
            edges = []
            async for record in result:
                edges.append({
                    "source": record["source"],
                    "target": record["target"],
                    "relation": record["relation"]
                })
            return edges
    
    async def _index_repository(self, repo_id: str):
        """Index a repository (background task)"""
        repo = self._repositories.get(repo_id)
        if not repo:
            return
        
        try:
            repo.status = RepoStatus.INDEXING
            await self.progress_tracker.start_tracking(repo_id, 0)
            
            # Import and run the indexer
            from xce.indexing.indexer import index_repository, ParserRegistry
            from xce.indexing.embedding import EmbeddingService
            from xce.indexing.doc_generator import DocGenerator
            from xce.graph.store import GraphStore
            
            # Get settings
            from xce.config import get_settings
            settings = get_settings()
            
            # Create proper registry
            registry = ParserRegistry()
            
            # Initialize services
            graph_store = GraphStore(
                neo4j_uri=settings.neo4j.uri,
                neo4j_auth=settings.neo4j.auth,
                embedding_dimensions=settings.embedding.dimensions
            )
            
            embedding_service = None
            doc_generator = None
            
            # Only init if API keys available
            if settings.embedding.api_key:
                embedding_service = EmbeddingService(
                    api_key=settings.embedding.api_key,
                    model=settings.embedding.model,
                    dimensions=settings.embedding.dimensions
                )
            
            if settings.doc_gen.api_key:
                doc_generator = DocGenerator(
                    api_key=settings.doc_gen.api_key,
                    batch_size=settings.doc_gen.batch_size
                )
            
            # Count files first
            file_count = sum(1 for _ in Path(repo.path).rglob("*") if _.is_file() and not _.name.startswith("."))
            await self.progress_tracker.start_tracking(repo_id, file_count)
            
            # Run indexing
            result, hashes = await index_repository(
                repo_path=repo.path,
                repo_id=repo_id,
                registry=registry,
                doc_generator=doc_generator,
                embedding_service=embedding_service,
                graph_store=graph_store,
                incremental=False
            )
            
            # Update repository stats - IndexResult is a dataclass
            repo.node_count = result.nodes_count
            repo.edge_count = result.edges_count
            repo.last_indexed = datetime.now()
            repo.status = RepoStatus.INDEXED
            
            await self.progress_tracker.finish(repo_id, True)
            
            # Save to database - use repo name as repo_id to match indexer
            actual_repo_id = os.path.basename(repo.path)
            async with self.driver.session() as session:
                await session.run("""
                    MERGE (r:Repository {repo_id: $repo_id})
                    SET r.name = $name, r.path = $path, r.node_count = $node_count,
                        r.edge_count = $edge_count, r.last_indexed = $last_indexed
                """, repo_id=actual_repo_id, name=repo.name, path=repo.path,
                    node_count=repo.node_count, edge_count=repo.edge_count,
                    last_indexed=repo.last_indexed.isoformat())
            
        except Exception as e:
            logger.error(f"Error indexing repository {repo_id}: {e}")
            repo.status = RepoStatus.ERROR
            repo.error_message = str(e)
            await self.progress_tracker.finish(repo_id, False, str(e))
    
    def _generate_repo_id(self, path: str) -> str:
        """Generate repository ID - use folder name (matches indexer behavior)"""
        return os.path.basename(path)