import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getHealth, getZoraStatus } from '../api/dashboardApi';
import { useWebSocket } from '../api/websocketProvider';
import { FiCpu, FiActivity, FiExternalLink } from 'react-icons/fi';

export default function TopBar() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth });
  const { data: zoraStatus } = useQuery({ queryKey: ['zoraStatus'], queryFn: getZoraStatus });
  const { connected, lastUpdate } = useWebSocket();

  const healthScore = health?.health_score ?? 0;
  const healthColor = healthScore >= 80 ? 'text-zora-green' : healthScore >= 50 ? 'text-zora-yellow' : 'text-zora-red';

  return (
    <header className="flex items-center justify-between px-6 py-4 bg-zora-card border-b border-zora-border">
      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-zora-accent to-zora-accent-light flex items-center justify-center font-extrabold text-zora-bg text-lg">
          Z
        </div>
        <div>
          <h1 className="text-xl font-bold bg-gradient-to-r from-zora-accent to-zora-accent-light bg-clip-text text-transparent">
            ZORA Dashboard
          </h1>
          <p className="text-xs text-zora-muted">Мониторинг системы</p>
        </div>
      </div>

      {/* Health Score */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <FiActivity className={`text-lg ${healthColor}`} />
          <span className={`font-bold text-lg ${healthColor}`}>{healthScore}</span>
          <span className="text-xs text-zora-muted">/ 100</span>
        </div>

        {/* WS Status */}
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-zora-green' : 'bg-zora-red'}`} />
          <span className="text-xs text-zora-muted">
            {connected ? 'Live' : 'Offline'}
          </span>
        </div>

        {/* Last Update */}
        <span className="text-xs text-zora-muted">
          {lastUpdate ? `🕐 ${lastUpdate}` : '—'}
        </span>

        {/* Nav Links */}
        <div className="flex items-center gap-2">
          <a
            href="/modern"
            className="btn btn-ghost text-xs flex items-center gap-1"
          >
            <FiExternalLink /> Ria IDE
          </a>
          <a
            href="/user"
            className="btn btn-ghost text-xs flex items-center gap-1"
          >
            <FiExternalLink /> Чат
          </a>
        </div>
      </div>
    </header>
  );
}
