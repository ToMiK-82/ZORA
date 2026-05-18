import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAgents } from '../api/dashboardApi';
import { useWebSocket } from '../api/websocketProvider';
import { FiUsers, FiSearch } from 'react-icons/fi';
import type { AgentData } from '../types';

const stateColors: Record<string, string> = {
  running: 'text-zora-accent bg-zora-accent/10 border-l-zora-accent',
  idle: 'text-zora-green bg-zora-green/10 border-l-zora-green',
  unavailable: 'text-zora-red bg-zora-red/10 border-l-zora-red',
  error: 'text-zora-red bg-zora-red/10 border-l-zora-red',
};

const stateLabels: Record<string, string> = {
  running: 'Активен',
  idle: 'Ожидает',
  unavailable: 'Недоступен',
  error: 'Ошибка',
};

export default function AgentTable() {
  const { data, isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: getAgents,
    refetchInterval: 15_000,
  });
  const { agentStatuses } = useWebSocket();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const agents = useMemo(() => {
    if (!data?.agents) return [];
    return Object.entries(data.agents).map(([name, info]) => {
      // Override state from WebSocket if available
      const wsState = agentStatuses[name];
      const state = wsState || info.state;
      return { name, ...info, state };
    });
  }, [data, agentStatuses]);

  const filtered = useMemo(() => {
    return agents.filter(a => {
      if (statusFilter !== 'all' && a.state !== statusFilter) return false;
      if (search && !a.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [agents, search, statusFilter]);

  const statesCount = useMemo(() => {
    const counts: Record<string, number> = {};
    agents.forEach(a => { counts[a.state] = (counts[a.state] || 0) + 1; });
    return counts;
  }, [agents]);

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <p className="text-zora-muted">Загрузка агентов...</p>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiUsers className="text-zora-accent" />
        <h3>Агенты</h3>
        <span className="ml-auto text-xs text-zora-muted">
          {agents.filter(a => a.state === 'idle' || a.state === 'running').length}/{agents.length}
        </span>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-3">
        <div className="flex-1 relative">
          <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-zora-muted" />
          <input
            type="text"
            placeholder="Поиск агента..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-zora-bg border border-zora-border rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-zora-muted focus:outline-none focus:border-zora-accent"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="bg-zora-bg border border-zora-border rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-zora-accent"
        >
          <option value="all">Все</option>
          <option value="running">Активны</option>
          <option value="idle">Ожидают</option>
          <option value="unavailable">Недоступны</option>
        </select>
      </div>

      {/* Agent Cards */}
      <div className="flex-1 overflow-y-auto space-y-2">
        {filtered.map(agent => (
          <div
            key={agent.name}
            className={`flex items-center gap-3 p-3 rounded-xl border-l-4 bg-zora-bg/50 border-zora-border ${stateColors[agent.state] || 'border-l-zora-gray'}`}
          >
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm truncate">
                {agent.class || agent.name}
              </div>
              <div className="text-xs text-zora-muted truncate mt-0.5">
                {agent.current_task || '—'}
              </div>
            </div>
            <div className="text-right">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                agent.state === 'running' ? 'bg-zora-accent/20 text-zora-accent' :
                agent.state === 'idle' ? 'bg-zora-green/20 text-zora-green' :
                'bg-zora-red/20 text-zora-red'
              }`}>
                {stateLabels[agent.state] || agent.state}
              </span>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-zora-muted text-sm py-4">Нет агентов</p>
        )}
      </div>
    </div>
  );
}
