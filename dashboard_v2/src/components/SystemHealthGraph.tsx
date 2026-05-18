import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSystemGraph } from '../api/dashboardApi';
import { FiServer, FiDatabase, FiCpu, FiGlobe } from 'react-icons/fi';
import type { SystemGraphNode } from '../types';

const iconMap: Record<string, React.ReactNode> = {
  orchestrator: <FiCpu className="text-lg" />,
  qdrant: <FiDatabase className="text-lg" />,
  ollama: <FiCpu className="text-lg" />,
  web_ui: <FiGlobe className="text-lg" />,
  docker: <FiServer className="text-lg" />,
};

const statusColors: Record<string, string> = {
  healthy: 'border-zora-green shadow-[0_0_8px_rgba(34,197,94,0.3)]',
  degraded: 'border-zora-yellow shadow-[0_0_8px_rgba(245,158,11,0.3)]',
  down: 'border-zora-red shadow-[0_0_8px_rgba(239,68,68,0.3)]',
};

const statusBg: Record<string, string> = {
  healthy: 'bg-zora-green/10',
  degraded: 'bg-zora-yellow/10',
  down: 'bg-zora-red/10',
};

export default function SystemHealthGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['systemGraph'],
    queryFn: getSystemGraph,
    refetchInterval: 30_000,
  });

  const [selectedNode, setSelectedNode] = useState<SystemGraphNode | null>(null);

  const nodes = data?.nodes ?? [];

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <p className="text-zora-muted">Загрузка графа...</p>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiServer className="text-zora-accent" />
        <h3>Граф компонентов</h3>
      </div>

      <div className="flex-1 grid grid-cols-2 gap-3 auto-rows-min content-start">
        {nodes.map((node) => (
          <button
            key={node.id}
            onClick={() => setSelectedNode(selectedNode?.id === node.id ? null : node)}
            className={`
              flex items-center gap-3 p-3 rounded-xl border transition-all duration-200
              ${statusColors[node.status] || 'border-zora-border'}
              ${statusBg[node.status] || 'bg-zora-card'}
              hover:bg-zora-border/50 cursor-pointer text-left
              ${selectedNode?.id === node.id ? 'ring-2 ring-zora-accent' : ''}
            `}
          >
            <div className="w-10 h-10 rounded-lg bg-zora-bg flex items-center justify-center text-zora-accent">
              {iconMap[node.id] || <FiServer />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm truncate">{node.label}</div>
              <div className="flex items-center gap-2 mt-1">
                <span className={`status-dot ${node.status}`} />
                <span className="text-xs text-zora-muted capitalize">{node.status}</span>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Tooltip */}
      {selectedNode && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm">{selectedNode.label}</span>
            <span className={`status-dot ${selectedNode.status}`} />
          </div>
          {selectedNode.metrics && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(selectedNode.metrics).map(([key, val]) => (
                <div key={key}>
                  <span className="text-zora-muted">{key}: </span>
                  <span className="text-white font-medium">
                    {typeof val === 'number' ? val.toFixed(2) : val}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
