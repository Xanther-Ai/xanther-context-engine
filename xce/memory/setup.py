"""XCE+XME Setup Helper — Production-ready initialization for new repositories.

Provides a single entry point to set up the full XCE+XME stack for any repo:
    - Neo4j graph store (code graph + episode embeddings)
    - Embedding service (OpenRouter)
    - CodeMemory (unified query + write interface)
    - Hook installation (auto-record turns)

Usage:
    from xce.memory.setup import XCESetup

    # One-liner setup
    xce = await XCESetup.create(repo_path="/path/to/repo", repo_id="my-repo")

    # Query
    ctx = await xce.memory.query("how does auth work?", repo_id="my-repo")

    # Record
    await xce.memory.record_action(repo_id="my-repo", action="fixed auth bug", files=["auth.py"])

    # Cleanup
    await xce.close()
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class XCEConfig:
    """Configuration for XCE+XME stack."""

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "xce_dev_password"

    # Embeddings
    openrouter_api_key: str = ""
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 512

    # XME
    xme_db_path: str = ".xanther/xme.db"

    # Indexing
    layer3_workers: int = 10

    @classmethod
    def from_env(cls) -> "XCEConfig":
        """Load config from environment variables."""
        return cls(
            neo4j_uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
            neo4j_password=os.environ.get("NEO4J_PASSWORD", "xce_dev_password"),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            embedding_model=os.environ.get("XCE_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
            embedding_dimensions=int(os.environ.get("XCE_EMBEDDING_DIMENSIONS", "512")),
            xme_db_path=os.environ.get("XME_DB_PATH", ".xanther/xme.db"),
            layer3_workers=int(os.environ.get("XCE_LAYER3_WORKERS", "10")),
        )


@dataclass
class XCESetup:
    """Production-ready XCE+XME stack for a repository.

    Encapsulates all infrastructure (Neo4j, embeddings, memory) behind
    a single async context manager or factory method.
    """

    config: XCEConfig
    repo_path: str
    repo_id: str

    # Initialized components
    graph_store: Any = field(default=None, repr=False)
    embedding_service: Any = field(default=None, repr=False)
    memory: Any = field(default=None, repr=False)

    _driver: Any = field(default=None, repr=False)

    @classmethod
    async def create(
        cls,
        repo_path: str,
        repo_id: Optional[str] = None,
        config: Optional[XCEConfig] = None,
    ) -> "XCESetup":
        """Factory method — creates and initializes the full XCE+XME stack.

        Args:
            repo_path: Path to the repository root
            repo_id: Repository identifier (defaults to directory name)
            config: Configuration (defaults to env vars)

        Returns:
            Fully initialized XCESetup ready for queries and writes.
        """
        if config is None:
            from dotenv import load_dotenv
            # Try to load .env from the repo or from XCE project
            env_path = Path(repo_path) / ".env"
            if not env_path.exists():
                env_path = Path(__file__).parent.parent.parent / ".env"
            if env_path.exists():
                load_dotenv(str(env_path))
            config = XCEConfig.from_env()

        if repo_id is None:
            repo_id = Path(repo_path).name

        setup = cls(config=config, repo_path=str(repo_path), repo_id=repo_id)
        await setup._initialize()
        return setup

    async def _initialize(self) -> None:
        """Initialize all components."""
        from xce.graph.store import GraphStore
        from xce.indexing.embedding import EmbeddingService
        from xce.memory.code_memory import CodeMemory

        # 1. Graph Store (Neo4j)
        self.graph_store = GraphStore(
            neo4j_uri=self.config.neo4j_uri,
            neo4j_auth=(self.config.neo4j_user, self.config.neo4j_password),
            embedding_dimensions=self.config.embedding_dimensions,
        )
        await self.graph_store.init_schema()
        self._driver = self.graph_store._driver
        logger.info("GraphStore initialized: %s", self.config.neo4j_uri)

        # 2. Embedding Service (OpenRouter)
        if self.config.openrouter_api_key:
            self.embedding_service = EmbeddingService(
                api_key=self.config.openrouter_api_key,
                model=self.config.embedding_model,
                dimensions=self.config.embedding_dimensions,
            )
            logger.info("EmbeddingService initialized: %s (%dd)",
                        self.config.embedding_model, self.config.embedding_dimensions)
        else:
            logger.warning("No OPENROUTER_API_KEY — embedding disabled (FTS5 fallback)")

        # 3. CodeMemory (unified XCE + XME interface)
        xme_db = Path(self.repo_path) / self.config.xme_db_path
        xme_db.parent.mkdir(parents=True, exist_ok=True)

        self.memory = CodeMemory(
            neo4j_driver=self._driver,
            xme_db_path=str(xme_db),
            embedding_service=self.embedding_service,
        )
        await self.memory.init()
        logger.info("CodeMemory initialized (repo_id=%s)", self.repo_id)

    async def index(self, full: bool = False, smart_docs: bool = True) -> dict[str, int]:
        """Run full indexing pipeline on the repository.

        Args:
            full: Force full re-index (skip incremental)
            smart_docs: Only generate docs for non-trivial nodes

        Returns:
            Dict with nodes_count, edges_count, docs_count, embeddings_count
        """
        from xce.indexing.indexer import index_repository
        from xce.indexing.doc_generator import DocGenerator

        doc_generator = DocGenerator(
            api_key=self.config.openrouter_api_key,
        )

        result, _ = await index_repository(
            self.repo_path,
            self.repo_id,
            doc_generator=doc_generator,
            embedding_service=self.embedding_service,
            graph_store=self.graph_store,
            hash_store=None,
            incremental=not full,
            smart_docs=smart_docs,
        )

        return {
            "nodes_count": result.nodes_count,
            "edges_count": result.edges_count,
            "docs_count": result.docs_count,
            "embeddings_count": result.embeddings_count,
        }

    async def query(self, question: str, top_k: int = 15) -> dict[str, Any]:
        """Query the codebase with semantic search + episodic memory.

        Shortcut for self.memory.query(question, repo_id=self.repo_id, top_k=top_k)
        """
        return await self.memory.query(question, repo_id=self.repo_id, top_k=top_k)

    async def record(self, action: str, files: Optional[list[str]] = None, outcome: str = "success") -> Optional[str]:
        """Record an agent action with vector embedding.

        Shortcut for self.memory.record_action(...)
        """
        return await self.memory.record_action(
            repo_id=self.repo_id,
            action=action,
            files=files,
            outcome=outcome,
        )

    async def decide(self, decision: str, rationale: str = "", files: Optional[list[str]] = None) -> None:
        """Record an architectural decision.

        Shortcut for self.memory.record_decision(...)
        """
        await self.memory.record_decision(
            repo_id=self.repo_id,
            decision=decision,
            rationale=rationale,
            affected_files=files,
        )

    async def recall(self, problem: str, limit: int = 5) -> list[dict[str, Any]]:
        """Recall past agent actions similar to the current problem.

        Shortcut for self.memory.recall_similar(...)
        """
        return await self.memory.recall_similar(problem, repo_id=self.repo_id, limit=limit)

    async def search_episodes(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Vector search over past episodes (actions + decisions).

        Returns episodes ranked by semantic similarity.
        """
        if self.embedding_service:
            return await self.memory._vector_episode_search(query, self.repo_id, top_k)
        return await self.memory._query_episodes(query, self.repo_id, top_k, "xce_agent", False)

    def install_hooks(self, dry_run: bool = False) -> dict[str, list[str]]:
        """Install Kiro + Claude Code hooks for auto-recording turns.

        Args:
            dry_run: If True, show what would be written without writing.

        Returns:
            Dict with 'kiro' and 'claude' lists of created file paths.
        """
        from xce.memory.hook_installer import install_hooks
        return install_hooks(self.repo_path, dry_run=dry_run)

    async def close(self) -> None:
        """Shut down all components cleanly."""
        if self.memory:
            await self.memory.close()
        if self.embedding_service:
            await self.embedding_service.close()
        if self.graph_store:
            await self.graph_store.close()
        logger.info("XCESetup closed")

    async def __aenter__(self) -> "XCESetup":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Static utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def check_prerequisites() -> dict[str, bool]:
        """Check if all required services are running.

        Returns dict with status of each dependency:
            neo4j: bool
            openrouter: bool (API key present)
            docker: bool
        """
        import subprocess

        checks = {}

        # Neo4j
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("localhost", 7687))
            s.close()
            checks["neo4j"] = True
        except Exception:
            checks["neo4j"] = False

        # OpenRouter API key
        checks["openrouter"] = bool(os.environ.get("OPENROUTER_API_KEY"))

        # Docker
        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            )
            checks["docker"] = result.returncode == 0
        except Exception:
            checks["docker"] = False

        return checks

    @staticmethod
    def print_setup_instructions() -> None:
        """Print setup instructions for new users."""
        print("""
╔══════════════════════════════════════════════════════════════╗
║           XCE+XME Setup Instructions                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. Start Neo4j:                                             ║
║     docker run -d --name xce-neo4j \\                         ║
║       -p 7474:7474 -p 7687:7687 \\                            ║
║       -e NEO4J_AUTH=neo4j/xce_dev_password \\                  ║
║       neo4j:5-community                                      ║
║                                                              ║
║  2. Set environment variables (.env):                        ║
║     NEO4J_URI=bolt://localhost:7687                           ║
║     NEO4J_USER=neo4j                                         ║
║     NEO4J_PASSWORD=xce_dev_password                          ║
║     OPENROUTER_API_KEY=sk-or-v1-...                          ║
║                                                              ║
║  3. Index your repo:                                         ║
║     python -m xce index /path/to/repo --mode full            ║
║                                                              ║
║  4. Or use the Python API:                                   ║
║     from xce.memory.setup import XCESetup                    ║
║     xce = await XCESetup.create("/path/to/repo")             ║
║     ctx = await xce.query("how does X work?")                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
