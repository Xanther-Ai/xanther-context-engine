-- PostgreSQL schema for XCE incremental indexing
-- Stores file hashes to enable incremental indexing (only re-index changed files)

-- File hashes table - tracks content hashes for each file per repository
CREATE TABLE IF NOT EXISTS file_hashes (
    id SERIAL PRIMARY KEY,
    repo_id VARCHAR(255) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,  -- SHA-256 hash
    file_size BIGINT,
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Composite unique constraint: one hash per file per repo
    CONSTRAINT unique_repo_file UNIQUE (repo_id, file_path)
);

-- Index for fast lookups by repo_id
CREATE INDEX IF NOT EXISTS idx_file_hashes_repo_id ON file_hashes(repo_id);

-- Index for looking up specific file in a repo
CREATE INDEX IF NOT EXISTS idx_file_hashes_repo_file ON file_hashes(repo_id, file_path);

-- Index for finding stale files (not indexed recently)
CREATE INDEX IF NOT EXISTS idx_file_hashes_last_modified ON file_hashes(last_modified);

-- Repository metadata table - stores indexing configuration and status
CREATE TABLE IF NOT EXISTS repositories (
    id SERIAL PRIMARY KEY,
    repo_id VARCHAR(255) NOT NULL UNIQUE,
    repo_path VARCHAR(1024) NOT NULL,
    language VARCHAR(50),
    last_indexed_at TIMESTAMP,
    indexing_status VARCHAR(50) DEFAULT 'never_indexed',  -- never_indexed, indexing, indexed, failed
    total_files INTEGER DEFAULT 0,
    indexed_files INTEGER DEFAULT 0,
    total_nodes INTEGER DEFAULT 0,
    total_edges INTEGER DEFAULT 0,
    total_docs INTEGER DEFAULT 0,
    total_embeddings INTEGER DEFAULT 0,
    config JSONB,  -- Stores indexing configuration
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repositories_repo_id ON repositories(repo_id);
CREATE INDEX IF NOT EXISTS idx_repositories_status ON repositories(indexing_status);

-- Indexing jobs table - tracks individual indexing runs
CREATE TABLE IF NOT EXISTS indexing_jobs (
    id SERIAL PRIMARY KEY,
    repo_id VARCHAR(255) NOT NULL,
    job_id VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, running, completed, failed
    incremental BOOLEAN DEFAULT true,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    -- Stats from IndexResult
    nodes_count INTEGER DEFAULT 0,
    edges_count INTEGER DEFAULT 0,
    docs_count INTEGER DEFAULT 0,
    embeddings_count INTEGER DEFAULT 0,
    files_changed INTEGER DEFAULT 0,
    files_unchanged INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repositories(repo_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_indexing_jobs_repo_id ON indexing_jobs(repo_id);
CREATE INDEX IF NOT EXISTS idx_indexing_jobs_status ON indexing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_indexing_jobs_job_id ON indexing_jobs(job_id);

-- Comments for documentation
COMMENT ON TABLE file_hashes IS 'Stores SHA-256 hashes of source files for incremental indexing';
COMMENT ON TABLE repositories IS 'Repository metadata and indexing status';
COMMENT ON TABLE indexing_jobs IS 'Tracks indexing job runs for monitoring and debugging';