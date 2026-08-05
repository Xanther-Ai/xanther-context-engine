import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

export function useRepositories() {
  const [repositories, setRepositories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<any>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/repositories`);
      const data = await res.json();
      setRepositories(data.repositories || []);
      
      // Get overall stats
      let totalNodes = 0, totalEdges = 0, totalLines = 0;
      for (const repo of data.repositories || []) {
        const statsRes = await fetch(`${API_BASE}/api/repositories/${repo.repo_id}/stats`);
        const statsData = await statsRes.json();
        totalNodes += statsData.total_nodes || 0;
        totalEdges += statsData.total_edges || 0;
        totalLines += statsData.total_lines || 0;
      }
      setStats({
        total_nodes: totalNodes,
        total_edges: totalEdges,
        total_lines: totalLines
      });
    } catch (err) {
      console.error('Failed to fetch repositories:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const addRepository = async (path: string) => {
    const res = await fetch(`${API_BASE}/api/repositories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!res.ok) throw new Error('Failed to add repository');
    await refresh();
  };

  const removeRepository = async (repoId: string) => {
    const res = await fetch(`${API_BASE}/api/repositories/${repoId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('Failed to remove repository');
    await refresh();
  };

  const reindexRepository = async (repoId: string) => {
    const res = await fetch(`${API_BASE}/api/repositories/${repoId}/reindex`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to reindex repository');
    await refresh();
  };

  return { repositories, loading, stats, refresh, addRepository, removeRepository, reindexRepository };
}