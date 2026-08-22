import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

interface SymbolNode {
  node_id: string;
  name: string;
  kind: string;
  filepath?: string;
}

interface CallersCalleesProps {
  symbolId: string;
  onNavigate?: (symbolId: string) => void;
}

export default function CallersCallees({ symbolId, onNavigate }: CallersCalleesProps) {
  const [callers, setCallers] = useState<SymbolNode[]>([]);
  const [callees, setCallees] = useState<SymbolNode[]>([]);
  const [depth, setDepth] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'callers' | 'callees'>('callers');

  const fetchCallersCallees = useCallback(async () => {
    if (!symbolId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const [callersRes, calleesRes] = await Promise.all([
        fetch(`${API_BASE}/api/symbol/${symbolId}/callers?depth=${depth}`),
        fetch(`${API_BASE}/api/symbol/${symbolId}/callees?depth=${depth}`)
      ]);

      if (!callersRes.ok || !calleesRes.ok) {
        throw new Error('Failed to fetch call chain data');
      }

      const [callersData, calleesData] = await Promise.all([
        callersRes.json(),
        calleesRes.json()
      ]);

      setCallers(callersData.callers || []);
      setCallees(calleesData.callees || []);
    } catch (err) {
      console.error('Failed to fetch callers/callees:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [symbolId, depth]);

  useEffect(() => {
    fetchCallersCallees();
  }, [fetchCallersCallees]);

  const handleNodeClick = (nodeId: string) => {
    if (onNavigate) {
      onNavigate(nodeId);
    }
  };

  const renderNodeList = (nodes: SymbolNode[], title: string) => {
    if (loading) {
      return (
        <div className="loading">
          <div className="spinner"></div>
        </div>
      );
    }

    if (error) {
      return (
        <div className="empty-state">
          <div className="empty-state-icon">⚠️</div>
          <div className="empty-state-title">Error loading data</div>
          <p>{error}</p>
        </div>
      );
    }

    if (nodes.length === 0) {
      return (
        <div className="empty-state">
          <div className="empty-state-icon">🔗</div>
          <div className="empty-state-title">No {title}</div>
          <p>No {title.toLowerCase()} found at depth {depth}</p>
        </div>
      );
    }

    const nodeColors: Record<string, string> = {
      class: '#8b5cf6',
      function: '#10b981',
      method: '#10b981',
      module: '#6366f1',
      import: '#f59e0b',
      variable: '#64748b'
    };

    return (
      <div className="node-list">
        {nodes.map((node) => (
          <div
            key={node.node_id}
            className="node-item"
            onClick={() => handleNodeClick(node.node_id)}
            style={{ cursor: onNavigate ? 'pointer' : 'default' }}
          >
            <div 
              className="node-color-dot"
              style={{ backgroundColor: nodeColors[node.kind] || '#64748b' }}
            />
            <div className="node-info">
              <span className="node-name">{node.name}</span>
              <span className="node-kind">{node.kind}</span>
              {node.filepath && (
                <span className="node-filepath">{node.filepath}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="callers-callees-panel fade-in">
      <div className="panel-header">
        <h3>Call Chain Analysis</h3>
        <div className="depth-selector">
          <label htmlFor="depth-select">Depth:</label>
          <select
            id="depth-select"
            className="input"
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            style={{ width: 'auto', minWidth: '80px' }}
          >
            {[1, 2, 3, 4, 5].map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="tab-container">
        <button
          className={`tab-button ${activeTab === 'callers' ? 'active' : ''}`}
          onClick={() => setActiveTab('callers')}
        >
          Callers ({callers.length})
        </button>
        <button
          className={`tab-button ${activeTab === 'callees' ? 'active' : ''}`}
          onClick={() => setActiveTab('callees')}
        >
          Callees ({callees.length})
        </button>
      </div>

      <div className="panel-content">
        {activeTab === 'callers' 
          ? renderNodeList(callers, 'Callers')
          : renderNodeList(callees, 'Callees')
        }
      </div>

      <style>{`
        .callers-callees-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
        }

        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          flex-wrap: wrap;
          gap: 12px;
        }

        .panel-header h3 {
          font-size: 1.125rem;
          font-weight: 600;
        }

        .depth-selector {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .depth-selector label {
          font-size: 0.875rem;
          color: var(--text-secondary);
        }

        .tab-container {
          display: flex;
          gap: 4px;
          margin-bottom: 16px;
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
        }

        .tab-button:hover {
          color: var(--text-primary);
        }

        .tab-button.active {
          background: var(--accent);
          color: white;
        }

        .panel-content {
          flex: 1;
          overflow-y: auto;
          min-height: 200px;
        }

        .node-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .node-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          transition: all 0.2s;
        }

        .node-item:hover {
          border-color: var(--accent);
          transform: translateX(4px);
        }

        .node-color-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          flex-shrink: 0;
        }

        .node-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }

        .node-name {
          font-weight: 500;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .node-kind {
          font-size: 0.75rem;
          color: var(--text-muted);
          text-transform: capitalize;
        }

        .node-filepath {
          font-size: 0.75rem;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      `}</style>
    </div>
  );
}