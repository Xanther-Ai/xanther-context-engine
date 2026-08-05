import React, { useState, useEffect, useRef } from 'react';
import { useGraph } from '../../hooks/useGraph';

interface GraphExplorerProps {
  onSymbolSelect?: (symbolId: string, symbolName?: string) => void;
}

export default function GraphExplorer({ onSymbolSelect }: GraphExplorerProps) {
  const { nodes, edges, loading, fetchGraph, selectedNode, selectNode } = useGraph();
  const [filter, setFilter] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilter(e.target.value);
  };

  const filteredNodes = filter 
    ? nodes.filter(n => n.name?.toLowerCase().includes(filter.toLowerCase()) || n.kind?.includes(filter.toLowerCase()))
    : nodes;

  const nodeColors: Record<string, string> = {
    class: '#8b5cf6',
    function: '#10b981',
    method: '#10b981',
    module: '#6366f1',
    import: '#f59e0b',
    variable: '#64748b'
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
      <h2 style={{ marginBottom: '24px' }}>Graph Explorer</h2>

      <div className="card">
        <div style={{ display: 'flex', gap: '16px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <input
            type="text"
            className="input"
            placeholder="Filter by name or kind..."
            value={filter}
            onChange={handleFilterChange}
            style={{ maxWidth: '300px' }}
          />
          <button className="btn btn-secondary" onClick={() => fetchGraph()}>🔄 Refresh</button>
        </div>

        <div className="graph-container" ref={containerRef}>
          {nodes.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">🕸️</div>
              <div className="empty-state-title">No graph data</div>
              <p>Add and index a repository to see the graph</p>
            </div>
          ) : (
            <svg width="100%" height="100%" style={{ minHeight: '500px' }}>
              <defs>
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="var(--text-muted)" />
                </marker>
              </defs>
              
              {/* Edges */}
              {edges.slice(0, 500).map((edge: any, i: number) => {
                const sourceNode = nodes.find((n: any) => n.id === edge.source);
                const targetNode = nodes.find((n: any) => n.id === edge.target);
                if (!sourceNode || !targetNode) return null;
                
                const x1 = (parseInt(sourceNode.id?.slice(-8) || '0', 16) % 800) + 50;
                const y1 = (parseInt(sourceNode.id?.slice(-8) || '0', 16) % 500) + 50;
                const x2 = (parseInt(targetNode.id?.slice(-8) || '0', 16) % 800) + 50;
                const y2 = (parseInt(targetNode.id?.slice(-8) || '0', 16) % 500) + 50;
                
                return (
                  <line
                    key={`edge-${i}`}
                    x1={x1} y1={y1}
                    x2={x2} y2={y2}
                    stroke="var(--text-muted)"
                    strokeWidth="1"
                    opacity="0.4"
                    markerEnd="url(#arrowhead)"
                  />
                );
              })}
              
              {/* Nodes */}
              {filteredNodes.slice(0, 200).map((node: any) => {
                const x = (parseInt(node.id?.slice(-8) || '0', 16) % 800) + 50;
                const y = (parseInt(node.id?.slice(-8) || '0', 16) % 500) + 50;
                const color = nodeColors[node.kind] || '#64748b';
                
                return (
                  <g 
                    key={node.id} 
                    onClick={() => {
                      selectNode(node.id);
                      if (onSymbolSelect) {
                        onSymbolSelect(node.id, node.name);
                      }
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <circle
                      cx={x}
                      cy={y}
                      r={node.kind === 'class' ? 12 : 8}
                      fill={color}
                      stroke={selectedNode === node.id ? 'white' : 'transparent'}
                      strokeWidth="2"
                    />
                    <text
                      x={x + 15}
                      y={y + 4}
                      fill="var(--text-secondary)"
                      fontSize="11"
                    >
                      {node.name?.length > 20 ? node.name.slice(0, 20) + '...' : node.name}
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>

        <div style={{ marginTop: '16px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          {Object.entries(nodeColors).map(([kind, color]) => (
            <div key={kind} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: color }}></div>
              <span style={{ fontSize: '0.875rem', textTransform: 'capitalize' }}>{kind}</span>
            </div>
          ))}
        </div>
      </div>

      {selectedNode && (
        <div className="card" style={{ marginTop: '16px' }}>
          <h3 className="card-title">Selected Node</h3>
          <pre style={{ marginTop: '12px', padding: '12px', background: 'var(--bg-tertiary)', borderRadius: '8px', overflow: 'auto' }}>
            {JSON.stringify(nodes.find((n: any) => n.id === selectedNode), null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}