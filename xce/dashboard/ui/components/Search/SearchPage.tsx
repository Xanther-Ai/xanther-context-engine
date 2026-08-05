import React, { useState } from 'react';
import { useSearch } from '../../hooks/useSearch';

interface SearchPageProps {
  onSymbolSelect?: (symbolId: string, symbolName?: string) => void;
}

export default function SearchPage({ onSymbolSelect }: SearchPageProps) {
  const { results, loading, search, searchHistory } = useSearch();
  const [query, setQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState('');

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      search(query, selectedRepo || undefined);
    }
  };

  return (
    <div className="fade-in">
      <h2 style={{ marginBottom: '24px' }}>Search</h2>

      <div className="search-container">
        <form onSubmit={handleSearch}>
          <div className="search-input-wrapper">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              className="search-input"
              placeholder="Search your codebase..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          
          <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
            <select 
              className="input" 
              style={{ maxWidth: '200px' }}
              value={selectedRepo}
              onChange={e => setSelectedRepo(e.target.value)}
            >
              <option value="">All Repositories</option>
              {/* Add repository options dynamically */}
            </select>
            <button type="submit" className="btn btn-primary" disabled={loading || !query.trim()}>
              {loading ? 'Searching...' : 'Search'}
            </button>
          </div>
        </form>

        {results.length > 0 && (
          <div className="search-results">
            <div style={{ marginBottom: '16px', color: 'var(--text-muted)' }}>
              Found {results.length} results
            </div>
            {results.map((result: any, i: number) => (
              <div 
                key={i} 
                className="search-result"
                onClick={() => onSymbolSelect && onSymbolSelect(result.id || result.node_id, result.name)}
                style={{ cursor: onSymbolSelect ? 'pointer' : 'default' }}
              >
                <div className="search-result-header">
                  <span className="search-result-name">{result.name}</span>
                  <span className="search-result-score">{(result.score * 100).toFixed(0)}% match</span>
                </div>
                <div className="search-result-filepath">
                  {result.filepath}:{result.start_line}-{result.end_line}
                </div>
                <div className="search-result-snippet">
                  {result.snippet}
                </div>
              </div>
            ))}
          </div>
        )}

        {query && results.length === 0 && !loading && (
          <div className="empty-state">
            <div className="empty-state-icon">🔍</div>
            <div className="empty-state-title">No results found</div>
            <p>Try different keywords or add more repositories</p>
          </div>
        )}

        {!query && searchHistory.length > 0 && (
          <div className="card">
            <h3 className="card-title" style={{ marginBottom: '16px' }}>Recent Searches</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {searchHistory.map((item: any, i: number) => (
                <div 
                  key={i} 
                  style={{ 
                    padding: '8px 12px', 
                    background: 'var(--bg-tertiary)', 
                    borderRadius: '6px',
                    cursor: 'pointer'
                  }}
                  onClick={() => {
                    setQuery(item.query);
                    search(item.query);
                  }}
                >
                  <span style={{ color: 'var(--text-secondary)' }}>{item.query}</span>
                  <span style={{ float: 'right', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {item.result_count} results
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}