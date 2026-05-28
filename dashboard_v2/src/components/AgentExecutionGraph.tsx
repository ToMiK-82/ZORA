import React, { useMemo, useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAgentsGraph } from '../api/dashboardApi';
import {
  FiCpu, FiCode, FiZap, FiBox, FiGlobe, FiSearch,
  FiFileText, FiShoppingBag, FiHeadphones, FiBarChart2, FiDollarSign, FiTruck,
  FiPackage, FiDatabase, FiUserCheck, FiCreditCard,
} from 'react-icons/fi';
import { useWebSocket } from '../api/websocketProvider';
import type { AgentGraphNode, TraceData } from '../types';
import { Card, CardContent } from './ui/card';

// ── Helper: вычислить позиции на орбите ──
function computeOrbitPositions(
  rx: number, ry: number,
  centerX: number, centerY: number,
  count: number,
  orbitAngle: number = 0
): { x: number; y: number }[] {
  if (count === 0) return [];
  return Array.from({ length: count }, (_, index) => {
    const angle = (index / count) * 2 * Math.PI - Math.PI / 2 + orbitAngle;
    return {
      x: centerX + rx * Math.cos(angle) - 28,
      y: centerY + ry * Math.sin(angle) - 28,
    };
  });
}

// ── SVG-логотип ZORA для центра ──
const ZoraLogo = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 64 64" fill="white">
    <path d="M13.402 15.904h5.15v-15h-5.15c-4.142 0-7.5 3.358-7.5 7.5s3.358 7.5 7.5 7.5z"/>
    <path d="M58.098 55.6c0 4.14-3.36 7.5-7.5 7.5h-5.15v-15h5.15c4.14 0 7.5 3.35 7.5 7.5z"/>
    <path d="M26.508 48.1h13.03v15h-22.18c-4.55 0-8.61-2.72-10.36-6.92-1.74-4.21-.78-9 2.43-12.22l28.06-28.06h-13.03v-15h22.18c4.55 0 8.61 2.72 10.36 6.92 1.74 4.21.78 9-2.43 12.22z"/>
  </svg>
);

// ── Иконки агентов (размер w-6 h-6, белые) ──
const agentIcons: Record<string, React.ReactNode> = {
  developer: <FiUserCheck className="w-6 h-6 text-white" />,
  parser: <FiDatabase className="w-6 h-6 text-white" />,
  procurement_manager: <FiShoppingBag className="w-6 h-6 text-white" />,
  smm: <FiZap className="w-6 h-6 text-white" />,
  support: <FiHeadphones className="w-6 h-6 text-white" />,
  economist: <FiBarChart2 className="w-6 h-6 text-white" />,
  accountant: <FiDollarSign className="w-6 h-6 text-white" />,
  logistician: <FiTruck className="w-6 h-6 text-white" />,
  purchaser: <FiPackage className="w-6 h-6 text-white" />,
  sales_consultant: <FiCreditCard className="w-6 h-6 text-white" />,
  website: <FiGlobe className="w-6 h-6 text-white" />,
  inspector: <FiSearch className="w-6 h-6 text-white" />,
};

// ── Градиенты (как в SystemHealthGraph) ──
const agentGradients: Record<string, string> = {
  orchestrator: 'from-zora-accent to-zora-accent-light',
  developer: 'from-rose-400 to-rose-600',
  parser: 'from-blue-400 to-blue-600',
  procurement_manager: 'from-amber-400 to-amber-600',
  smm: 'from-pink-400 to-pink-600',
  support: 'from-cyan-400 to-cyan-600',
  economist: 'from-yellow-400 to-yellow-600',
  accountant: 'from-green-400 to-green-600',
  logistician: 'from-orange-400 to-orange-600',
  sales_consultant: 'from-indigo-400 to-indigo-600',
  website: 'from-red-400 to-red-600',
  inspector: 'from-violet-400 to-violet-600',
};

const agentLabels: Record<string, string> = {
  developer: 'Ассистент Ria',
  parser: 'Парсер (Интегратор данных)',
  procurement_manager: 'Менеджер по закупкам',
};

const shortDescriptions: Record<string, string> = {
  orchestrator: 'Центральный планировщик агентов',
  developer: 'Помощник разработчика, код-ревью, рефакторинг',
  parser: 'Парсинг сайтов, документов и интеграция данных',
  procurement_manager: 'Управление закупками и поставщиками',
  smm: 'Управление соцсетями и контентом',
  support: 'Поддержка пользователей',
  economist: 'Экономический анализ и отчёты',
  accountant: 'Бухгалтерский учёт',
  logistician: 'Логистика и поставки',
  sales_consultant: 'Принимает заказы, консультирует по товарам',
  website: 'Веб-разработка и SEO',
  inspector: 'Проверка качества и аудит',
};

// ── Цвета статусных точек ──
const statusDotColors: Record<string, string> = {
  running: 'bg-zora-green shadow-[0_0_8px_rgba(34,197,94,0.8)]',
  healthy: 'bg-zora-green shadow-[0_0_8px_rgba(34,197,94,0.6)]',
  degraded: 'bg-yellow-400 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
  down: 'bg-zora-red shadow-[0_0_8px_rgba(239,68,68,0.6)]',
  idle: 'bg-zora-gray shadow-[0_0_8px_rgba(107,114,128,0.4)]',
};

function getDisplayLabel(node: AgentGraphNode): string {
  return agentLabels[node.id] || node.label || node.id;
}

// ── Компонент планеты (полностью повторяет SystemOrbitNode) ──
function AgentPlanetNode({
  node,
  status,
  floatDelay = 0,
}: {
  node: AgentGraphNode;
  status: string;
  floatDelay?: number;
}) {
  const gradient = agentGradients[node.id] || 'from-zora-gray to-zora-gray/50';
  const icon = agentIcons[node.id] || <FiBox className="w-6 h-6 text-white" />;

  const animClass = React.useMemo((): string => {
    switch (status) {
      case 'running': return 'animate-float-glow-green';
      case 'healthy': return 'animate-float-glow-green';
      case 'degraded': return 'animate-float-glow-yellow';
      case 'down': return 'animate-float-glow-red';
      default: return 'animate-float-glow-gray';
    }
  }, [status]);

  const animStyle = React.useMemo((): React.CSSProperties => {
    let duration = '5s';
    if (status === 'degraded') duration = '3s';
    else if (status === 'down') duration = '1.5s';
    return { animationDuration: duration, animationDelay: `${floatDelay}s` };
  }, [status, floatDelay]);

  return (
    <div className="flex flex-col items-center gap-1 group">
      <div
        className={`relative w-14 h-14 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center shadow-lg transition-shadow duration-300 group-hover:scale-110 ${animClass}`}
        style={animStyle}
      >
        {icon}
        <span
          className={`absolute -top-1 -right-1 w-3 h-3 rounded-full border-2 border-zora-bg ${
            statusDotColors[status] || 'bg-zora-gray'
          }`}
        />
      </div>
    </div>
  );
}

// ── Панель активных трасс (оставляем как есть) ──
function TracePanel({ traces }: { traces: TraceData[] }) {
  if (!traces || traces.length === 0) return null;
  return (
    <div className="border-t border-border/50 shrink-0">
      <div className="px-3 py-1.5 bg-background/30">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="w-1.5 h-1.5 rounded-full bg-zora-green animate-pulse" />
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
            Активные трассы
          </span>
        </div>
        <div className="space-y-1 max-h-[80px] overflow-y-auto scrollbar-thin">
          {traces.map((trace, i) => (
            <div key={trace.run_id || i} className="flex items-center gap-2 text-[11px]">
              <span className="text-zora-accent font-mono shrink-0">#{i + 1}</span>
              <span className="text-muted-foreground truncate flex-1">{trace.query || 'Запрос'}</span>
              <span className="text-zora-green shrink-0 text-[10px]">{trace.steps?.length || 0} шагов</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Главный компонент ──
export default function AgentExecutionGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setDims({ width, height });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { data, isLoading } = useQuery({
    queryKey: ['agentsGraph'],
    queryFn: getAgentsGraph,
    refetchInterval: 15_000,
  });

  const { agentStatuses, executionTraces } = useWebSocket();
  const [selectedAgent, setSelectedAgent] = useState<AgentGraphNode | null>(null);

  const agents = useMemo(() => data?.nodes ?? [], [data]);

  const agentNodes = useMemo(
    () => agents.filter((a) => a.type === 'agent'),
    [agents]
  );

  // Объединяем трассы из API и WebSocket
  const activeTraces = useMemo(() => {
    const apiTraces = data?.active_traces ?? [];
    const wsTraces = executionTraces
      .filter((t) => t.status === 'running' || !t.completed_at)
      .map((t) => ({
        run_id: t.run_id,
        query: t.query || '',
        steps: t.steps?.map((s) => s.agent) || [],
        started_at: t.started_at || Date.now(),
      }));
    const seen = new Set(apiTraces.map((t) => t.run_id));
    const combined = [...apiTraces];
    for (const wt of wsTraces) {
      if (!seen.has(wt.run_id)) {
        combined.push(wt);
        seen.add(wt.run_id);
      }
    }
    return combined;
  }, [data, executionTraces]);

  // Статус агента: приоритет у WebSocket
  const getAgentStatus = (agentId: string, serverStatus?: string): string => {
    if (agentStatuses[agentId] === 'running' || agentStatuses[agentId] === 'processing') return 'running';
    if (agentStatuses[agentId] === 'error') return 'down';
    return serverStatus || 'idle';
  };

  // Эллиптическая орбита — максимальное заполнение области
  const ellipseConfig = useMemo(() => {
    const w = dims.width;
    const h = dims.height;
    if (w === 0 || h === 0) {
      return { centerX: 200, centerY: 200, rx: 120, ry: 120 };
    }
    const centerX = w / 2;
    const centerY = h / 2;
    // Минимальный отступ от края контейнера до центра планеты — 38px.
    // Сама планета w-14 (56px), половина = 28px, итого ~10px воздух + запас на hover scale-110
    const rx = Math.max(centerX - 38, 60);
    const ry = Math.max(centerY - 38, 60);
    return { centerX, centerY, rx, ry };
  }, [dims]);

  // Статичные позиции планет (без вращения по орбите)
  const staticPositions = useMemo(
    () => computeOrbitPositions(ellipseConfig.rx, ellipseConfig.ry, ellipseConfig.centerX, ellipseConfig.centerY, agentNodes.length),
    [ellipseConfig.rx, ellipseConfig.ry, ellipseConfig.centerX, ellipseConfig.centerY, agentNodes.length]
  );

  const orbitRings = useMemo(() => {
    const { centerX, centerY, rx, ry } = ellipseConfig;
    return [0.5, 0.75, 1.0].map((scale) => ({
      cx: centerX,
      cy: centerY,
      rx: rx * scale,
      ry: ry * scale,
      opacity: scale * 0.25,
    }));
  }, [ellipseConfig]);

  return (
    <Card className="h-full border-border bg-card/50 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0">
        <div className="flex items-center gap-2">
          <FiCpu className="text-zora-accent" />
          <span className="text-sm font-semibold text-foreground">Граф агентов</span>
        </div>
        <span className="text-[10px] text-muted-foreground">{agentNodes.length} агентов</span>
      </div>

      <CardContent className="p-0 flex-1 min-h-[300px] relative overflow-hidden" ref={containerRef}>
        {isLoading ? (
          <div className="h-full flex items-center justify-center min-h-[300px]">
            <p className="text-muted-foreground text-sm">Загрузка графа агентов...</p>
          </div>
        ) : (
          <div className="relative w-full h-full min-h-[300px]">
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {orbitRings.map((ring, i) => (
                <ellipse
                  key={i}
                  cx={ring.cx}
                  cy={ring.cy}
                  rx={ring.rx}
                  ry={ring.ry}
                  fill="none"
                  stroke="rgba(255,140,66,0.22)"
                  strokeWidth={1 + i * 0.3}
                  strokeDasharray="6 4"
                  opacity={ring.opacity}
                />
              ))}
              {staticPositions.map((pos, i) => {
                const node = agentNodes[i];
                if (!pos || !node) return null;
                const status = getAgentStatus(node.id, node.status);
                const isRunning = status === 'running';
                const isHealthy = status === 'running' || status === 'healthy';
                const lineColor = status === 'running'
                  ? 'rgba(255,140,66,0.55)'
                  : status === 'healthy'
                  ? 'rgba(34,197,94,0.55)'
                  : status === 'idle'
                  ? 'rgba(245,158,11,0.45)'
                  : status === 'degraded'
                  ? 'rgba(245,158,11,0.45)'
                  : 'rgba(239,68,68,0.45)';
                return (
                  <line
                    key={`line-${node.id}`}
                    x1={pos.x + 28}
                    y1={pos.y + 28}
                    x2={ellipseConfig.centerX}
                    y2={ellipseConfig.centerY}
                    stroke={lineColor}
                    strokeWidth={isRunning ? 2 : isHealthy && !isRunning ? 1.5 : 1.2}
                    strokeDasharray={isHealthy ? '4 3' : '3 4'}
                    className={isRunning ? 'animate-dash-flow' : ''}
                    opacity={isHealthy ? 1 : 0.65}
                  />
                );
              })}
            </svg>

            {/* Центральный оркестратор — мерцает, расширяется и парит */}
            <div
              className="absolute z-10 animate-float"
              style={{
                left: ellipseConfig.centerX - 48,
                top: ellipseConfig.centerY - 48,
                animationDuration: '5s',

              }}
            >
              <div
                className="w-24 h-24 rounded-full bg-gradient-to-br from-zora-accent to-zora-accent-light flex items-center justify-center shadow-lg animate-pulse-glow"
                style={{ boxShadow: '0 0 30px rgba(255,140,66,0.5)' }}
              >
                <ZoraLogo className="w-10 h-10" />
              </div>
            </div>

            {/* Планеты (агенты) */}
            {staticPositions.map((pos, index) => {
              const node = agentNodes[index];
              if (!pos || !node) return null;
              const status = getAgentStatus(node.id, node.status);
              return (
                <div
                  key={node.id}
                  className="absolute cursor-pointer transition-transform hover:scale-110 z-10"
                  style={{
                    left: pos.x,
                    top: pos.y,
                    filter:
                      status === 'running'
                        ? 'drop-shadow(0 0 8px rgba(255,140,66,0.5))'
                        : status === 'healthy'
                        ? 'drop-shadow(0 0 8px rgba(34,197,94,0.3))'
                        : 'none',
                  }}
                  onClick={() =>
                    setSelectedAgent((prev) =>
                      prev?.id === node.id ? null : node
                    )
                  }
                >
                  <AgentPlanetNode node={node} status={status} floatDelay={index * 0.35} />
                </div>
              );
            })}
          </div>
        )}
      </CardContent>

      <TracePanel traces={activeTraces} />

      {selectedAgent && (
        <div className="border-t border-border/50 p-2 bg-background/50 shrink-0">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-sm font-semibold text-foreground whitespace-nowrap shrink-0">
                {getDisplayLabel(selectedAgent)}
              </span>
              <span className="text-[10px] text-muted-foreground truncate hidden sm:inline">
                {shortDescriptions[selectedAgent.id] || selectedAgent.description || ''}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-background text-muted-foreground border border-border whitespace-nowrap shrink-0">
                {selectedAgent.id}
              </span>
            </div>
            <button
              onClick={() => setSelectedAgent(null)}
              className="text-muted-foreground hover:text-foreground text-xs ml-1 shrink-0"
            >
              ✕
            </button>
          </div>
          {selectedAgent.current_task && (
            <div className="text-xs text-muted-foreground mt-1">
              Текущая задача: <span className="text-zora-accent">{selectedAgent.current_task}</span>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
