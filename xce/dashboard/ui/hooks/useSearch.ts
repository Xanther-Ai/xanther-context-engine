import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

export function useSearch() {
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchHistory, setSearchHistory] = useState<any[]>([]);

  const search = useCallback(async (query: string, repoId?: string) => {
    setLoading(true);
    try {
      let url = `${API_BASE}/api/search?q=${encodeURIComponent(query)}`;
      if (repoId) url += `&repo_id=${repoId}`;
      
      const res = await fetch(url);
      const data = await res.json();
      setResults(data.results || []);
      
      // Refresh history
      const historyRes = await fetch(`${API_BASE}/api/search/history`);
      const historyData = await historyRes.json();
      setSearchHistory(historyData.history || []);
    } catch (err) {
      console.error('Search failed:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    // Load search history on mount
    fetch(`${API_BASE}/api/search/history`)
      .then(res => res.json())
      .then(data => setSearchHistory(data.history || []))
      .catch(console.error);
  }, []);

  return { results, loading, search, searchHistory };
}