import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

interface ModuleNode {
  id: string;
  name: string;
  layer?: string;
  node_count: number;
  edge_count: number;
}

interface ModuleEdge {
  source: string;
  target: string;
  type: string;
}

interface CircularDependency {
  modules: string[];
  path: string[];
}

interface ArchitectureViewProps {
  onSymbolSelect?: (symbolId: string, symbolName?: string) => void;
}

interface ModuleDetails {
  name: string;
  layer: string;
  node_count: number;
  edge_count: number;
  dependencies: string[];
  dependents: string[];
  description?: string;
  public_api: string[];
}

export default function ArchitectureView({ onSymbolSelect }: ArchitectureViewProps) {
  const [modules, setModules] = useState<ModuleNode[]>([]);
  const [edges, setEdges] = useState<ModuleEdge[]>([]);
  const [circularDeps, setCircularDeps] = useState<CircularDependency[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedModule, setSelectedModule] = useState<string | null>(null);
  const [moduleDetails, setModuleDetails] = useState<ModuleDetails | null>(null);
  const [drillDownModule, setDrillDownModule] = useState<string | null>(null);
  const [moduleChildren, setModuleChildren] = useState<any[]>([]);
  const [viewMode, setViewMode] = useState<'graph' | 'layers' | 'circular'>('graph');

  const fetchArchitecture = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/architecture/modules`);
      if (!res.ok) {
        throw new Error('Failed to fetch architecture data');
      }
      const data = await res.json();
      setModules(data.modules || []);
      setEdges(data.edges || []);
      setCircularDeps(data.circular_dependencies || []);
    } catch (err) {
      console.error('Failed to fetch architecture:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchArchitecture();
  }, [fetchArchitecture]);

  const fetchModuleDetails = useCallback(async (moduleId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/architecture/module/${moduleId}/details`);
      if (res.ok) {
        const data = await res.json();
        setModuleDetails(data);
      }
    } catch (err) {
      console.error('Failed to fetch module details:', err);
    }
  }, []);

  const handleModuleClick = (moduleId: string) => {
    setSelectedModule(moduleId);
    setDrillDownModule(moduleId);
    fetchModuleDetails(moduleId);
    fetchModuleChildren(moduleId);
  };

  const fetchModuleChildren = async (moduleId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/architecture/module/${moduleId}/children`);
      if (res.ok) {
        const data = await res.json();
        setModuleChildren(data.children || []);
      }
    } catch (err) {
      console.error('Failed to fetch module children:', err);
      setModuleChildren([]);
    }
  };

  // Color scheme for layers
  const layerColors: Record<string, string> = {
    'presentation': '#8b5cf6',
    'application': '#6366f1',
    'domain': '#10b981',
    'infrastructure': '#f59e0b',
    'data': '#ec4899',
    'unknown': '#64748b'
  };

  const getLayerColor = (layer: string) => layerColors[layer?.toLowerCase()] || layerColors['unknown'];

  // Calculate positions for modules in a force-directed layout
  const calculatePositions = () => {
    const width = 800;
    const height = 500;
    const positions: Record<string, { x: number; y: number }> = {};
    
    // Group modules by layer
    const layerGroups: Record<string, ModuleNode[]> = {};
    modules.forEach(mod => {
      const layer = mod.layer || 'unknown';
      if (!layerGroups[layer]) layerGroups[layer] = [];
      layerGroups[layer].push(mod);
    });
    
    // Position modules by layer
    const layers = Object.keys(layerGroups);
    const layerWidth = width / (layers.length + 1);
    
    layers.forEach((layer, layerIndex) => {
      const layerModules = layerGroups[layer];
      const moduleHeight = height / (layerModules.length + 1);
      
      layerModules.forEach((mod, modIndex) => {
        positions[mod.id] = {
          x: (layerIndex + 1) * layerWidth,
          y: (modIndex + 1) * moduleHeight
        };
      });
    });
    
    return positions;
  };

  const positions = calculatePositions();

  // Check if edge is part of a circular dependency
  const isCircularEdge = (source: string, target: string): boolean => {
    return circularDeps.some(cd => {
      const idx = cd.modules.indexOf(source);
      if (idx === -1) return false;
      const nextIdx = (idx + 1) % cd.modules.length;
      return cd.modules[nextIdx] === target;
    });
  };

  const renderGraphView = () => {
    if (modules.length === 0) {
      return (
        <div className="empty-state">
          <div className="empty-state-icon">🏗️</div>
          <div className="empty-state-title">No architecture data</div>
          <p>Index a repository to see the module dependency graph</p>
        </div>
      );
    }

    return (
      <svg width="100%" height="500" viewBox="0 0 800 500" style={{ background: 'var(--bg-secondary)', borderRadius: '8px' }}>
        <defs>
          <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="var(--text-muted)" />
          </marker>
          <marker id="arrowhead-circular" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="#ef4444" />
          </marker>
        </defs>
        
        {/* Edges */}
        {edges.map((edge, i) => {
          const sourcePos = positions[edge.source];
          const targetPos = positions[edge.target];
          if (!sourcePos || !targetPos) return null;
          
          const isCircular = isCircularEdge(edge.source, edge.target);
          
          return (
            <line
              key={`edge-${i}`}
              x1={sourcePos.x} y1={sourcePos.y}
              x2={targetPos.x} y2={targetPos.y}
              stroke={isCircular ? '#ef4444' : 'var(--text-muted)'}
              strokeWidth={isCircular ? 2 : 1}
              strokeDasharray={isCircular ? '5,5' : undefined}
              opacity={isCircular ? 1 : 0.4}
              markerEnd={isCircular ? 'url(#arrowhead-circular)' : 'url(#arrowhead)'}
            />
          );
        })}
        
        {/* Modules */}
        {modules.map((mod) => {
          const pos = positions[mod.id];
          if (!pos) return null;
          const color = getLayerColor(mod.layer || 'unknown');
          const isSelected = selectedModule === mod.id;
          
          return (
            <g 
              key={mod.id} 
              onClick={() => handleModuleClick(mod.id)}
              style={{ cursor: 'pointer' }}
            >
              <circle
                cx={pos.x}
                cy={pos.y}
                r={isSelected ? 35 : 28}
                fill={color}
                stroke={isSelected ? 'white' : 'transparent'}
                strokeWidth="2"
                opacity={0.8}
              />
              <text
                x={pos.x}
                y={pos.y + 45}
                textAnchor="middle"
                fill="var(--text-primary)"
                fontSize="12"
                fontWeight="500"
              >
                {mod.name.length > 15 ? mod.name.slice(0, 15) + '...' : mod.name}
              </text>
              <text
                x={pos.x}
                y={pos.y + 60}
                textAnchor="middle"
                fill="var(--text-muted)"
                fontSize="10"
              >
                {mod.node_count} nodes
              </text>
            </g>
          );
        })}
      </svg>
    );
  };

  const renderLayersView = () => {
    const layerGroups: Record<string, ModuleNode[]> = {};
    modules.forEach(mod => {
      const layer = mod.layer || 'unknown';
      if (!layerGroups[layer]) layerGroups[layer] = [];
      layerGroups[layer].push(mod);
    });

    return (
      <div className="layers-view">
        {Object.entries(layerGroups).map(([layer, layerModules]) => (
          <div key={layer} className="layer-group">
            <div className="layer-header" style={{ borderLeftColor: getLayerColor(layer) }}>
              <h3 style={{ textTransform: 'capitalize' }}>{layer}</h3>
              <span className="layer-count">{layerModules.length} modules</span>
            </div>
            <div className="layer-modules">
              {layerModules.map(mod => (
                <div 
                  key={mod.id}
                  className={`module-card ${selectedModule === mod.id ? 'selected' : ''}`}
                  onClick={() => handleModuleClick(mod.id)}
                >
                  <div className="module-name">{mod.name}</div>
                  <div className="module-stats">
                    <span>{mod.node_count} nodes</span>
                    <span>{mod.edge_count} connections</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderCircularView = () => {
    if (circularDeps.length === 0) {
      return (
        <div className="empty-state">
          <div className="empty-state-icon">✅</div>
          <div className="empty-state-title">No circular dependencies</div>
          <p>Your module architecture is clean!</p>
        </div>
      );
    }

    return (
      <div className="circular-deps-view">
        <div className="warning-banner">
          <span className="warning-icon">⚠️</span>
          <span>Found {circularDeps.length} circular dependency chain(s)</span>
        </div>
        
        <div className="circular-list">
          {circularDeps.map((cd, i) => (
            <div key={i} className="circular-item">
              <div className="circular-path">
                {cd.modules.map((mod, idx) => (
                  <React.Fragment key={idx}>
                    <span className="circular-module">{mod}</span>
                    {idx < cd.modules.length - 1 && <span className="circular-arrow">→</span>}
                  </React.Fragment>
                ))}
              </div>
              <div className="circular-impact">
                Impact: {cd.modules.length} modules in cycle
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="architecture-view fade-in">
        <div className="loading">
          <div className="spinner"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="architecture-view fade-in">
        <div className="empty-state">
          <div className="empty-state-icon">⚠️</div>
          <div className="empty-state-title">Error loading architecture</div>
          <p>{error}</p>
          <button className="btn btn-primary" onClick={fetchArchitecture} style={{ marginTop: '16px' }}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="architecture-view fade-in">
      <div className="arch-header">
        <h2>Architecture View</h2>
        
        <div className="view-mode-tabs">
          <button 
            className={`tab-button ${viewMode === 'graph' ? 'active' : ''}`}
            onClick={() => setViewMode('graph')}
          >
            Dependency Graph
          </button>
          <button 
            className={`tab-button ${viewMode === 'layers' ? 'active' : ''}`}
            onClick={() => setViewMode('layers')}
          >
            By Layers
          </button>
          <button 
            className={`tab-button ${viewMode === 'circular' ? 'active' : ''}`}
            onClick={() => setViewMode('circular')}
          >
            Circular Dependencies
            {circularDeps.length > 0 && (
              <span className="warning-badge">{circularDeps.length}</span>
            )}
          </button>
        </div>
      </div>

      <div className="arch-content">
        <div className="main-view">
          {viewMode === 'graph' && renderGraphView()}
          {viewMode === 'layers' && renderLayersView()}
          {viewMode === 'circular' && renderCircularView()}
        </div>

        {/* Module Details Panel */}
        {selectedModule && (
          <div className="details-panel">
            <div className="details-header">
              <h3>{moduleDetails?.name || selectedModule}</h3>
              <button className="btn btn-ghost" onClick={() => { setSelectedModule(null); setDrillDownModule(null); }}>
                ✕
              </button>
            </div>
            
            {moduleDetails && (
              <div className="details-content">
                <div className="detail-row">
                  <span className="detail-label">Layer</span>
                  <span 
                    className="detail-value layer-badge"
                    style={{ background: getLayerColor(moduleDetails.layer), color: 'white' }}
                  >
                    {moduleDetails.layer}
                  </span>
                </div>
                
                <div className="detail-row">
                  <span className="detail-label">Nodes</span>
                  <span className="detail-value">{moduleDetails.node_count}</span>
                </div>
                
                <div className="detail-row">
                  <span className="detail-label">Connections</span>
                  <span className="detail-value">{moduleDetails.edge_count}</span>
                </div>

                {moduleDetails.dependencies && moduleDetails.dependencies.length > 0 && (
                  <div className="detail-section">
                    <span className="detail-label">Dependencies</span>
                    <div className="tag-list">
                      {moduleDetails.dependencies.map((dep, i) => (
                        <span 
                          key={i} 
                          className="tag dependency"
                          onClick={() => handleModuleClick(dep)}
                        >
                          {dep}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {moduleDetails.dependents && moduleDetails.dependents.length > 0 && (
                  <div className="detail-section">
                    <span className="detail-label">Dependents</span>
                    <div className="tag-list">
                      {moduleDetails.dependents.map((dep, i) => (
                        <span 
                          key={i} 
                          className="tag dependent"
                          onClick={() => handleModuleClick(dep)}
                        >
                          {dep}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {moduleDetails.public_api && moduleDetails.public_api.length > 0 && (
                  <div className="detail-section">
                    <span className="detail-label">Public API</span>
                    <div className="api-list">
                      {moduleDetails.public_api.slice(0, 5).map((api, i) => (
                        <code key={i} className="api-item">{api}</code>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="legend">
        {Object.entries(layerColors).map(([layer, color]) => (
          <div key={layer} className="legend-item">
            <div className="legend-dot" style={{ background: color }}></div>
            <span style={{ textTransform: 'capitalize' }}>{layer}</span>
          </div>
        ))}
      </div>

      <style>{`
        .architecture-view {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .arch-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          flex-wrap: wrap;
          gap: 16px;
        }

        .arch-header h2 {
          margin: 0;
        }

        .view-mode-tabs {
          display: flex;
          gap: 4px;
          background: var(--bg-tertiary);
          padding: 4px;
          border-radius: 8px;
        }

        .tab-button {
          padding: 8px 16px;
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
          gap: 6px;
        }

        .tab-button:hover {
          color: var(--text-primary);
        }

        .tab-button.active {
          background: var(--accent);
          color: white;
        }

        .warning-badge {
          background: #ef4444;
          color: white;
          font-size: 0.75rem;
          padding: 2px 6px;
          border-radius: 10px;
        }

        .arch-content {
          display: grid;
          grid-template-columns: 1fr 300px;
          gap: 20px;
        }

        .main-view {
          min-height: 500px;
        }

        .layers-view {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .layer-group {
          background: var(--bg-secondary);
          border-radius: 12px;
          padding: 16px;
        }

        .layer-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-left: 12px;
          border-left: 4px solid;
          margin-bottom: 16px;
        }

        .layer-header h3 {
          margin: 0;
          font-size: 1rem;
        }

        .layer-count {
          font-size: 0.875rem;
          color: var(--text-muted);
        }

        .layer-modules {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
        }

        .module-card {
          padding: 12px 16px;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .module-card:hover {
          border-color: var(--accent);
        }

        .module-card.selected {
          border-color: var(--accent);
          background: var(--accent);
          color: white;
        }

        .module-name {
          font-weight: 500;
        }

        .module-stats {
          display: flex;
          gap: 12px;
          font-size: 0.75rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        .module-card.selected .module-stats {
          color: rgba(255, 255, 255, 0.8);
        }

        .circular-deps-view {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .warning-banner {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 16px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 8px;
          color: #ef4444;
        }

        .warning-icon {
          font-size: 1.25rem;
        }

        .circular-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .circular-item {
          padding: 16px;
          background: var(--bg-secondary);
          border: 1px solid #ef4444;
          border-radius: 8px;
        }

        .circular-path {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .circular-module {
          padding: 4px 12px;
          background: rgba(239, 68, 68, 0.2);
          color: #ef4444;
          border-radius: 4px;
          font-size: 0.875rem;
          font-weight: 500;
        }

        .circular-arrow {
          color: #ef4444;
        }

        .circular-impact {
          margin-top: 8px;
          font-size: 0.875rem;
          color: var(--text-muted);
        }

        .details-panel {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 20px;
          height: fit-content;
        }

        .details-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }

        .details-header h3 {
          margin: 0;
          font-size: 1.125rem;
        }

        .details-content {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .detail-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .detail-label {
          font-size: 0.875rem;
          color: var(--text-muted);
        }

        .detail-value {
          font-weight: 500;
        }

        .layer-badge {
          padding: 4px 12px;
          border-radius: 4px;
          font-size: 0.75rem;
          text-transform: capitalize;
        }

        .detail-section {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .tag-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .tag {
          padding: 4px 10px;
          border-radius: 4px;
          font-size: 0.75rem;
          cursor: pointer;
          transition: all 0.2s;
        }

        .tag.dependency {
          background: rgba(99, 102, 241, 0.2);
          color: var(--accent);
        }

        .tag.dependent {
          background: rgba(16, 185, 129, 0.2);
          color: var(--success);
        }

        .tag:hover {
          transform: scale(1.05);
        }

        .api-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .api-item {
          padding: 6px 10px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          font-size: 0.8rem;
          font-family: 'Fira Code', monospace;
        }

        .legend {
          display: flex;
          gap: 20px;
          flex-wrap: wrap;
          padding: 16px;
          background: var(--bg-secondary);
          border-radius: 8px;
        }

        .legend-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.875rem;
        }

        .legend-dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
        }

        @media (max-width: 900px) {
          .arch-content {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}