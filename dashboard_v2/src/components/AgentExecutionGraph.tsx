import React, { useMemo, useState, useCallback, useEffect } from 'react';
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
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useQuery } from '@tanstack/react-query';
import { getAgentsGraph, getKnowledgeGraph } from '../api/dashboardApi';
import { useWebSocket } from '../api/websocketProvider';
import { FiUsers, FiSearch, FiUser, FiCpu, FiClock, FiCode, FiFileText } from 'react-icons/fi';
import type { AgentGraphNode, AgentGraphEdge, TraceData, WsExecutionTrace } from '../types';

const stateColors: Record<string, string> = {
  running: 'border-zora-accent shadow-[0_0_8px_rgba(255,140,66,0.3)]',
  idle: 'border-zora-green shadow-[0_0_8px_rgba(34,197,94,0.3)]',
  healthy: 'border-zora-green shadow-[0_0_8px_rgba(34,197,94,0.3)]',
  down: 'border-zora-red shadow-[0_0_8px_rgba(239,68,68,0.3)]',
  unavailable: 'border-zora-red shadow-[0_0_8px_rgba(239,68,68,0.3)]',
  error: 'border-zora-red shadow-[0_0_8px_rgba(239,68,68,0.3)]',
};

const stateBg: Record<string, string> = {
  running: 'bg-zora-accent/10',
  idle: 'bg-zora-green/10',
  healthy: 'bg-zora-green/10',
  down: 'bg-zora-red/10',
  unavailable: 'bg-zora-red/10',
  error: 'bg-zora-red/10',
};

const stateDot: Record<string, string> = {
  running: 'bg-zora-accent shadow-[0_0_4px_rgba(255,140,66,0.6)]',
  idle: 'bg-zora-green shadow-[0_0_4px_rgba(34,197,94,0.6)]',
  healthy: 'bg-zora-green shadow-[0_0_4px_rgba(34,197,94,0.6)]',
  down: 'bg-zora-red shadow-[0_0_4px_rgba(239,68,68,0.6)]',
  unavailable: 'bg-zora-red shadow-[0_0_4px_rgba(239,68,68,0.6)]',
  error: 'bg-zora-red shadow-[0_0_4px_rgba(239,68,68,0.6)]',
};

const stateLabels: Record<string, string> = {
  running: 'Активен',
  idle: 'Ожидает',
  healthy: 'Здоров',
  down: 'Недоступен',
  unavailable: 'Недоступен',
  error: 'Ошибка',
};

// Кастомный узел для оркестратора
function OrchestratorNode({ data }: NodeProps) {
  const node = data as unknown as AgentGraphNode;
  return (
    <div
      className={`flex items-center gap-2 px-4 py-3 rounded-2xl border-2 bg-zora-card transition-all duration-200 min-w-[150px] ${
        stateColors[node.status] || 'border-zora-border'
      } ${stateBg[node.status] || ''}`}
    >
      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-zora-accent/20 to-zora-accent/5 flex items-center justify-center shrink-0">
        <FiCpu className="text-xl text-zora-accent" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-bold text-sm truncate">{node.label}</div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`w-2 h-2 rounded-full ${stateDot[node.status] || 'bg-zora-gray'}`} />
          <span className="text-[10px] text-zora-muted">{stateLabels[node.status] || node.status}</span>
        </div>
        {node.metrics && (
          <div className="text-[9px] text-zora-muted mt-0.5">
            Трассы: {node.metrics.active_traces ?? 0} | Агентов: {node.metrics.total_agents ?? 0}
          </div>
        )}
      </div>
    </div>
  );
}

// Кастомный узел для агентов
function AgentFlowNode({ data }: NodeProps) {
  const node = data as unknown as AgentGraphNode;
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-xl border bg-zora-card transition-all duration-200 min-w-[130px] ${
        stateColors[node.status] || 'border-zora-border'
      } ${stateBg[node.status] || ''}`}
    >
      <div className="w-8 h-8 rounded-lg bg-zora-bg flex items-center justify-center shrink-0 text-blue-400">
        <FiUser className="text-lg" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-xs truncate">{node.label}</div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`w-1.5 h-1.5 rounded-full ${stateDot[node.status] || 'bg-zora-gray'}`} />
          <span className="text-[10px] text-zora-muted">{stateLabels[node.status] || node.status}</span>
        </div>
      </div>
    </div>
  );
}

// Кастомный узел для User (зелёный)
function UserNode({ data }: NodeProps) {
  const node = data as unknown as AgentGraphNode;
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-zora-green/40 bg-zora-green/5 min-w-[100px]">
      <div className="w-8 h-8 rounded-lg bg-zora-green/10 flex items-center justify-center shrink-0">
        <FiUser className="text-lg text-zora-green" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-xs truncate">{node.label}</div>
        <div className="text-[10px] text-zora-muted">Пользователь</div>
      </div>
    </div>
  );
}

// Кастомный узел для Developer (синий)
function DeveloperNode({ data }: NodeProps) {
  const node = data as unknown as AgentGraphNode;
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-blue-400/40 bg-blue-400/5 min-w-[100px]">
      <div className="w-8 h-8 rounded-lg bg-blue-400/10 flex items-center justify-center shrink-0">
        <FiCode className="text-lg text-blue-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-xs truncate">{node.label}</div>
        <div className="text-[10px] text-zora-muted">Разработчик</div>
      </div>
    </div>
  );
}

const nodeTypes = {
  orchestratorNode: OrchestratorNode,
  agentNode: AgentFlowNode,
  userNode: UserNode,
  developerNode: DeveloperNode,
};

const agentPositions: Record<string, { x: number; y: number }> = {
  orchestrator: { x: 300, y: 0 },
  user: { x: 300, y: 200 },
  developer: { x: 600, y: 0 },
  developer_assistant: { x: 0, y: 100 },
  inspector: { x: 150, y: 100 },
  logistician: { x: 300, y: 100 },
  accountant: { x: 450, y: 100 },
  economist: { x: 600, y: 100 },
  purchaser: { x: 0, y: 200 },
  sales_consultant: { x: 150, y: 200 },
  support: { x: 300, y: 200 },
  smm: { x: 450, y: 200 },
  website: { x: 600, y: 200 },
};

type TimeRange = 'now' | '1h' | 'today';

export default function AgentExecutionGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['agentsGraph'],
    queryFn: getAgentsGraph,
    refetchInterval: 10_000,
  });
  const { agentStatuses, executionTraces } = useWebSocket();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedAgent, setSelectedAgent] = useState<AgentGraphNode | null>(null);
  const [showOnlyActive, setShowOnlyActive] = useState(false);
  const [liveTraces, setLiveTraces] = useState<WsExecutionTrace['data'][]>([]);
  const [timeRange, setTimeRange] = useState<TimeRange>('now');
  const [viewMode, setViewMode] = useState<'graph' | 'table'>('graph');

  // Knowledge Graph (связи агент–файл)
  const { data: kgData } = useQuery({
    queryKey: ['knowledgeGraph'],
    queryFn: getKnowledgeGraph,
    refetchInterval: 60_000,
    enabled: selectedAgent !== null,
  });

  // Обновляем живые трейсы из WebSocket
  useEffect(() => {
    if (executionTraces.length > 0) {
      setLiveTraces(prev => {
        const combined = [...executionTraces, ...prev];
        return combined.slice(0, 50);
      });
    }
  }, [executionTraces]);

  // TTL: авто-исчезновение завершённых трасс через 5 секунд
  useEffect(() => {
    const completedIds = executionTraces
      .filter(t => t.status === 'completed' || (t as any).event === 'trace_completed')
      .map(t => t.run_id);
    if (completedIds.length === 0) return;
    const timer = setTimeout(() => {
      setLiveTraces(prev => prev.filter(t => !completedIds.includes(t.run_id)));
    }, 5000);
    return () => clearTimeout(timer);
  }, [executionTraces]);

  // TTL для исторических трасс: удаляем трассы старше 30 секунд
  useEffect(() => {
    if (liveTraces.length === 0) return;
    const now = Date.now();
    const ttl = 30_000; // 30 секунд
    setLiveTraces(prev => prev.filter(t => {
      const ts = t.started_at || t.steps?.[0]?.timestamp || 0;
      return (now - ts) < ttl;
    }));
  }, [liveTraces.length > 0 && Date.now()]);

  // Определяем активных агентов из трейсов
  const activeAgentIds = useMemo(() => {
    const traces = data?.active_traces ?? [];
    const ids = new Set<string>();
    traces.forEach((t: TraceData) => {
      t.steps.forEach((s) => ids.add(s));
    });
    liveTraces.forEach((t) => {
      if (t.steps) {
        t.steps.forEach((s) => ids.add(s.agent));
      }
    });
    return ids;
  }, [data, liveTraces]);

  // Фильтрация по времени
  const filteredTraces = useMemo(() => {
    const traces = data?.active_traces ?? [];
    if (timeRange === 'now') return traces;
    const now = Date.now();
    const cutoff = timeRange === '1h' ? now - 3600_000 : now - 86400_000;
    return traces.filter((t) => t.started_at >= cutoff);
  }, [data, timeRange]);

  // Собираем used_files для выбранного агента
  const agentUsedFiles = useMemo(() => {
    if (!selectedAgent || !kgData?.nodes) return [];
    const agentId = selectedAgent.id;
    const fileNodes = kgData.nodes.filter((n: any) => n.type === 'file');
    const fileIds = new Set<string>();
    (kgData.edges || []).forEach((e: any) => {
      if (e.source === agentId && e.target.startsWith('file:')) {
        fileIds.add(e.target);
      }
    });
    return fileNodes
      .filter((n: any) => fileIds.has(n.id))
      .map((n: any) => n.label || n.id);
  }, [selectedAgent, kgData]);

  const { nodes: flowNodes, edges: flowEdges } = useMemo(() => {
    const apiNodes = data?.nodes ?? [];
    const apiEdges = data?.edges ?? [];

    // Добавляем узлы User и Developer, если их нет
    const hasUser = apiNodes.some((n) => n.id === 'user');
    const hasDeveloper = apiNodes.some((n) => n.id === 'developer');
    const enrichedNodes = [...apiNodes];
    if (!hasUser) {
      enrichedNodes.push({
        id: 'user',
        label: 'Пользователь',
        type: 'user' as const,
        status: 'healthy' as const,
      });
    }
    if (!hasDeveloper) {
      enrichedNodes.push({
        id: 'developer',
        label: 'Разработчик',
        type: 'developer' as const,
        status: 'healthy' as const,
      });
    }

    // Добавляем рёбра от User и Developer к оркестратору
    const enrichedEdges = [...apiEdges];
    if (!enrichedEdges.some((e) => e.source === 'user' && e.target === 'orchestrator')) {
      enrichedEdges.push({ source: 'user', target: 'orchestrator', label: 'запрос' });
    }
    if (!enrichedEdges.some((e) => e.source === 'developer' && e.target === 'orchestrator')) {
      enrichedEdges.push({ source: 'developer', target: 'orchestrator', label: 'отладка' });
    }

    // Фильтр
    let filteredNodes = enrichedNodes;
    if (search) {
      filteredNodes = filteredNodes.filter((n) =>
        n.label.toLowerCase().includes(search.toLowerCase())
      );
    }
    if (statusFilter !== 'all') {
      filteredNodes = filteredNodes.filter((n) => n.status === statusFilter);
    }
    if (showOnlyActive) {
      filteredNodes = filteredNodes.filter((n) => activeAgentIds.has(n.id));
    }

    const nodes: Node[] = filteredNodes.map((n) => {
      let nodeType = 'agentNode';
      if (n.type === 'orchestrator') nodeType = 'orchestratorNode';
      else if (n.type === 'user') nodeType = 'userNode';
      else if (n.type === 'developer') nodeType = 'developerNode';
      return {
        id: n.id,
        type: nodeType,
        position: agentPositions[n.id] || { x: 300, y: 150 },
        data: n as any,
      };
    });

    const edges: Edge[] = enrichedEdges.map((e, i) => {
      const isActive =
        activeAgentIds.has(e.source) || activeAgentIds.has(e.target);
      return {
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        animated: isActive,
        style: {
          stroke: isActive ? '#FF8C42' : '#2A3A4E',
          strokeWidth: isActive ? 2.5 : 1.5,
          strokeDasharray: isActive ? '5 5' : 'none',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isActive ? '#FF8C42' : '#2A3A4E',
        },
      };
    });

    return { nodes, edges };
  }, [data, search, statusFilter, activeAgentIds, showOnlyActive]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedAgent((prev) =>
        prev?.id === node.id ? null : (node.data as unknown as AgentGraphNode)
      );
    },
    []
  );

  const statesCount = useMemo(() => {
    const counts: Record<string, number> = {};
    (data?.nodes ?? []).forEach((n) => {
      counts[n.status] = (counts[n.status] || 0) + 1;
    });
    return counts;
  }, [data]);

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <p className="text-zora-muted">Загрузка графа агентов...</p>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiUsers className="text-zora-accent" />
        <h3>Граф агентов</h3>
        <span className="ml-auto text-xs text-zora-muted">
          {data?.nodes?.length ?? 0} агентов
        </span>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-3 flex-wrap">
        <div className="flex-1 relative min-w-[120px]">
          <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-zora-muted" />
          <input
            type="text"
            placeholder="Поиск агента..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-zora-bg border border-zora-border rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-zora-muted focus:outline-none focus:border-zora-accent"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-zora-bg border border-zora-border rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-zora-accent"
        >
          <option value="all">Все статусы</option>
          <option value="running">Активны</option>
          <option value="idle">Ожидают</option>
          <option value="unavailable">Недоступны</option>
        </select>
        <button
          onClick={() => setShowOnlyActive(!showOnlyActive)}
          className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
            showOnlyActive
              ? 'bg-zora-accent/20 border-zora-accent text-zora-accent'
              : 'bg-zora-bg border-zora-border text-zora-muted hover:text-white'
          }`}
        >
          <FiClock className="inline mr-1" />
          Только активные
        </button>
      </div>

      {/* View Mode Toggle + Time Range */}
      <div className="flex gap-1 mb-3 items-center">
        <button
          onClick={() => setViewMode('graph')}
          className={`px-2 py-1 rounded-lg text-xs border transition-colors ${
            viewMode === 'graph'
              ? 'bg-zora-accent/20 border-zora-accent text-zora-accent'
              : 'bg-zora-bg border-zora-border text-zora-muted hover:text-white'
          }`}
        >
          Граф
        </button>
        <button
          onClick={() => setViewMode('table')}
          className={`px-2 py-1 rounded-lg text-xs border transition-colors ${
            viewMode === 'table'
              ? 'bg-zora-accent/20 border-zora-accent text-zora-accent'
              : 'bg-zora-bg border-zora-border text-zora-muted hover:text-white'
          }`}
        >
          Таблица
        </button>
        <span className="w-px h-4 bg-zora-border mx-1" />
        {(['now', '1h', 'today'] as TimeRange[]).map((range) => (
          <button
            key={range}
            onClick={() => setTimeRange(range)}
            className={`px-2 py-1 rounded-lg text-xs border transition-colors ${
              timeRange === range
                ? 'bg-zora-accent/20 border-zora-accent text-zora-accent'
                : 'bg-zora-bg border-zora-border text-zora-muted hover:text-white'
            }`}
          >
            {range === 'now' ? 'Сейчас' : range === '1h' ? '1 час' : 'Сегодня'}
          </button>
        ))}
      </div>

      {/* View: Graph or Table */}
      {viewMode === 'graph' ? (
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
                const s = (n.data as unknown as AgentGraphNode)?.status;
                return s === 'running'
                  ? '#FF8C42'
                  : s === 'idle' || s === 'healthy'
                  ? '#22C55E'
                  : '#EF4444';
              }}
            />
          </ReactFlow>
        </div>
      ) : (
        <div className="flex-1 overflow-auto" style={{ minHeight: 0 }}>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-zora-muted border-b border-zora-border">
                <th className="text-left py-2 px-2">Агент</th>
                <th className="text-left py-2 px-2">Статус</th>
                <th className="text-left py-2 px-2">Тип</th>
                <th className="text-right py-2 px-2">Трассы</th>
              </tr>
            </thead>
            <tbody>
              {(data?.nodes ?? []).map((n) => (
                <tr
                  key={n.id}
                  onClick={() => setSelectedAgent((prev) => (prev?.id === n.id ? null : n))}
                  className={`border-b border-zora-border/50 cursor-pointer transition-colors hover:bg-zora-bg/50 ${
                    selectedAgent?.id === n.id ? 'bg-zora-accent/10' : ''
                  }`}
                >
                  <td className="py-2 px-2 font-medium text-white">{n.label}</td>
                  <td className="py-2 px-2">
                    <span className={`inline-flex items-center gap-1 ${
                      n.status === 'running' ? 'text-zora-accent' :
                      n.status === 'idle' || n.status === 'healthy' ? 'text-zora-green' :
                      'text-zora-red'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        n.status === 'running' ? 'bg-zora-accent' :
                        n.status === 'idle' || n.status === 'healthy' ? 'bg-zora-green' :
                        'bg-zora-red'
                      }`} />
                      {stateLabels[n.status] || n.status}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-zora-muted">{n.type}</td>
                  <td className="py-2 px-2 text-right text-zora-muted">
                    {n.metrics?.active_traces ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Active Traces Info */}
      {filteredTraces.length > 0 && (
        <div className="mt-2 p-2 rounded-xl bg-zora-accent/5 border border-zora-accent/20">
          <div className="text-xs font-semibold text-zora-accent mb-1">
            {timeRange === 'now' ? 'Активные' : 'Исторические'} трассы ({filteredTraces.length})
          </div>
          {filteredTraces.slice(0, 3).map((t: TraceData) => (
            <div key={t.run_id} className="text-[10px] text-zora-muted truncate">
              {t.query} → {t.steps.join(' → ')}
            </div>
          ))}
        </div>
      )}

      {/* Live Traces from WebSocket */}
      {liveTraces.length > 0 && (
        <div className="mt-2 p-2 rounded-xl bg-blue-500/5 border border-blue-500/20">
          <div className="text-xs font-semibold text-blue-400 mb-1">
            Живые трейсы (WS) ({liveTraces.length})
          </div>
          {liveTraces.slice(0, 3).map((t, i) => (
            <div key={i} className="text-[10px] text-zora-muted truncate">
              {t.query || 'запрос'} → {t.steps?.map(s => s.agent).join(' → ') || '...'}
            </div>
          ))}
        </div>
      )}

      {/* Detail Panel */}
      {selectedAgent && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-sm">{selectedAgent.label}</span>
            <span
              className={`px-2 py-0.5 rounded-full text-xs ${
                selectedAgent.status === 'running'
                  ? 'bg-zora-accent/20 text-zora-accent'
                  : selectedAgent.status === 'idle' || selectedAgent.status === 'healthy'
                  ? 'bg-zora-green/20 text-zora-green'
                  : 'bg-zora-red/20 text-zora-red'
              }`}
            >
              {stateLabels[selectedAgent.status] || selectedAgent.status}
            </span>
          </div>
          {selectedAgent.description && (
            <div className="text-zora-muted">{selectedAgent.description}</div>
          )}
          {selectedAgent.current_task && (
            <div>
              <span className="text-zora-muted">Текущая задача: </span>
              {selectedAgent.current_task}
            </div>
          )}
          {selectedAgent.metrics && (
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(selectedAgent.metrics).map(([key, val]) => (
                <div key={key}>
                  <span className="text-zora-muted">{key}: </span>
                  <span className="text-white font-medium">
                    {typeof val === 'number' ? val.toFixed(2) : val}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Used Files Section (Knowledge Graph) */}
          {agentUsedFiles.length > 0 && (
            <div className="mt-2 pt-2 border-t border-zora-border">
              <div className="flex items-center gap-1 text-zora-muted mb-1">
                <FiFileText className="text-xs" />
                <span className="font-semibold text-xs">Используемые файлы ({agentUsedFiles.length})</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {agentUsedFiles.slice(0, 10).map((file, i) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 rounded bg-zora-accent/10 text-zora-accent text-[10px] truncate max-w-[150px]"
                    title={file}
                  >
                    {file}
                  </span>
                ))}
                {agentUsedFiles.length > 10 && (
                  <span className="text-[10px] text-zora-muted">+{agentUsedFiles.length - 10}</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
