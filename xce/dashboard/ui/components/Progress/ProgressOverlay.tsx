import React from 'react';

interface ProgressOverlayProps {
  progress: any[];
}

export default function ProgressOverlay({ progress }: ProgressOverlayProps) {
  if (!progress || progress.length === 0) return null;

  return (
    <div className="progress-overlay">
      {progress.map((p: any, i: number) => (
        <div key={i}>
          <div className="progress-header">
            <span className="progress-title">{p.repo_id || 'Indexing...'}</span>
            <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
              {p.percent?.toFixed(0) || 0}%
            </span>
          </div>
          <div className="progress-bar-container">
            <div className="progress-bar" style={{ width: `${p.percent || 0}%` }}></div>
          </div>
          <div className="progress-stats">
            <span>{p.processed_files || 0} / {p.total_files || 0} files</span>
            <span>{p.nodes_created || 0} nodes</span>
          </div>
          {p.current_file && (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {p.current_file}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}