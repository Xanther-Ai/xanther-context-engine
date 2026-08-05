import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

export function useGraph() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const fetchGraph = useCallback(async (repoId?: string) => {
    setLoading(true);
    try {
      // Get first repository if not specified
      if (!repoId) {
        const reposRes = await fetch(`${API_BASE}/api/repositories`);
        const reposData = await reposRes.json();
        if (reposData.repositories?.length > 0) {
          repoId = reposData.repositories[0].repo_id;
        }
      }
      
      if (repoId) {
        const [nodesRes, edgesRes] = await Promise.all([
          fetch(`${API_BASE}/api/graph/nodes?repo_id=${repoId}&limit=500`),
          fetch(`${API_BASE}/api/graph/edges?repo_id=${repoId}&limit=500`)
        ]);
        
        const nodesData = await nodesRes.json();
        const edgesData = await edgesRes.json();
        
        setNodes(nodesData.nodes || []);
        setEdges(edgesData.edges || []);
      }
    } catch (err) {
      console.error('Failed to fetch graph:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const selectNode = (nodeId: string) => {
    setSelectedNode(selectedNode === nodeId ? null : nodeId);
  };

  return { nodes, edges, loading, fetchGraph, selectedNode, selectNode };
}