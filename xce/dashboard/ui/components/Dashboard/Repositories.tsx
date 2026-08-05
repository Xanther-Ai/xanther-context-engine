import React, { useState } from 'react';
import { useRepositories } from '../../hooks/useRepositories';

export default function Repositories() {
  const { repositories, loading, addRepository, removeRepository, reindexRepository } = useRepositories();
  const [showAddModal, setShowAddModal] = useState(false);
  const [newRepoPath, setNewRepoPath] = useState('');
  const [adding, setAdding] = useState(false);

  const handleAddRepo = async () => {
    if (!newRepoPath.trim()) return;
    setAdding(true);
    try {
      await addRepository(newRepoPath);
      setShowAddModal(false);
      setNewRepoPath('');
    } catch (err: any) {
      alert(err.message);
    }
    setAdding(false);
  };

  const handleRemove = async (repoId: string) => {
    if (confirm('Are you sure you want to remove this repository?')) {
      await removeRepository(repoId);
    }
  };

  const handleReindex = async (repoId: string) => {
    await reindexRepository(repoId);
  };

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h2>Repositories</h2>
        <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
          + Add Repository
        </button>
      </div>

      {repositories.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📁</div>
          <div className="empty-state-title">No repositories yet</div>
          <p>Add your first repository to start exploring your code</p>
          <button className="btn btn-primary" style={{ marginTop: '16px' }} onClick={() => setShowAddModal(true)}>
            + Add Repository
          </button>
        </div>
      ) : (
        <div className="repo-grid">
          {repositories.map((repo: any) => (
            <div key={repo.repo_id} className="repo-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                <div>
                  <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>{repo.name}</h3>
                  <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginTop: '4px', wordBreak: 'break-all' }}>
                    {repo.path}
                  </div>
                </div>
                <span className={`repo-status ${repo.status}`}>
                  {repo.status === 'indexed' ? '✓ Indexed' : repo.status}
                </span>
              </div>
              
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Nodes</div>
                  <div style={{ fontWeight: 600 }}>{repo.node_count?.toLocaleString() || 0}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Edges</div>
                  <div style={{ fontWeight: 600 }}>{repo.edge_count?.toLocaleString() || 0}</div>
                </div>
              </div>

              {repo.last_indexed && (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
                  Last indexed: {new Date(repo.last_indexed).toLocaleDateString()}
                </div>
              )}

              {repo.error_message && (
                <div style={{ fontSize: '0.875rem', color: 'var(--error)', marginBottom: '12px', padding: '8px', background: 'rgba(239,68,68,0.1)', borderRadius: '6px' }}>
                  Error: {repo.error_message}
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => handleReindex(repo.repo_id)} disabled={repo.status === 'indexing'}>
                  🔄 Re-index
                </button>
                <button className="btn btn-danger" onClick={() => handleRemove(repo.repo_id)} disabled={repo.status === 'indexing'}>
                  🗑️ Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Add Repository</h3>
              <button onClick={() => setShowAddModal(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.25rem' }}>×</button>
            </div>
            
            <div className="input-group">
              <label className="input-label">Repository Path</label>
              <input
                type="text"
                className="input"
                placeholder="/path/to/your/repo"
                value={newRepoPath}
                onChange={e => setNewRepoPath(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddRepo()}
              />
            </div>
            
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={() => setShowAddModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleAddRepo} disabled={adding || !newRepoPath.trim()}>
                {adding ? 'Adding...' : 'Add Repository'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}