import React, { useState, useEffect } from 'react';
import { useSettings } from '../../hooks/useSettings';

export default function SettingsPanel() {
  const { settings, loading, saveSettings, resetSettings } = useSettings();
  const [formData, setFormData] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setFormData(settings);
    }
  }, [settings]);

  const handleChange = (key: string, value: any) => {
    setFormData((prev: any) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveSettings(formData);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      alert('Failed to save settings');
    }
    setSaving(false);
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
      <h2 style={{ marginBottom: '24px' }}>Settings</h2>

      <div className="card">
        <h3 className="card-title" style={{ marginBottom: '20px' }}>Neo4j Connection</h3>
        
        <div className="input-group">
          <label className="input-label">Neo4j URI</label>
          <input
            type="text"
            className="input"
            value={formData.neo4j_uri || ''}
            onChange={e => handleChange('neo4j_uri', e.target.value)}
            placeholder="bolt://localhost:7687"
          />
        </div>

        <div className="input-group">
          <label className="input-label">Neo4j Username</label>
          <input
            type="text"
            className="input"
            value={formData.neo4j_user || ''}
            onChange={e => handleChange('neo4j_user', e.target.value)}
            placeholder="neo4j"
          />
        </div>

        <div className="input-group">
          <label className="input-label">Neo4j Password</label>
          <input
            type="password"
            className="input"
            value={formData.neo4j_password || ''}
            onChange={e => handleChange('neo4j_password', e.target.value)}
            placeholder="••••••••"
          />
        </div>
      </div>

      <div className="card">
        <h3 className="card-title" style={{ marginBottom: '20px' }}>Embedding Settings</h3>
        
        <div className="input-group">
          <label className="input-label">Embedding Model</label>
          <select
            className="input"
            value={formData.embedding_model || ''}
            onChange={e => handleChange('embedding_model', e.target.value)}
          >
            <option value="amazon.titan-embed-text-v1">Amazon Titan Text Embedding</option>
            <option value="openai/text-embedding-3-small">OpenAI text-embedding-3-small</option>
            <option value="cohere/embed-multilingual-v3.0">Cohere Multilingual</option>
          </select>
        </div>

        <div className="input-group">
          <label className="input-label">Embedding Dimensions</label>
          <select
            className="input"
            value={formData.embedding_dimensions || 1536}
            onChange={e => handleChange('embedding_dimensions', parseInt(e.target.value))}
          >
            <option value={256}>256</option>
            <option value={512}>512</option>
            <option value={768}>768</option>
            <option value={1024}>1024</option>
            <option value={1536}>1536</option>
            <option value={2048}>2048</option>
          </select>
        </div>

        <div className="input-group">
          <label className="input-label">Batch Size</label>
          <input
            type="number"
            className="input"
            value={formData.batch_size || 100}
            onChange={e => handleChange('batch_size', parseInt(e.target.value))}
            min={1}
            max={1000}
          />
        </div>
      </div>

      <div className="card">
        <h3 className="card-title" style={{ marginBottom: '20px' }}>Server Settings</h3>
        
        <div className="input-group">
          <label className="input-label">Dashboard Port</label>
          <input
            type="number"
            className="input"
            value={formData.server_port || 8080}
            onChange={e => handleChange('server_port', parseInt(e.target.value))}
            min={1}
            max={65535}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : saved ? '✓ Saved!' : 'Save Settings'}
        </button>
        <button className="btn btn-secondary" onClick={resetSettings}>
          Reset to Defaults
        </button>
      </div>
    </div>
  );
}