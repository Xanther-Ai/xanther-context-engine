import React, { useState, useEffect } from 'react';
import { useRepositories } from '../../hooks/useRepositories';

export default function Home() {
  const { repositories, loading, stats, refresh } = useRepositories();

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
      </div>
    );
  }

  const totalNodes = stats?.total_nodes || 0;
  const totalEdges = stats?.total_edges || 0;
  const totalRepos = repositories.length;

  return (
    <div className="fade-in">
      <h2 style={{ marginBottom: '24px' }}>Dashboard</h2>
      
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{totalRepos}</div>
          <div className="stat-label">Repositories</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totalNodes.toLocaleString()}</div>
          <div className="stat-label">Total Nodes</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totalEdges.toLocaleString()}</div>
          <div className="stat-label">Total Edges</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats?.total_lines?.toLocaleString() || 0}</div>
          <div className="stat-label">Lines of Code</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Recent Activity</h3>
          <button className="btn btn-secondary" onClick={refresh}>Refresh</button>
        </div>
        
        {repositories.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📁</div>
            <div className="empty-state-title">No repositories indexed</div>
            <p>Add a repository to get started</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {repositories.slice(0, 5).map((repo: any) => (
              <div key={repo.repo_id} style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'center',
                padding: '12px',
                background: 'var(--bg-tertiary)',
                borderRadius: '8px'
              }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{repo.name}</div>
                  <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>{repo.path}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span className={`repo-status ${repo.status}`}>
                    {repo.status === 'indexed' ? '✓ Indexed' : repo.status}
                  </span>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {repo.node_count?.toLocaleString()} nodes
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Quick Actions</h3>
        </div>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <button className="btn btn-primary">+ Add Repository</button>
          <button className="btn btn-secondary">🔍 Search Codebase</button>
          <button className="btn btn-secondary">🕸️ Explore Graph</button>
        </div>
      </div>
    </div>
  );
}