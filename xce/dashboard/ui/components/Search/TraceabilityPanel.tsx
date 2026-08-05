import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

interface TraceabilityData {
  component_description?: {
    summary: string;
    responsibilities: string[];
    public_api: string[];
  };
  linked_tests?: Array<{
    path: string;
    name: string;
    coverage_percentage?: number;
  }>;
  architecture_context?: {
    module: string;
    layer: string;
    dependencies: string[];
    dependents: string[];
  };
  requirement_links?: Array<{
    id: string;
    type: string;
    description: string;
  }>;
  issue_references?: Array<{
    id: string;
    title: string;
    status: string;
  }>;
}

interface TraceabilityPanelProps {
  symbolId: string;
  onNavigate?: (symbolId: string) => void;
}

export default function TraceabilityPanel({ symbolId, onNavigate }: TraceabilityPanelProps) {
  const [traceability, setTraceability] = useState<TraceabilityData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'description' | 'tests' | 'architecture'>('description');

  const fetchTraceability = useCallback(async () => {
    if (!symbolId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/symbol/${symbolId}/trace`);
      
      if (!res.ok) {
        throw new Error('Failed to fetch traceability data');
      }

      const data = await res.json();
      setTraceability(data);
    } catch (err) {
      console.error('Failed to fetch traceability:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [symbolId]);

  useEffect(() => {
    fetchTraceability();
  }, [fetchTraceability]);

  const renderDescriptionTab = () => {
    if (!traceability?.component_description) {
      return (
        <div className="empty-section">
          <div className="empty-state-icon">📝</div>
          <div className="empty-state-title">No description available</div>
          <p>Component description not found in documentation</p>
        </div>
      );
    }

    const desc = traceability.component_description;

    return (
      <div className="description-content">
        <div className="summary-section">
          <h4>Summary</h4>
          <p className="summary-text">{desc.summary}</p>
        </div>

        {desc.responsibilities && desc.responsibilities.length > 0 && (
          <div className="responsibilities-section">
            <h4>Responsibilities</h4>
            <ul className="responsibility-list">
              {desc.responsibilities.map((resp, i) => (
                <li key={i}>{resp}</li>
              ))}
            </ul>
          </div>
        )}

        {desc.public_api && desc.public_api.length > 0 && (
          <div className="api-section">
            <h4>Public API</h4>
            <div className="api-list">
              {desc.public_api.map((api, i) => (
                <span key={i} className="api-item">{api}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderTestsTab = () => {
    const tests = traceability?.linked_tests || [];
    
    if (tests.length === 0) {
      return (
        <div className="empty-section">
          <div className="empty-state-icon">🧪</div>
          <div className="empty-state-title">No linked tests</div>
          <p>No test files were found for this symbol</p>
        </div>
      );
    }

    return (
      <div className="tests-content">
        {tests.map((test, i) => (
          <div key={i} className="test-item">
            <div className="test-header">
              <span className="test-icon">🧪</span>
              <span className="test-name">{test.name}</span>
              {test.coverage_percentage !== undefined && (
                <span 
                  className="coverage-badge"
                  style={{ 
                    background: test.coverage_percentage >= 80 
                      ? 'rgba(16, 185, 129, 0.2)' 
                      : test.coverage_percentage >= 50
                        ? 'rgba(245, 158, 11, 0.2)'
                        : 'rgba(239, 68, 68, 0.2)',
                    color: test.coverage_percentage >= 80 
                      ? 'var(--success)' 
                      : test.coverage_percentage >= 50
                        ? 'var(--warning)'
                        : 'var(--error)'
                  }}
                >
                  {test.coverage_percentage}% coverage
                </span>
              )}
            </div>
            <div className="test-path">{test.path}</div>
          </div>
        ))}
      </div>
    );
  };

  const renderArchitectureTab = () => {
    if (!traceability?.architecture_context) {
      return (
        <div className="empty-section">
          <div className="empty-state-icon">🏗️</div>
          <div className="empty-state-title">No architecture context</div>
          <p>Architecture information not available</p>
        </div>
      );
    }

    const arch = traceability.architecture_context;

    return (
      <div className="architecture-content">
        <div className="arch-header">
          <div className="arch-module">
            <span className="arch-label">Module</span>
            <span className="arch-value">{arch.module}</span>
          </div>
          <div className="arch-layer">
            <span className="arch-label">Layer</span>
            <span className="arch-value layer-badge">{arch.layer}</span>
          </div>
        </div>

        {arch.dependencies && arch.dependencies.length > 0 && (
          <div className="arch-section">
            <h4>Dependencies</h4>
            <div className="arch-tags">
              {arch.dependencies.map((dep, i) => (
                <span key={i} className="arch-tag dependency">{dep}</span>
              ))}
            </div>
          </div>
        )}

        {arch.dependents && arch.dependents.length > 0 && (
          <div className="arch-section">
            <h4>Dependents</h4>
            <div className="arch-tags">
              {arch.dependents.map((dep, i) => (
                <span key={i} className="arch-tag dependent">{dep}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="traceability-panel fade-in">
        <div className="loading">
          <div className="spinner"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="traceability-panel fade-in">
        <div className="empty-state">
          <div className="empty-state-icon">⚠️</div>
          <div className="empty-state-title">Error loading data</div>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!traceability) {
    return (
      <div className="traceability-panel fade-in">
        <div className="empty-state">
          <div className="empty-state-icon">🔗</div>
          <div className="empty-state-title">No traceability data</div>
          <p>Select a symbol to view its traceability</p>
        </div>
      </div>
    );
  }

  const tabs = [
    { id: 'description', label: 'Description', hasContent: !!traceability.component_description },
    { id: 'tests', label: 'Tests', hasContent: (traceability.linked_tests?.length || 0) > 0 },
    { id: 'architecture', label: 'Architecture', hasContent: !!traceability.architecture_context }
  ] as const;

  return (
    <div className="traceability-panel fade-in">
      <h3>Traceability</h3>

      <div className="tab-container">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
            {!tab.hasContent && <span className="no-data-dot" title="No data available">•</span>}
          </button>
        ))}
      </div>

      <div className="panel-content">
        {activeTab === 'description' && renderDescriptionTab()}
        {activeTab === 'tests' && renderTestsTab()}
        {activeTab === 'architecture' && renderArchitectureTab()}
      </div>

      {/* Requirement Links */}
      {traceability.requirement_links && traceability.requirement_links.length > 0 && (
        <div className="requirements-section">
          <h4>Requirement Links</h4>
          <div className="requirements-list">
            {traceability.requirement_links.map((req, i) => (
              <div key={i} className="requirement-item">
                <span className="req-type">{req.type}</span>
                <span className="req-id">{req.id}</span>
                <span className="req-description">{req.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Issue References */}
      {traceability.issue_references && traceability.issue_references.length > 0 && (
        <div className="issues-section">
          <h4>Issue References</h4>
          <div className="issues-list">
            {traceability.issue_references.map((issue, i) => (
              <div key={i} className="issue-item">
                <span className="issue-id">#{issue.id}</span>
                <span className="issue-title">{issue.title}</span>
                <span className={`issue-status status-${issue.status}`}>{issue.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`
        .traceability-panel {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .traceability-panel h3 {
          font-size: 1.125rem;
          font-weight: 600;
        }

        .tab-container {
          display: flex;
          gap: 4px;
          background: var(--bg-tertiary);
          padding: 4px;
          border-radius: 8px;
        }

        .tab-button {
          flex: 1;
          padding: 10px 16px;
          border: none;
          background: transparent;
          color: var(--text-secondary);
          font-size: 0.875rem;
          font-weight: 500;
          cursor: pointer;
          border-radius: 6px;
          transition: all 0.2s;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
        }

        .tab-button:hover {
          color: var(--text-primary);
        }

        .tab-button.active {
          background: var(--accent);
          color: white;
        }

        .no-data-dot {
          color: var(--text-muted);
          font-size: 1.25rem;
        }

        .panel-content {
          min-height: 200px;
        }

        .description-content,
        .tests-content,
        .architecture-content {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .summary-section h4,
        .responsibilities-section h4,
        .api-section h4,
        .arch-section h4 {
          font-size: 0.875rem;
          font-weight: 600;
          color: var(--text-secondary);
          margin-bottom: 8px;
        }

        .summary-text {
          color: var(--text-primary);
          line-height: 1.6;
        }

        .responsibility-list {
          list-style: disc;
          padding-left: 20px;
          color: var(--text-secondary);
        }

        .responsibility-list li {
          margin-bottom: 4px;
        }

        .api-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .api-item {
          padding: 4px 12px;
          background: var(--accent);
          color: white;
          border-radius: 4px;
          font-size: 0.875rem;
          font-family: 'Fira Code', monospace;
        }

        .test-item {
          padding: 12px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 8px;
        }

        .test-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }

        .test-icon {
          font-size: 1rem;
        }

        .test-name {
          font-weight: 500;
          flex: 1;
        }

        .coverage-badge {
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 500;
        }

        .test-path {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .arch-header {
          display: flex;
          gap: 16px;
          margin-bottom: 16px;
        }

        .arch-module,
        .arch-layer {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .arch-label {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .arch-value {
          font-weight: 600;
        }

        .layer-badge {
          padding: 2px 8px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          font-size: 0.875rem;
        }

        .arch-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .arch-tag {
          padding: 4px 12px;
          border-radius: 4px;
          font-size: 0.875rem;
        }

        .arch-tag.dependency {
          background: rgba(99, 102, 241, 0.2);
          color: var(--accent);
        }

        .arch-tag.dependent {
          background: rgba(16, 185, 129, 0.2);
          color: var(--success);
        }

        .empty-section {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 40px 20px;
          text-align: center;
        }

        .empty-section p {
          color: var(--text-muted);
          font-size: 0.875rem;
        }

        .requirements-section,
        .issues-section {
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid var(--border-color);
        }

        .requirements-section h4,
        .issues-section h4 {
          font-size: 0.875rem;
          font-weight: 600;
          margin-bottom: 12px;
        }

        .requirements-list,
        .issues-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .requirement-item,
        .issue-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          background: var(--bg-secondary);
          border-radius: 6px;
          font-size: 0.875rem;
        }

        .req-type,
        .issue-status {
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 500;
          text-transform: uppercase;
        }

        .req-type {
          background: var(--bg-tertiary);
          color: var(--text-secondary);
        }

        .issue-status {
          margin-left: auto;
        }

        .status-open {
          background: rgba(99, 102, 241, 0.2);
          color: var(--accent);
        }

        .status-closed {
          background: rgba(16, 185, 129, 0.2);
          color: var(--success);
        }

        .req-id,
        .issue-id {
          color: var(--text-muted);
          font-family: 'Fira Code', monospace;
        }

        .req-description,
        .issue-title {
          flex: 1;
          color: var(--text-secondary);
        }
      `}</style>
    </div>
  );
}