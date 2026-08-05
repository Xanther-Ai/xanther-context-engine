"""
Search Service for XCE Dashboard
Handles semantic search using embeddings
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
from neo4j import AsyncGraphDatabase
import json
import os


@dataclass
class SearchResult:
    """Search result"""
    node_id: str
    name: str
    filepath: str
    start_line: int
    end_line: int
    kind: str
    score: float
    snippet: str


@dataclass
class SearchQuery:
    """Search query history"""
    query: str
    timestamp: datetime
    result_count: int


class SearchService:
    """Handles search functionality"""
    
    def __init__(self, embedding_service, driver: AsyncGraphDatabase.driver):
        self.embedding_service = embedding_service
        self.driver = driver
        self._history: List[SearchQuery] = []
        self._history_file = ".xce_search_history.json"
        self._load_history()
    
    async def search(
        self,
        query: str,
        repo_id: Optional[str] = None,
        node_kinds: Optional[List[str]] = None,
        extensions: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[SearchResult]:
        """Search using semantic embeddings"""
        try:
            # Get embedding for query
            embedding = await self.embedding_service.get_embedding(query)
            
            if embedding is None:
                # Fallback to keyword search
                return await self._keyword_search(query, repo_id, node_kinds, extensions, limit)
            
            # Search in Neo4j using vector similarity
            async with self.driver.session() as session:
                cypher = """
                    MATCH (n:ASTNode)
                    WHERE n.embedding IS NOT NULL
                """
                params = {"embedding": embedding, "limit": limit}
                
                if repo_id:
                    cypher += " AND n.repo_id = $repo_id"
                    params["repo_id"] = repo_id
                
                if node_kinds:
                    cypher += " AND n.kind IN $node_kinds"
                    params["node_kinds"] = node_kinds
                
                cypher += """
                    WITH n, apoc.algo.cosineSimilarity(n.embedding, $embedding) as score
                    WHERE score > 0.5
                    RETURN n.id as node_id, n.name as name, n.filepath as filepath,
                           n.start_line as start_line, n.end_line as end_line,
                           n.kind as kind, score,
                           coalesce(n.docstring, n.source_text[:200]) as snippet
                    ORDER BY score DESC
                    LIMIT $limit
                """
                
                result = await session.run(cypher, params)
                results = []
                async for record in result:
                    results.append(SearchResult(
                        node_id=record["node_id"],
                        name=record["name"],
                        filepath=record["filepath"],
                        start_line=record["start_line"] or 0,
                        end_line=record["end_line"] or 0,
                        kind=record["kind"],
                        score=record["score"],
                        snippet=record["snippet"] or ""
                    ))
                
                # Add to history
                self._add_to_history(query, len(results))
                
                return results
        
        except Exception as e:
            print(f"Search error: {e}")
            # Fallback to keyword search
            return await self._keyword_search(query, repo_id, node_kinds, extensions, limit)
    
    async def _keyword_search(
        self,
        query: str,
        repo_id: Optional[str] = None,
        node_kinds: Optional[List[str]] = None,
        extensions: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[SearchResult]:
        """Fallback keyword search"""
        async with self.driver.session() as session:
            search_terms = query.lower().split()
            pattern = ".*".join(search_terms)
            
            cypher = """
                MATCH (n:ASTNode)
                WHERE (n.name CONTAINS $term OR n.docstring CONTAINS $term OR n.source_text CONTAINS $term)
            """
            params = {"term": query.lower(), "limit": limit}
            
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
                       coalesce(n.docstring, n.source_text[:200]) as snippet
                LIMIT $limit
            """
            
            result = await session.run(cypher, params)
            results = []
            async for record in result:
                results.append(SearchResult(
                    node_id=record["node_id"],
                    name=record["name"],
                    filepath=record["filepath"],
                    start_line=record["start_line"] or 0,
                    end_line=record["end_line"] or 0,
                    kind=record["kind"],
                    score=record["score"],
                    snippet=record["snippet"] or ""
                ))
            
            self._add_to_history(query, len(results))
            return results
    
    async def get_history(self, limit: int = 10) -> List[SearchQuery]:
        """Get search history"""
        return self._history[:limit]
    
    def _add_to_history(self, query: str, result_count: int):
        """Add query to history"""
        self._history.insert(0, SearchQuery(
            query=query,
            timestamp=datetime.now(),
            result_count=result_count
        ))
        # Keep only last 50
        self._history = self._history[:50]
        self._save_history()
    
    def _load_history(self):
        """Load history from file"""
        if os.path.exists(self._history_file):
            try:
                with open(self._history_file, "r") as f:
                    data = json.load(f)
                    self._history = [
                        SearchQuery(
                            query=q["query"],
                            timestamp=datetime.fromisoformat(q["timestamp"]),
                            result_count=q["result_count"]
                        )
                        for q in data
                    ]
            except:
                pass
    
    def _save_history(self):
        """Save history to file"""
        try:
            with open(self._history_file, "w") as f:
                json.dump([
                    {
                        "query": q.query,
                        "timestamp": q.timestamp.isoformat(),
                        "result_count": q.result_count
                    }
                    for q in self._history
                ], f)
        except:
            pass