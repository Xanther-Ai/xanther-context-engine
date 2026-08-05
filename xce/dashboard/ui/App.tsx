import React, { useState, useEffect } from 'react';
import Sidebar from './components/Layout/Sidebar';
import Header from './components/Layout/Header';
import Home from './components/Dashboard/Home';
import Repositories from './components/Dashboard/Repositories';
import GraphExplorer from './components/Graph/GraphExplorer';
import CallersCallees from './components/Graph/CallersCallees';
import ImpactAnalysis from './components/Graph/ImpactAnalysis';
import ArchitectureView from './components/Dashboard/ArchitectureView';
import SearchPage from './components/Search/SearchPage';
import TraceabilityPanel from './components/Search/TraceabilityPanel';
import SettingsPanel from './components/Settings/SettingsPanel';
import ProgressOverlay from './components/Progress/ProgressOverlay';
import { useProgress } from './hooks/useProgress';

type Page = 'home' | 'repositories' | 'graph' | 'callers' | 'impact' | 'traceability' | 'architecture' | 'search' | 'settings';

// Symbol Selector - shown when user needs to select a symbol first
interface SymbolSelectorProps {
  title: string;
  description: string;
  onSelect: (symbolId: string, symbolName?: string) => void;
  onNavigateToGraph: () => void;
}

function SymbolSelector({ title, description, onSelect, onNavigateToGraph }: SymbolSelectorProps) {
  const [symbolId, setSymbolId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (symbolId.trim()) {
      onSelect(symbolId.trim());
    }
  };

  return (
    <div className="fade-in">
      <h2 style={{ marginBottom: '24px' }}>{title}</h2>
      
      <div className="card">
        <div className="empty-state" style={{ padding: '40px 20px' }}>
          <div className="empty-state-icon">🔍</div>
          <div className="empty-state-title">{title}</div>
          <p>{description}</p>
        </div>
        
        <form onSubmit={handleSubmit} style={{ marginTop: '24px' }}>
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <input
              type="text"
              className="input"
              placeholder="Enter symbol ID or name..."
              value={symbolId}
              onChange={(e) => setSymbolId(e.target.value)}
              style={{ flex: 1, minWidth: '200px' }}
            />
            <button type="submit" className="btn btn-primary" disabled={!symbolId.trim()}>
              Analyze
            </button>
            <button type="button" className="btn btn-secondary" onClick={onNavigateToGraph}>
              Select from Graph
            </button>
          </div>
        </form>
        
        {error && (
          <div style={{ marginTop: '16px', color: 'var(--error)', fontSize: '0.875rem' }}>
            {error}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: '24px' }}>
        <h3 className="card-title">Quick Tips</h3>
        <ul style={{ marginTop: '12px', paddingLeft: '20px', color: 'var(--text-secondary)' }}>
          <li>Select a symbol from the Graph Explorer to analyze its relationships</li>
          <li>Use the search functionality to find symbols by name</li>
          <li>Click on any node in the graph to view its details and run analysis</li>
        </ul>
      </div>
    </div>
  );
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('home');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const { progress, connected } = useProgress();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // State for selected symbol (shared across analysis panels)
  const [selectedSymbolId, setSelectedSymbolId] = useState<string | null>(null);
  const [selectedSymbolName, setSelectedSymbolName] = useState<string | null>(null);

  const handleSymbolSelect = (symbolId: string, symbolName?: string) => {
    setSelectedSymbolId(symbolId);
    if (symbolName) {
      setSelectedSymbolName(symbolName);
    }
  };

  const clearSymbolSelection = () => {
    setSelectedSymbolId(null);
    setSelectedSymbolName(null);
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'home': 
        return <Home />;
      case 'repositories': 
        return <Repositories />;
      case 'graph': 
        return <GraphExplorer onSymbolSelect={handleSymbolSelect} />;
      case 'callers': 
        return selectedSymbolId ? (
          <div className="analysis-panel">
            <div className="panel-header-with-back">
              <button className="btn btn-ghost" onClick={clearSymbolSelection}>← Back</button>
              <div className="selected-symbol-info">
                <span className="selected-symbol-label">Analyzing:</span>
                <span className="selected-symbol-name">{selectedSymbolName || selectedSymbolId}</span>
              </div>
            </div>
            <CallersCallees symbolId={selectedSymbolId} onNavigate={handleSymbolSelect} />
          </div>
        ) : (
          <SymbolSelector 
            title="Callers/Callees Analysis" 
            description="Select a symbol from the Graph Explorer to analyze its call chain"
            onSelect={handleSymbolSelect}
            onNavigateToGraph={() => setCurrentPage('graph')}
          />
        );
      case 'impact': 
        return selectedSymbolId ? (
          <div className="analysis-panel">
            <div className="panel-header-with-back">
              <button className="btn btn-ghost" onClick={clearSymbolSelection}>← Back</button>
              <div className="selected-symbol-info">
                <span className="selected-symbol-label">Analyzing:</span>
                <span className="selected-symbol-name">{selectedSymbolName || selectedSymbolId}</span>
              </div>
            </div>
            <ImpactAnalysis symbolId={selectedSymbolId} onNavigate={handleSymbolSelect} />
          </div>
        ) : (
          <SymbolSelector 
            title="Impact Analysis" 
            description="Select a symbol to view its impact on dependent files and test coverage"
            onSelect={handleSymbolSelect}
            onNavigateToGraph={() => setCurrentPage('graph')}
          />
        );
      case 'traceability': 
        return selectedSymbolId ? (
          <div className="analysis-panel">
            <div className="panel-header-with-back">
              <button className="btn btn-ghost" onClick={clearSymbolSelection}>← Back</button>
              <div className="selected-symbol-info">
                <span className="selected-symbol-label">Tracing:</span>
                <span className="selected-symbol-name">{selectedSymbolName || selectedSymbolId}</span>
              </div>
            </div>
            <TraceabilityPanel symbolId={selectedSymbolId} onNavigate={handleSymbolSelect} />
          </div>
        ) : (
          <SymbolSelector 
            title="Traceability" 
            description="Select a symbol to view its requirements links, tests, and architecture context"
            onSelect={handleSymbolSelect}
            onNavigateToGraph={() => setCurrentPage('graph')}
          />
        );
      case 'architecture':
        return <ArchitectureView onSymbolSelect={handleSymbolSelect} />;
      case 'search': 
        return <SearchPage onSymbolSelect={handleSymbolSelect} />;
      case 'settings': 
        return <SettingsPanel />;
      default: 
        return <Home />;
    }
  };

  const hasActiveProgress = progress && progress.length > 0;

  return (
    <div className="app-container">
      <Sidebar 
        isOpen={sidebarOpen} 
        currentPage={currentPage} 
        onNavigate={setCurrentPage} 
      />
      <div className={`main-content ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
        <Header 
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          theme={theme}
          onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        />
        <main className="page-content">
          {renderPage()}
        </main>
      </div>
      {hasActiveProgress && <ProgressOverlay progress={progress} />}
      
      {/* Global styles for new components */}
      <style>{`
        .analysis-panel {
          padding: 0;
        }
        
        .panel-header-with-back {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 24px;
        }
        
        .selected-symbol-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        
        .selected-symbol-label {
          font-size: 0.875rem;
          color: var(--text-muted);
        }
        
        .selected-symbol-name {
          font-weight: 600;
          color: var(--accent);
        }
        
        .btn-ghost {
          background: transparent;
          border: 1px solid var(--border-color);
          color: var(--text-secondary);
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s;
        }
        
        .btn-ghost:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }
      `}</style>
    </div>
  );
}