import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080';

export function useSettings() {
  const [settings, setSettings] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/settings`);
      const data = await res.json();
      setSettings(data);
    } catch (err) {
      console.error('Failed to fetch settings:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const saveSettings = async (newSettings: any) => {
    const res = await fetch(`${API_BASE}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSettings)
    });
    if (!res.ok) throw new Error('Failed to save settings');
    await refresh();
  };

  const resetSettings = async () => {
    // Reset to defaults by saving empty/defaults
    await saveSettings({
      neo4j_uri: 'bolt://localhost:7687',
      neo4j_user: 'neo4j',
      neo4j_password: '',
      embedding_model: 'amazon.titan-embed-text-v1',
      embedding_dimensions: 1536,
      batch_size: 100,
      server_port: 8080,
      auth_enabled: false
    });
  };

  return { settings, loading, saveSettings, resetSettings };
}