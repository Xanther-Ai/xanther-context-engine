"""
Statistics Service for XCE Dashboard
Aggregates and calculates repository statistics
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from neo4j import AsyncGraphDatabase


@dataclass
class RepositoryStats:
    """Repository statistics"""
    repo_id: str
    total_nodes: int
    nodes_by_kind: Dict[str, int]
    total_edges: int
    edges_by_type: Dict[str, int]
    files_by_extension: Dict[str, int]
    total_lines: int
    last_indexed: Optional[datetime]


class StatsService:
    """Calculates repository statistics"""
    
    def __init__(self, driver: AsyncGraphDatabase.driver):
        self.driver = driver
    
    async def get_stats(self, repo_id: str) -> Optional[RepositoryStats]:
        """Get statistics for a repository"""
        async with self.driver.session() as session:
            # Get node counts by kind
            result = await session.run("""
                MATCH (n:ASTNode {repo_id: $repo_id})
                RETURN n.kind as kind, count(*) as count
            """, repo_id=repo_id)
            
            nodes_by_kind = {}
            total_nodes = 0
            async for record in result:
                nodes_by_kind[record["kind"]] = record["count"]
                total_nodes += record["count"]
            
            # Get edge counts by type
            result = await session.run("""
                MATCH (a:ASTNode {repo_id: $repo_id})-[r]->(b:ASTNode {repo_id: $repo_id})
                RETURN type(r) as rel_type, count(*) as count
            """, repo_id=repo_id)
            
            edges_by_type = {}
            total_edges = 0
            async for record in result:
                edges_by_type[record["rel_type"]] = record["count"]
                total_edges += record["count"]
            
            # Get file counts by extension
            result = await session.run("""
                MATCH (n:ASTNode {repo_id: $repo_id})
                WHERE n.filepath IS NOT NULL
                WITH split(n.filepath, '/')[-1] as filename
                WITH CASE 
                    WHEN filename CONTAINS '.' THEN '.' + split(filename, '\\.')[-1]
                    ELSE '' 
                END as ext
                RETURN ext as extension, count(*) as count
                ORDER BY count DESC
                LIMIT 20
            """, repo_id=repo_id)
            
            files_by_extension = {}
            async for record in result:
                ext = record["extension"] or "(no extension)"
                files_by_extension[ext] = record["count"]
            
            # Get total lines
            result = await session.run("""
                MATCH (n:ASTNode {repo_id: $repo_id})
                WHERE n.start_line IS NOT NULL AND n.end_line IS NOT NULL
                RETURN sum(n.end_line - n.start_line + 1) as total_lines
            """, repo_id=repo_id)
            
            record = await result.single()
            total_lines = record["total_lines"] if record else 0
            
            # Get last indexed
            result = await session.run("""
                MATCH (r:Repository {repo_id: $repo_id})
                RETURN r.last_indexed as last_indexed
            """, repo_id=repo_id)
            
            record = await result.single()
            last_indexed = None
            if record and record["last_indexed"]:
                try:
                    last_indexed = datetime.fromisoformat(record["last_indexed"])
                except:
                    pass
            
            return RepositoryStats(
                repo_id=repo_id,
                total_nodes=total_nodes,
                nodes_by_kind=nodes_by_kind,
                total_edges=total_edges,
                edges_by_type=edges_by_type,
                files_by_extension=files_by_extension,
                total_lines=total_lines,
                last_indexed=last_indexed
            )
    
    async def compare_repos(self, repo_ids: List[str]) -> List[RepositoryStats]:
        """Compare statistics across multiple repositories"""
        stats = []
        for repo_id in repo_ids:
            repo_stats = await self.get_stats(repo_id)
            if repo_stats:
                stats.append(repo_stats)
        return stats