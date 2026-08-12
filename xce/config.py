"""Environment-based configuration for XCE."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return int(raw)


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str = field(default_factory=lambda: _env("NEO4J_URI", "bolt://localhost:7687"))
    user: str = field(default_factory=lambda: _env("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD", ""))

    @property
    def auth(self) -> tuple[str, str]:
        return (self.user, self.password)


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    )
    dimensions: int = field(default_factory=lambda: _env_int("EMBEDDING_DIMENSIONS", 512))
    batch_size: int = field(default_factory=lambda: _env_int("EMBEDDING_BATCH_SIZE", 100))


@dataclass(frozen=True)
class SummarizerConfig:
    api_key: str = field(default_factory=lambda: _env("KIMI_API_KEY"))
    model: str = field(
        default_factory=lambda: _env("SUMMARIZER_MODEL", "moonshot/kimi-k2.5")
    )


@dataclass(frozen=True)
class DocGenConfig:
    api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    batch_size: int = field(default_factory=lambda: _env_int("DOC_GEN_BATCH_SIZE", 10))


@dataclass(frozen=True)
class XMEConfig:
    """Configuration for the Xanther Memory Engine (XME).

    XME is fully local-first and open source.
    All memory is stored in <repo>/.xanther/memory/ by default.

    XCE → XME bridge settings control whether indexed code facts are
    automatically synced into XME after each index run.
    """
    # Storage
    memory_dir: str = field(
        default_factory=lambda: _env("XME_MEMORY_DIR", "")
    )  # empty = auto-detect from repo root

    # Hot cache
    cache_max_size: int = field(
        default_factory=lambda: _env_int("XME_CACHE_MAX_SIZE", 256)
    )
    cache_ttl_seconds: float = field(
        default_factory=lambda: float(_env("XME_CACHE_TTL_SECONDS", "3600"))
    )

    # Team sync
    sync_enabled: bool = field(
        default_factory=lambda: _env("XME_SYNC_ENABLED", "true").lower() == "true"
    )
    sync_remote: str = field(
        default_factory=lambda: _env("XME_SYNC_REMOTE", "origin")
    )
    sync_branch: str = field(
        default_factory=lambda: _env("XME_SYNC_BRANCH", "main")
    )

    # Behaviour
    auto_capture_sessions: bool = field(
        default_factory=lambda: _env("XME_AUTO_CAPTURE", "false").lower() == "true"
    )

    # XCE → XME bridge: sync indexed code facts into XME memory layers
    bridge_enabled: bool = field(
        default_factory=lambda: _env("XME_BRIDGE_ENABLED", "false").lower() == "true"
    )
    # Path to XME SQLite db for episodic store (code file episodes)
    bridge_db_path: str = field(
        default_factory=lambda: _env("XME_BRIDGE_DB_PATH", ".xanther/xme.db")
    )
    # OpenSearch URL for episodic store (optional — falls back to SQLite)
    bridge_opensearch_url: str = field(
        default_factory=lambda: _env("XME_BRIDGE_OPENSEARCH_URL", "")
    )


@dataclass(frozen=True)
class XCEConfig:
    """XCE-specific settings that control which indexing layers run."""

    # Layer 3: ComponentDoc (detailed per-function docs) — expensive, optional
    # Disabled by default — modern LLMs can generate these on demand from source
    deep_docs_enabled: bool = field(
        default_factory=lambda: _env("XCE_DEEP_DOCS", "false").lower() == "true"
    )
    # Layer 4: ArchitectureDoc (module-level HLD) — expensive, optional
    # Re-enable when you want pre-generated architecture context for large codebases
    arch_docs_enabled: bool = field(
        default_factory=lambda: _env("XCE_ARCH_DOCS", "false").lower() == "true"
    )


@dataclass(frozen=True)
class Settings:
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)
    doc_gen: DocGenConfig = field(default_factory=DocGenConfig)
    xme: XMEConfig = field(default_factory=XMEConfig)
    xce: XCEConfig = field(default_factory=XCEConfig)
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    kimi_api_key: str = field(default_factory=lambda: _env("KIMI_API_KEY"))
    runpod_api_key: str = field(default_factory=lambda: _env("RUN_POD_API_KEY"))


def get_settings() -> Settings:
    """Create a Settings instance from current environment variables."""
    return Settings()
