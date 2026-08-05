import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

interface ImpactData {
  direct_dependents: Array<{
    node_id: string;
    name: string;
    kind: string;
    filepath: string;
  }>;
  test_files: Array<{
    path: string;
    test_count: number;
  }>;
  risk_score: number;
  propagation_depth: number;
}

interface ImpactAnalysisProps {
  symbolId: string;
  onNavigate?: (symbolId: string) => void;
}

export default function ImpactAnalysis({ symbolId, onNavigate }: ImpactAnalysisProps) {
  const [impact, setImpact] = useState<ImpactData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchImpact = useCallback(async () => {
    if (!symbolId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/symbol/${symbolId}/impact`);
      
      if (!res.ok) {
        throw new Error('Failed to fetch impact analysis');
      }

      const data = await res.json();
      setImpact(data);
    } catch (err) {
      console.error('Failed to fetch impact analysis:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [symbolId]);

  useEffect(() => {
    fetchImpact();
  }, [fetchImpact]);

  const handleNodeClick = (nodeId: string) => {
    if (onNavigate) {
      onNavigate(nodeId);
    }
  };

  const getRiskColor = (score: number): string => {
    if (score >= 0.7) return '#ef4444';
    if (score >= 0.4) return '#f59e0b';
    return '#10b981';
  };

  const getRiskLabel = (score: number): string => {
    if (score >= 0.7) return 'High Risk';
    if (score >= 0.4) return 'Medium Risk';
    return 'Low Risk';
  };

  const renderCircularProgress = (value: number) => {
    const radius = 45;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - value * circumference;
    
    return (
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke="var(--bg-tertiary)"
          strokeWidth="10"
        />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke={getRiskColor(value)}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
          style={{ transition: 'stroke-dashoffset 0.5s ease' }}
        />
        <text
          x="60"
          y="60"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="var(--text-primary)"
          fontSize="24"
          fontWeight="700"
        >
          {Math.round(value * 100)}
        </text>
        <text
          x="60"
          y="80"
          textAnchor="middle"
          fill="var(--text-muted)"
          fontSize="10"
        >
          %
        </text>
      </svg>
    );
  };

  if (loading) {
    return (
      <div className="impact-analysis fade-in">
        <div className="loading">
          <div className="spinner"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="impact-analysis fade-in">
        <div className="empty-state">
          <div className="empty-state-icon">⚠️</div>
          <div className="empty-state-title">Error loading analysis</div>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!impact) {
    return (
      <div className="impact-analysis fade-in">
        <div className="empty-state">
          <div className="empty-state-icon">📊</div>
          <div className="empty-state-title">No impact data</div>
          <p>Select a symbol to view impact analysis</p>
        </div>
      </div>
    );
  }

  return (
    <div className="impact-analysis fade-in">
      <h3>Impact Analysis</h3>

      <div className="impact-grid">
        {/* Risk Score */}
        <div className="impact-card risk-card">
          <div className="risk-score-container">
            {renderCircularProgress(impact.risk_score)}
          </div>
          <div className="risk-info">
            <span 
              className="risk-label"
              style={{ color: getRiskColor(impact.risk_score) }}
            >
              {getRiskLabel(impact.risk_score)}
            </span>
            <span className="risk-description">
              {impact.risk_score >= 0.7 
                ? 'Changing this symbol could affect many dependent files'
                : impact.risk_score >= 0.4
                  ? 'Moderate impact if this symbol is modified'
                  : 'Low impact - limited dependencies'
              }
            </span>
          </div>
        </div>

        {/* Propagation Depth */}
        <div className="impact-card depth-card">
          <div className="depth-indicator">
            <div className="depth-value">{impact.propagation_depth}</div>
            <div className="depth-label">Propagation Depth</div>
          </div>
          <div className="depth-visual">
            {[...Array(Math.min(impact.propagation_depth, 5))].map((_, i) => (
              <div 
                key={i} 
                className="depth-bar"
                style={{ 
                  height: `${((5 - i) / 5) * 100}%`,
                  opacity: 1 - (i * 0.15)
                }}
              />
            ))}
          </div>
          <p className="depth-description">
            Changes can propagate up to {impact.propagation_depth} levels deep
          </p>
        </div>
      </div>

      {/* Direct Dependents */}
      <div className="impact-section">
        <div className="section-header">
          <h4>Direct Dependents</h4>
          <span className="badge">{impact.direct_dependents.length}</span>
        </div>
        
        {impact.direct_dependents.length === 0 ? (
          <div className="empty-section">
            <p>No dependent files found</p>
          </div>
        ) : (
          <div className="file-list">
            {impact.direct_dependents.slice(0, 10).map((dep) => (
              <div
                key={dep.node_id}
                className="file-item"
                onClick={() => handleNodeClick(dep.node_id)}
                style={{ cursor: onNavigate ? 'pointer' : 'default' }}
              >
                <span className="file-icon">📄</span>
                <div className="file-info">
                  <span className="file-name">{dep.name}</span>
                  <span className="file-path">{dep.filepath}</span>
                </div>
                <span className="file-kind">{dep.kind}</span>
              </div>
            ))}
            {impact.direct_dependents.length > 10 && (
              <div className="more-indicator">
                +{impact.direct_dependents.length - 10} more
              </div>
            )}
          </div>
        )}
      </div>

      {/* Test Files */}
      <div className="impact-section">
        <div className="section-header">
          <h4>Test Files</h4>
          <span className="badge">{impact.test_files.length}</span>
        </div>
        
        {impact.test_files.length === 0 ? (
          <div className="empty-section">
            <p>No test files found that exercise this symbol</p>
          </div>
        ) : (
          <div className="file-list">
            {impact.test_files.map((test, i) => (
              <div key={i} className="file-item test-file">
                <span className="file-icon">🧪</span>
                <div className="file-info">
                  <span className="file-name">{test.path}</span>
                  <span className="test-count">{test.test_count} test(s)</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style>{`
        .impact-analysis {
          padding: 0;
        }

        .impact-analysis h3 {
          font-size: 1.125rem;
          font-weight: 600;
          margin-bottom: 20px;
        }

        .impact-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          margin-bottom: 24px;
        }

        .impact-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 20px;
        }

        .risk-card {
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
        }

        .risk-score-container {
          margin-bottom: 12px;
        }

        .risk-info {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .risk-label {
          font-weight: 600;
          font-size: 0.875rem;
        }

        .risk-description {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .depth-card {
          display: flex;
          flex-direction: column;
          align-items: center;
        }

        .depth-indicator {
          text-align: center;
          margin-bottom: 12px;
        }

        .depth-value {
          font-size: 2.5rem;
          font-weight: 700;
          color: var(--accent);
        }

        .depth-label {
          font-size: 0.875rem;
          color: var(--text-secondary);
        }

        .depth-visual {
          display: flex;
          align-items: flex-end;
          gap: 4px;
          height: 40px;
          margin-bottom: 8px;
        }

        .depth-bar {
          width: 8px;
          background: var(--accent);
          border-radius: 2px;
        }

        .depth-description {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .impact-section {
          margin-bottom: 24px;
        }

        .section-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
        }

        .section-header h4 {
          font-size: 1rem;
          font-weight: 600;
        }

        .badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 24px;
          height: 24px;
          padding: 0 8px;
          background: var(--accent);
          color: white;
          font-size: 0.75rem;
          font-weight: 600;
          border-radius: 12px;
        }

        .file-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .file-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          transition: all 0.2s;
        }

        .file-item:hover {
          border-color: var(--accent);
          transform: translateX(4px);
        }

        .file-icon {
          font-size: 1.25rem;
        }

        .file-info {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }

        .file-name {
          font-weight: 500;
          color: var(--text-primary);
        }

        .file-path {
          font-size: 0.75rem;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .file-kind {
          font-size: 0.75rem;
          color: var(--text-muted);
          text-transform: capitalize;
          padding: 2px 8px;
          background: var(--bg-tertiary);
          border-radius: 4px;
        }

        .test-file .test-count {
          font-size: 0.75rem;
          color: var(--success);
        }

        .more-indicator {
          text-align: center;
          padding: 8px;
          color: var(--text-muted);
          font-size: 0.875rem;
        }

        .empty-section {
          padding: 24px;
          text-align: center;
          color: var(--text-muted);
          background: var(--bg-secondary);
          border: 1px dashed var(--border-color);
          border-radius: 8px;
        }

        @media (max-width: 600px) {
          .impact-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}