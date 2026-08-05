import React from 'react';

interface SidebarProps {
  isOpen: boolean;
  currentPage: string;
  onNavigate: (page: any) => void;
}

const navItems = [
  { id: 'home', label: 'Home', icon: '🏠' },
  { id: 'repositories', label: 'Repositories', icon: '📁' },
  { id: 'graph', label: 'Graph Explorer', icon: '🕸️' },
  { id: 'callers', label: 'Callers/Callees', icon: '🔗' },
  { id: 'impact', label: 'Impact Analysis', icon: '📊' },
  { id: 'traceability', label: 'Traceability', icon: '🔍' },
  { id: 'architecture', label: 'Architecture', icon: '🏗️' },
  { id: 'search', label: 'Search', icon: '🔎' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
];

export default function Sidebar({ isOpen, currentPage, onNavigate }: SidebarProps) {
  if (!isOpen) return null;

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>🧠 XCE Dashboard</h1>
      </div>
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <div
            key={item.id}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </div>
        ))}
      </nav>
      <div style={{ padding: '16px', borderTop: '1px solid var(--border-color)' }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          <div>Neo4j: bolt://localhost:7687</div>
          <div>Status: Connected</div>
        </div>
      </div>
    </aside>
  );
}