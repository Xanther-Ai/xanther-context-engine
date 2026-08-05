import React from 'react';

interface HeaderProps {
  onToggleSidebar: () => void;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
}

export default function Header({ onToggleSidebar, theme, onToggleTheme }: HeaderProps) {
  return (
    <header className="header">
      <div className="header-left">
        <button className="menu-button" onClick={onToggleSidebar}>
          ☰
        </button>
        <span style={{ fontWeight: 600 }}>XCE Local Dashboard</span>
      </div>
      <div className="header-right">
        <button className="theme-toggle" onClick={onToggleTheme}>
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </div>
    </header>
  );
}