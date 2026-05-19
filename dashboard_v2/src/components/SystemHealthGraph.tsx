import React, { useMemo, useState, useCallback } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  NodeProps,
  Handle,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useQuery } from '@tanstack/react-query';
import { getSystemGraph } from '../api/dashboardApi';
import { FiServer, FiDatabase, FiCpu, FiGlobe, FiBox } from 'react-icons/fi';
import type { SystemGraphNode as SysNode } from '../types';

const iconMap: Record<string, React.ReactNode> = {
  orchestrator: <FiCpu className="text-lg" />,
  qdrant: <FiDatabase className="text-lg" />,
  ollama: <FiCpu className="text-lg" />,
  deepseek: <FiGlobe className="text-lg" />,
  postgres: <FiDatabase className="text-lg" />,
  web_ui: <FiGlobe className="text-lg" />,
  docker: <FiBox className="text-lg" />,
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

const statusDot: Record<string, string> = {
  healthy: 'bg-zora-green shadow-[0_0_4px_rgba(34,197,94,0.6)]',
  degraded: 'bg-zora-yellow shadow-[0_0_4px_rgba(245,158,11,0.6)]',
  down: 'bg-zora-red shadow-[0_0_4px_rgba(239,68,68,0.6)]',
};

function SystemNode({ data }: NodeProps) {
  const node = data as unknown as SysNode;
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-xl border bg-zora-card transition-all duration-200 min-w-[140px] ${
        statusColors[node.status] || 'border-zora-border'
      } ${statusBg[node.status] || ''}`}
    >
      <div className="w-8 h-8 rounded-lg bg-zora-bg flex items-center justify-center text-zora-accent shrink-0">
        {iconMap[node.id] || <FiServer />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-xs truncate">{node.label}</div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`w-1.5 h-1.5 rounded-full ${statusDot[node.status] || 'bg-zora-gray'}`} />
          <span className="text-[10px] text-zora-muted capitalize">{node.status}</span>
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { systemNode: SystemNode };

const initialPositions: Record<string, { x: number; y: number }> = {
  orchestrator: { x: 250, y: 0 },
  qdrant: { x: 0, y: 120 },
  ollama: { x: 250, y: 120 },
  deepseek: { x: 500, y: 120 },
  postgres: { x: 0, y: 240 },
  web_ui: { x: 250, y: 240 },
  docker: { x: 500, y: 240 },
};

export default function SystemHealthGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['systemGraph'],
    queryFn: getSystemGraph,
    refetchInterval: 30_000,
  });

  const [selectedNode, setSelectedNode] = useState<SysNode | null>(null);

  const { nodes: flowNodes, edges: flowEdges } = useMemo(() => {
    const apiNodes = data?.nodes ?? [];
    const apiEdges = data?.edges ?? [];

    const nodes: Node[] = apiNodes.map((n) => ({
      id: n.id,
      type: 'systemNode',
      position: initialPositions[n.id] || { x: 250, y: 120 },
      data: n as any,
    }));

    const edges: Edge[] = apiEdges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      style: { stroke: '#2A3A4E', strokeWidth: 1.5 },
      labelStyle: { fill: '#6B7280', fontSize: 10 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#2A3A4E' },
    }));

    return { nodes, edges };
  }, [data]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode((prev) =>
        prev?.id === node.id ? null : (node.data as unknown as SysNode)
      );
    },
    []
  );

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

      <div className="flex-1" style={{ minHeight: 0 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1A2536" gap={20} />
          <Controls className="!bg-zora-card !border-zora-border !rounded-xl" />
          <MiniMap
            style={{ background: '#0C111D', border: '1px solid #2A3A4E', borderRadius: 12 }}
            nodeColor={(n) => {
              const s = (n.data as unknown as SysNode)?.status;
              return s === 'healthy' ? '#22C55E' : s === 'degraded' ? '#F59E0B' : '#EF4444';
            }}
          />
        </ReactFlow>
      </div>

      {/* Tooltip */}
      {selectedNode && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm">{selectedNode.label}</span>
            <span className={`w-2 h-2 rounded-full ${statusDot[selectedNode.status] || 'bg-zora-gray'}`} />
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
