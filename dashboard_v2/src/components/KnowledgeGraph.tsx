import React, { useMemo } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useQuery } from '@tanstack/react-query';
import { getKnowledgeGraph } from '../api/dashboardApi';
import { FiShare2 } from 'react-icons/fi';

export default function KnowledgeGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['knowledgeGraph'],
    queryFn: getKnowledgeGraph,
    refetchInterval: 60_000,
  });

  const { nodes, edges } = useMemo(() => {
    const apiNodes = data?.nodes ?? [];
    const apiEdges = data?.edges ?? [];

    const flowNodes: Node[] = apiNodes.map((n: any, i: number) => ({
      id: n.id,
      type: 'default',
      position: {
        x: n.type === 'agent' ? 100 + (i % 5) * 200 : 600 + (i % 5) * 180,
        y: n.type === 'agent' ? Math.floor(i / 5) * 120 : Math.floor(i / 5) * 80 + 50,
      },
      data: { label: n.label },
      style: {
        background: n.type === 'agent' ? '#1A3A5C' : '#2A4A3C',
        color: '#fff',
        border: n.type === 'agent' ? '2px solid #3B82F6' : '2px solid #22C55E',
        borderRadius: n.type === 'agent' ? '50%' : '8px',
        padding: '8px 12px',
        fontSize: '11px',
        minWidth: '80px',
        textAlign: 'center' as const,
      },
    }));

    // Прямые связи: agent → file
    const forwardEdges: Edge[] = apiEdges.map((e: any, i: number) => ({
      id: `kge-${i}`,
      source: e.source,
      target: e.target,
      animated: true,
      style: {
        stroke: '#3B82F6',
        strokeWidth: 1.5,
        strokeDasharray: '4 4',
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#3B82F6',
      },
      label: e.type || 'использует',
      labelStyle: { fill: '#6B7280', fontSize: 9 },
    }));

    // Обратные связи: file → agent (кто использует этот файл)
    const reverseEdges: Edge[] = apiEdges
      .filter((e: any) => e.source.startsWith('agent:') || !e.source.startsWith('file:'))
      .map((e: any, i: number) => ({
        id: `kge-rev-${i}`,
        source: e.target,
        target: e.source,
        animated: false,
        style: {
          stroke: '#22C55E',
          strokeWidth: 1,
          strokeDasharray: '2 4',
          opacity: 0.6,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#22C55E',
        },
        label: 'используется агентом',
        labelStyle: { fill: '#6B7280', fontSize: 8, opacity: 0.6 },
      }));

    const flowEdges = [...forwardEdges, ...reverseEdges];

    return { nodes: flowNodes, edges: flowEdges };
  }, [data]);

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <p className="text-zora-muted">Загрузка графа знаний...</p>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiShare2 className="text-zora-accent" />
        <h3>Граф знаний</h3>
        <span className="ml-auto text-xs text-zora-muted">
          {data?.nodes?.length ?? 0} узлов
        </span>
      </div>

      <div className="flex-1" style={{ minHeight: 0 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          attributionPosition="bottom-left"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1A2536" gap={20} />
          <Controls className="!bg-zora-card !border-zora-border !rounded-xl" />
          <MiniMap
            style={{ background: '#0C111D', border: '1px solid #2A3A4E', borderRadius: 12 }}
            nodeColor={(n) =>
              (n.data as any)?.type === 'agent' ? '#3B82F6' : '#22C55E'
            }
          />
        </ReactFlow>
      </div>

      {/* Легенда */}
      <div className="mt-2 flex gap-4 text-[10px] text-zora-muted">
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-full bg-blue-500 inline-block" />
          Агенты
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-green-500 inline-block" />
          Файлы
        </div>
        <div className="flex items-center gap-1">
          <span className="w-4 h-0.5 bg-blue-400 inline-block" style={{ borderTop: '1px dashed #3B82F6' }} />
          Использует
        </div>
      </div>
    </div>
  );
}
