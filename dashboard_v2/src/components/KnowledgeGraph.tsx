import React, { useMemo, useState } from 'react';
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
import { getKnowledgeGraph, runReindex } from '../api/dashboardApi';
import { FiShare2, FiDatabase, FiFileText, FiCode } from 'react-icons/fi';
import toast from 'react-hot-toast';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';

const nodeGradients: Record<string, string> = {
  agent: 'from-blue-400 to-blue-600',
  file: 'from-emerald-400 to-emerald-600',
  concept: 'from-purple-400 to-purple-600',
};

const nodeIcons: Record<string, React.ReactNode> = {
  agent: <FiCode className="text-lg text-white" />,
  file: <FiFileText className="text-lg text-white" />,
  concept: <FiDatabase className="text-lg text-white" />,
};

function KnowledgeGraphNode({ data }: any) {
  const gradient = nodeGradients[data.nodeType] || 'from-zora-gray to-zora-gray/50';
  const icon = nodeIcons[data.nodeType] || <FiDatabase className="text-lg text-white" />;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-card/50 border border-border/50 shadow-lg transition-all duration-200 hover:shadow-[0_0_16px_rgba(255,140,66,0.3)]">
      <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center shrink-0`}>
        {icon}
      </div>
      <div className="font-semibold text-xs text-foreground">{data.label}</div>
    </div>
  );
}

const nodeTypes = { knowledgeNode: KnowledgeGraphNode };

export default function KnowledgeGraph() {
  const [indexing, setIndexing] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['knowledgeGraph'],
    queryFn: getKnowledgeGraph,
    refetchInterval: 60_000,
  });

  const handleReindex = async () => {
    try {
      setIndexing(true);
      const result = await runReindex('incremental');
      if (result.success) {
        toast.success('Индексация запущена');
        setTimeout(() => refetch(), 5000);
      } else {
        toast.error(result.message || 'Ошибка индексации');
      }
    } catch (e: any) {
      toast.error(e.message || 'Ошибка сети');
    } finally {
      setIndexing(false);
    }
  };

  const { nodes, edges } = useMemo(() => {
    const apiNodes = data?.nodes ?? [];
    const apiEdges = data?.edges ?? [];

    const flowNodes: Node[] = apiNodes.map((n: any, i: number) => ({
      id: n.id,
      type: 'knowledgeNode',
      position: {
        x: n.type === 'agent' ? 100 + (i % 4) * 200 : 600 + (i % 4) * 180,
        y: n.type === 'agent' ? Math.floor(i / 4) * 100 + 20 : Math.floor(i / 4) * 80 + 50,
      },
      data: { label: n.label, nodeType: n.type },
    }));

    const forwardEdges: Edge[] = apiEdges.map((e: any, i: number) => ({
      id: `kge-${i}`,
      source: e.source,
      target: e.target,
      animated: true,
      style: { stroke: '#3B82F6', strokeWidth: 1.5, strokeDasharray: '4 4' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#3B82F6' },
      label: e.type || 'использует',
      labelStyle: { fill: '#6B7280', fontSize: 9 },
    }));

    const reverseEdges: Edge[] = apiEdges
      .filter((e: any) => e.source.startsWith('agent:') || !e.source.startsWith('file:'))
      .map((e: any, i: number) => ({
        id: `kge-rev-${i}`,
        source: e.target,
        target: e.source,
        animated: false,
        style: { stroke: '#22C55E', strokeWidth: 1, strokeDasharray: '2 4', opacity: 0.6 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#22C55E' },
        label: 'используется агентом',
        labelStyle: { fill: '#6B7280', fontSize: 8, opacity: 0.6 },
      }));

    return { nodes: flowNodes, edges: [...forwardEdges, ...reverseEdges] };
  }, [data]);

  const isEmpty = !data?.nodes?.length;

  return (
    <Card className="h-full border-border bg-card/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FiShare2 className="text-zora-accent" />
            Граф знаний
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">
            {data?.nodes?.length ?? 0} узлов
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0 h-[280px]">
        {isLoading ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-muted-foreground text-sm">Загрузка графа знаний...</p>
          </div>
        ) : isEmpty ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 p-6">
            <p className="text-muted-foreground text-sm text-center">
              Нет связей. Запустите индексацию и выполните несколько запросов к агентам.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={handleReindex}
              disabled={indexing}
              className="text-xs border-border"
            >
              {indexing ? '⏳ Индексация...' : '▶ Запустить индексацию'}
            </Button>
          </div>
        ) : (
          <div className="h-full w-full relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              attributionPosition="bottom-left"
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#1A2536" gap={20} />
              <Controls />
              <MiniMap
                style={{
                  background: '#0C111D',
                  border: '1px solid #2A3A4E',
                  borderRadius: 12,
                  width: 100,
                  height: 80,
                }}
                position="bottom-right"
                nodeColor={(n) => (n.data as any)?.nodeType === 'agent' ? '#3B82F6' : '#22C55E'}
              />
            </ReactFlow>
            {/* Legend */}
            <div className="absolute bottom-2 left-2 flex gap-3 text-[9px] text-muted-foreground bg-card/80 px-2 py-1 rounded-lg border border-border z-10">
              <div className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500 inline-block" />
                Агенты
              </div>
              <div className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded bg-emerald-500 inline-block" />
                Файлы
              </div>
              <div className="flex items-center gap-1">
                <span className="w-3 h-0.5 bg-blue-400 inline-block" style={{ borderTop: '1px dashed #3B82F6' }} />
                Использует
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
