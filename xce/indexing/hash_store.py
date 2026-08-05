"""
PostgreSQL-based hash store for incremental indexing.

Stores file hashes in PostgreSQL to enable incremental indexing - only re-indexing
files that have changed since the last indexing run.
"""

from __future__ import annotations

import os
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

import asyncpg
from asyncpg import Pool

logger = logging.getLogger(__name__)


@dataclass
class FileHash:
    """Represents a file hash entry"""
    repo_id: str
    file_path: str
    file_hash: str
    file_size: Optional[int] = None
    last_modified: Optional[datetime] = None
    indexed_at: Optional[datetime] = None


@dataclass
class RepoMetadata:
    """Repository metadata from PostgreSQL"""
    repo_id: str
    repo_path: str
    language: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    indexing_status: str = "never_indexed"
    total_files: int = 0
    indexed_files: int = 0
    total_nodes: int = 0
    total_edges: int = 0


class HashStore:
    """PostgreSQL-backed store for file hashes and repository metadata"""
    
    def __init__(
        self,
        postgres_uri: str,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
    ) -> None:
        self._pool: Optional[Pool] = None
        self._postgres_uri = postgres_uri
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
    
    async def connect(self) -> None:
        """Create connection pool to PostgreSQL"""
        if self._pool is not None:
            return
        
        logger.info(f"Connecting to PostgreSQL: {self._postgres_uri.split('@')[0] if '@' in self._postgres_uri else 'localhost'}")
        self._pool = await asyncpg.create_pool(
            self._postgres_uri,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
        )
        logger.info("Connected to PostgreSQL")
    
    async def close(self) -> None:
        """Close the connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Closed PostgreSQL connection")
    
    async def ensure_schema(self) -> None:
        """Ensure the database schema exists.
        
        Note: Schema is typically created by init-postgres.sql,
        but this provides a fallback.
        """
        # The schema is created by init-postgres.sql, so we just verify
        # the tables exist. If not, log a warning.
        async with self._pool.acquire() as conn:
            # Check if tables exist
            result = await conn.fetch("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name IN ('file_hashes', 'repositories')
            """)
            if len(result) < 2:
                logger.warning("PostgreSQL schema not initialized. Run init-postgres.sql")
    
    # -------------------------------------------------------------------------
    # File Hash Operations
    # -------------------------------------------------------------------------
    
    async def get_file_hash(self, repo_id: str, file_path: str) -> Optional[str]:
        """Get the stored hash for a specific file in a repo.
        
        Returns:
            The SHA-256 hash string, or None if not found
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT file_hash FROM file_hashes 
                WHERE repo_id = $1 AND file_path = $2
                """,
                repo_id, file_path
            )
            return row["file_hash"] if row else None
    
    async def get_all_file_hashes(self, repo_id: str) -> dict[str, str]:
        """Get all file hashes for a repository.
        
        Returns:
            Dictionary mapping file_path -> file_hash
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT file_path, file_hash FROM file_hashes WHERE repo_id = $1",
                repo_id
            )
            return {row["file_path"]: row["file_hash"] for row in rows}
    
    async def upsert_file_hash(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        file_size: Optional[int] = None,
    ) -> None:
        """Insert or update a file hash.
        
        Uses ON CONFLICT to handle the unique constraint.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO file_hashes (repo_id, file_path, file_hash, file_size, indexed_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (repo_id, file_path) 
                DO UPDATE SET file_hash = $3, file_size = $4, indexed_at = CURRENT_TIMESTAMP
                """,
                repo_id, file_path, file_hash, file_size
            )
    
    async def upsert_file_hashes(
        self,
        repo_id: str,
        hashes: dict[str, str],
    ) -> int:
        """Batch upsert file hashes.
        
        Args:
            repo_id: Repository identifier
            hashes: Dictionary mapping file_path -> file_hash
        
        Returns:
            Number of records inserted/updated
        """
        if not hashes:
            return 0
        
        async with self._pool.acquire() as conn:
            # Use a transaction for batch upsert
            async with conn.transaction():
                # Build values list for batch insert
                values = [
                    (repo_id, file_path, file_hash, os.path.getsize(file_path) if os.path.exists(file_path) else None)
                    for file_path, file_hash in hashes.items()
                ]
                
                await conn.executemany(
                    """
                    INSERT INTO file_hashes (repo_id, file_path, file_hash, file_size, indexed_at)
                    VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                    ON CONFLICT (repo_id, file_path) 
                    DO UPDATE SET file_hash = $3, file_size = $4, indexed_at = CURRENT_TIMESTAMP
                    """,
                    values
                )
        
        logger.info(f"Upserted {len(hashes)} file hashes for repo {repo_id}")
        return len(hashes)
    
    async def delete_file_hashes(self, repo_id: str) -> int:
        """Delete all file hashes for a repository.
        
        Useful when doing a full reindex.
        
        Returns:
            Number of records deleted
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM file_hashes WHERE repo_id = $1",
                repo_id
            )
            # Result is "DELETE n" where n is count
            if result.startswith("DELETE "):
                return int(result.split()[1])
            return 0
    
    # -------------------------------------------------------------------------
    # Repository Metadata Operations
    # -------------------------------------------------------------------------
    
    async def get_repository(self, repo_id: str) -> Optional[RepoMetadata]:
        """Get repository metadata"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM repositories WHERE repo_id = $1",
                repo_id
            )
            if row:
                return RepoMetadata(
                    repo_id=row["repo_id"],
                    repo_path=row["repo_path"],
                    language=row.get("language"),
                    last_indexed_at=row.get("last_indexed_at"),
                    indexing_status=row.get("indexing_status", "never_indexed"),
                    total_files=row.get("total_files", 0),
                    indexed_files=row.get("indexed_files", 0),
                    total_nodes=row.get("total_nodes", 0),
                    total_edges=row.get("total_edges", 0),
                )
            return None
    
    async def upsert_repository(
        self,
        repo_id: str,
        repo_path: str,
        language: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Insert or update repository metadata"""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO repositories (repo_id, repo_path, language, last_indexed_at, indexing_status, 
                                          total_files, indexed_files, total_nodes, total_edges, updated_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4, $5, $6, $7, $8, CURRENT_TIMESTAMP)
                ON CONFLICT (repo_id) 
                DO UPDATE SET 
                    repo_path = $2, 
                    language = COALESCE($3, repositories.language),
                    last_indexed_at = CURRENT_TIMESTAMP,
                    indexing_status = $4,
                    total_files = COALESCE($5, repositories.total_files),
                    indexed_files = COALESCE($6, repositories.indexed_files),
                    total_nodes = COALESCE($7, repositories.total_nodes),
                    total_edges = COALESCE($8, repositories.total_edges),
                    updated_at = CURRENT_TIMESTAMP
                """,
                repo_id,
                repo_path,
                language,
                kwargs.get("indexing_status", "indexed"),
                kwargs.get("total_files", 0),
                kwargs.get("indexed_files", 0),
                kwargs.get("total_nodes", 0),
                kwargs.get("total_edges", 0),
            )
    
    async def update_indexing_status(
        self,
        repo_id: str,
        status: str,
        nodes_count: int = 0,
        edges_count: int = 0,
        docs_count: int = 0,
        embeddings_count: int = 0,
    ) -> None:
        """Update the indexing status for a repository"""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE repositories 
                SET indexing_status = $2,
                    last_indexed_at = CURRENT_TIMESTAMP,
                    total_nodes = $3,
                    total_edges = $4,
                    updated_at = CURRENT_TIMESTAMP
                WHERE repo_id = $1
                """,
                repo_id, status, nodes_count, edges_count
            )
    
    async def list_repositories(self) -> list[RepoMetadata]:
        """List all repositories"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM repositories ORDER BY last_indexed_at DESC")
            return [
                RepoMetadata(
                    repo_id=row["repo_id"],
                    repo_path=row["repo_path"],
                    language=row.get("language"),
                    last_indexed_at=row.get("last_indexed_at"),
                    indexing_status=row.get("indexing_status", "never_indexed"),
                    total_files=row.get("total_files", 0),
                    indexed_files=row.get("indexed_files", 0),
                    total_nodes=row.get("total_nodes", 0),
                    total_edges=row.get("total_edges", 0),
                )
                for row in rows
            ]
    
    async def delete_repository(self, repo_id: str) -> bool:
        """Delete a repository and all its file hashes"""
        async with self._pool.acquire() as conn:
            # Delete file hashes first (foreign key)
            await conn.execute("DELETE FROM file_hashes WHERE repo_id = $1", repo_id)
            # Delete repository
            result = await conn.execute("DELETE FROM repositories WHERE repo_id = $1", repo_id)
            return result != "DELETE 0"


# ============================================================================
# Factory function
# ============================================================================

def create_hash_store(postgres_uri: str) -> HashStore:
    """Create a HashStore instance from a PostgreSQL URI"""
    return HashStore(postgres_uri)


async def create_hash_store_and_connect(postgres_uri: str) -> HashStore:
    """Create a HashStore and connect to PostgreSQL"""
    store = HashStore(postgres_uri)
    await store.connect()
    return store