import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

export function useProgress() {
  const [progress, setProgress] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // Poll for progress updates
    const fetchProgress = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/indexing/progress`);
        if (res.ok) {
          const data = await res.json();
          setProgress(data.progress || []);
          setConnected(true);
        } else {
          setConnected(false);
        }
      } catch {
        setConnected(false);
      }
    };

    fetchProgress();
    const interval = setInterval(fetchProgress, 2000);
    
    return () => clearInterval(interval);
  }, []);

  return { progress, connected };
}