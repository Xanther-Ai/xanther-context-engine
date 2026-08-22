import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Network, DataSet, Options } from 'vis-network/standalone';

const API_BASE = import.meta.env.VITE_API_URL || '';

// PRAT Layer colors
const LAYER_COLORS = {
  // P: Parse layer (AST nodes)
  class: { background: '#8b5cf6', border: '#6d28d9', font: '#fff' },
  function: { background: '#10b981', border: '#059669', font: '#fff' },
  method: { background: '#06b6d4', border: '#0891b2', font: '#fff' },
  module: { background: '#6366f1', border: '#4f46e5', font: '#fff' },
  // R: Relate (edges are colored by type)
  // A: Annotate (description nodes)
  description: { background: '#f59e0b', border: '#d97706', font: '#000' },
  component_doc: { background: '#ef4444', border: '#dc2626', font: '#fff' },
  // T: Architecture (HLD nodes)
  architecture: { background: '#ec4899', border: '#db2777', font: '#fff' },
};

const EDGE_COLORS: Record<string, string> = {
  CALLS: '#3b82f6',
  IMPORTS: '#22c55e',
  INHERITS: '#ef4444',
  CONTAINS: '#94a3b8',
  DESCRIBED_BY: '#f59e0b',
  DETAILED_IN: '#ef4444',
  PART_OF_ARCHITECTURE: '#ec4899',
};

interface GraphExplorerProps {
  onSymbolSelect?: (symbolId: string, symbolName?: string) => void;
}

export default function GraphExplorer({ onSymbolSelect }: GraphExplorerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [loading, setLoading] = useState(true);
  const [repos, setRepos] = useState<any[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>('');
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [stats, setStats] = useState({ nodes: 0, edges: 0 });
  const [layers, setLayers] = useState({
    parse: true,      // P: AST nodes
    relate: true,     // R: Edges
    annotate: false,  // A: Descriptions + ComponentDocs
    traverse: false,  // T: Architecture docs
  });
  const [filter, setFilter] = useState('');

  // Fetch repos
  useEffect(() => {
    fetch(`${API_BASE}/api/graph/repos`)
      .then(r => r.json())
      .then(data => {
        const repoList = data.repos || [];
        setRepos(repoList);
        if (repoList.length > 0 && !selectedRepo) {
          // Pick first non-test repo
          const real = repoList.find((r: any) => !r.repo_id.startsWith('test_') && !r.repo_id.startsWith('tgr_'));
          setSelectedRepo(real?.repo_id || repoList[0].repo_id);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch graph when repo changes
  const fetchAndRender = useCallback(async () => {
    if (!selectedRepo || !containerRef.current) return;
    setLoading(true);

    try {
      const [nodesRes, edgesRes] = await Promise.all([
        fetch(`${API_BASE}/api/graph/nodes?repo_id=${selectedRepo}&limit=300`),
        fetch(`${API_BASE}/api/graph/edges?repo_id=${selectedRepo}&limit=500`),
      ]);
      const nodesData = await nodesRes.json();
      const edgesData = await edgesRes.json();

      const rawNodes = nodesData.nodes || [];
      const rawEdges = edgesData.edges || [];

      // Build vis-network data
      const visNodes = new DataSet<any>();
      const visEdges = new DataSet<any>();

      // Filter based on active layers
      for (const n of rawNodes) {
        if (!layers.parse && ['class', 'function', 'method', 'module'].includes(n.kind)) continue;
        if (filter && !n.name?.toLowerCase().includes(filter.toLowerCase())) continue;

        const colors = LAYER_COLORS[n.kind as keyof typeof LAYER_COLORS] || LAYER_COLORS.function;
        const size = n.kind === 'class' ? 30 : n.kind === 'module' ? 25 : 18;
        const shape = n.kind === 'class' ? 'box' : n.kind === 'module' ? 'diamond' : 'dot';

        visNodes.add({
          id: n.id,
          label: n.name || '?',
          title: `${n.kind}: ${n.name}\n${n.filepath || ''}\nLines: ${n.start_line || '?'}-${n.end_line || '?'}${n.docstring ? '\n' + n.docstring.slice(0, 100) : ''}`,
          color: colors,
          size,
          shape,
          font: { color: colors.font, size: 11 },
          kind: n.kind,
          filepath: n.filepath,
          data: n,
        });
      }

      if (layers.relate) {
        for (const e of rawEdges) {
          if (!visNodes.get(e.source) || !visNodes.get(e.target)) continue;
          visEdges.add({
            from: e.source,
            to: e.target,
            arrows: 'to',
            color: { color: EDGE_COLORS[e.relation] || '#64748b', opacity: 0.6 },
            title: e.relation,
            dashes: e.relation === 'IMPORTS',
            width: e.relation === 'INHERITS' ? 3 : 1,
          });
        }
      }

      setStats({ nodes: visNodes.length, edges: visEdges.length });

      // Create network
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }

      // Clear the container manually to avoid React conflicts
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }

      const options: Options = {
        nodes: {
          borderWidth: 2,
          shadow: true,
          font: { size: 11, face: 'Inter, system-ui, sans-serif' },
        },
        edges: {
          smooth: { enabled: true, type: 'continuous', roundness: 0.2 },
          arrows: { to: { scaleFactor: 0.5 } },
        },
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: {
            gravitationalConstant: -40,
            centralGravity: 0.005,
            springLength: 120,
            springConstant: 0.05,
            damping: 0.4,
          },
          stabilization: { iterations: 150, fit: true },
        },
        interaction: {
          hover: true,
          tooltipDelay: 100,
          zoomView: true,
          dragView: true,
          navigationButtons: true,
        },
        layout: {
          improvedLayout: false,
        },
      };

      const network = new Network(containerRef.current, { nodes: visNodes, edges: visEdges }, options);
      networkRef.current = network;

      network.on('click', (params) => {
        if (params.nodes.length > 0) {
          const nodeId = params.nodes[0];
          const node = visNodes.get(nodeId) as any;
          setSelectedNode(node?.data || node);
          if (onSymbolSelect && node) {
            onSymbolSelect(nodeId as string, node?.label);
          }
        } else {
          setSelectedNode(null);
        }
      });

      network.on('stabilizationIterationsDone', () => {
        network.setOptions({ physics: { enabled: false } });
      });

    } catch (err) {
      console.error('Graph fetch failed:', err);
    }
    setLoading(false);
  }, [selectedRepo, layers, filter]);

  useEffect(() => {
    fetchAndRender();
    // Cleanup on unmount
    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [selectedRepo, layers]);

  return (
    <div className="fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Controls bar */}
      <div style={{ padding: '12px 16px', display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', borderBottom: '1px solid var(--border)' }}>
        {/* Repo selector */}
        <select
          value={selectedRepo}
          onChange={(e) => setSelectedRepo(e.target.value)}
          style={{ padding: '6px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
        >
          {repos.filter(r => !r.repo_id.startsWith('test_') && !r.repo_id.startsWith('tgr_')).map(r => (
            <option key={r.repo_id} value={r.repo_id}>{r.repo_id} ({r.node_count} nodes)</option>
          ))}
        </select>

        {/* Search */}
        <input
          type="text"
          placeholder="Search symbols..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchAndRender()}
          style={{ padding: '6px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', width: '200px' }}
        />

        {/* PRAT Layer toggles */}
        <div style={{ display: 'flex', gap: '4px' }}>
          {[
            { key: 'parse', label: 'P', title: 'Parse (AST nodes)', color: '#10b981' },
            { key: 'relate', label: 'R', title: 'Relate (edges)', color: '#3b82f6' },
            { key: 'annotate', label: 'A', title: 'Annotate (descriptions)', color: '#f59e0b' },
            { key: 'traverse', label: 'T', title: 'Traverse (architecture)', color: '#ec4899' },
          ].map(l => (
            <button
              key={l.key}
              title={l.title}
              onClick={() => setLayers(prev => ({ ...prev, [l.key]: !prev[l.key as keyof typeof prev] }))}
              style={{
                width: '28px', height: '28px', borderRadius: '4px',
                border: `2px solid ${l.color}`,
                background: layers[l.key as keyof typeof layers] ? l.color : 'transparent',
                color: layers[l.key as keyof typeof layers] ? '#fff' : l.color,
                fontWeight: 'bold', fontSize: '12px', cursor: 'pointer',
              }}
            >
              {l.label}
            </button>
          ))}
        </div>

        {/* Stats */}
        <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {stats.nodes} nodes · {stats.edges} edges
        </span>
      </div>

      {/* Graph canvas - use key to prevent React from reconciling vis-network's DOM */}
      <div style={{ flex: 1, minHeight: '600px', background: 'var(--bg-primary)', position: 'relative' }}>
        {loading && (
          <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', zIndex: 10 }}>
            <div className="spinner" />
          </div>
        )}
        <div
          ref={containerRef}
          style={{ width: '100%', height: '100%', minHeight: '600px' }}
          dangerouslySetInnerHTML={{ __html: '' }}
        />
      </div>

      {/* Selected node detail */}
      {selectedNode && (
        <div style={{ padding: '16px', borderTop: '1px solid var(--border)', maxHeight: '250px', overflow: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>
              <span style={{ color: LAYER_COLORS[selectedNode.kind as keyof typeof LAYER_COLORS]?.background || '#888' }}>●</span>
              {' '}{selectedNode.name}
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{selectedNode.kind} · {selectedNode.filepath}</span>
          </div>
          {selectedNode.signature && <code style={{ display: 'block', marginTop: '8px', fontSize: '12px', color: 'var(--text-secondary)' }}>{selectedNode.signature}</code>}
          {selectedNode.docstring && <p style={{ marginTop: '8px', fontSize: '13px', color: 'var(--text-secondary)' }}>{selectedNode.docstring}</p>}
          <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
            Lines {selectedNode.start_line}–{selectedNode.end_line} · ID: {selectedNode.id?.slice(0, 40)}...
          </div>
        </div>
      )}

      {/* Legend */}
      <div style={{ padding: '8px 16px', display: 'flex', gap: '16px', flexWrap: 'wrap', borderTop: '1px solid var(--border)', fontSize: '11px' }}>
        <span><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '2px', background: '#8b5cf6', marginRight: '4px' }}></span>Class</span>
        <span><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: '#10b981', marginRight: '4px' }}></span>Function</span>
        <span><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: '#06b6d4', marginRight: '4px' }}></span>Method</span>
        <span><span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: '#6366f1', marginRight: '4px' }}></span>Module</span>
        <span style={{ marginLeft: '16px' }}>—<span style={{ color: '#3b82f6' }}> Calls</span></span>
        <span>- -<span style={{ color: '#22c55e' }}> Imports</span></span>
        <span>━<span style={{ color: '#ef4444' }}> Inherits</span></span>
      </div>
    </div>
  );
}
