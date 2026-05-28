import React from 'react';

// === AgentPrism-совместимые компоненты для дашборда ZORA ===

interface TraceData {
  run_id: string;
  query: string;
  steps: string[];
  started_at: number;
  completed_at?: number;
  status?: string;
  result?: string;
}

interface MetricsData {
  hit_rate: Record<string, number>;
  mrr: number;
  faithfulness_mean?: number | null;
  vectors_count: number;
}

interface TraceViewProps {
  traces: TraceData[];
  maxHeight?: string;
}

export function TraceView({ traces, maxHeight = '200px' }: TraceViewProps) {
  if (!traces || traces.length === 0) {
    return (
      <div className="text-xs text-zora-muted text-center py-4">
        Нет данных о трассировках
      </div>
    );
  }

  return (
    <div className="space-y-2" style={{ maxHeight, overflow: 'auto' }}>
      <h4 className="text-xs font-semibold text-zora-muted uppercase tracking-wider mb-2">
        Последние трассировки
      </h4>
      {traces.slice(0, 10).map((trace) => (
        <div
          key={trace.run_id}
          className="p-2 rounded-lg bg-zora-bg border border-zora-border text-xs"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-white font-medium truncate flex-1">
              {trace.query || 'Без запроса'}
            </span>
            <span
              className={`ml-2 px-1.5 py-0.5 rounded-full text-[10px] ${
                trace.status === 'completed'
                  ? 'bg-zora-green/20 text-zora-green'
                  : trace.status === 'running'
                  ? 'bg-zora-accent/20 text-zora-accent'
                  : 'bg-zora-gray/20 text-zora-gray'
              }`}
            >
              {trace.status || 'unknown'}
            </span>
          </div>
          <div className="text-zora-muted">
            <span>Шагов: {trace.steps?.length || 0}</span>
            <span className="ml-3">
              {new Date(trace.started_at * 1000).toLocaleTimeString('ru-RU')}
            </span>
          </div>
          {trace.steps && trace.steps.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {trace.steps.slice(0, 3).map((step, i) => (
                <div key={i} className="flex items-center gap-1 text-zora-muted">
                  <span className="w-1 h-1 rounded-full bg-zora-accent" />
                  <span className="truncate">{step}</span>
                </div>
              ))}
              {trace.steps.length > 3 && (
                <span className="text-zora-gray text-[10px]">
                  +{trace.steps.length - 3} шагов
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

interface MetricsViewProps {
  metrics: MetricsData | null;
}

export function MetricsView({ metrics }: MetricsViewProps) {
  if (!metrics) {
    return (
      <div className="text-xs text-zora-muted text-center py-4">
        Метрики не загружены
      </div>
    );
  }

  const hitRateEntries = metrics.hit_rate ? Object.entries(metrics.hit_rate) : [];

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-zora-muted uppercase tracking-wider">
        Метрики RAG
      </h4>
      <div className="grid grid-cols-3 gap-2">
        <div className="p-2 rounded-lg bg-zora-bg border border-zora-border text-center">
          <div className="text-lg font-bold text-zora-accent">
            {metrics.mrr ? (metrics.mrr * 100).toFixed(1) : '—'}%
          </div>
          <div className="text-[10px] text-zora-muted">MRR</div>
        </div>
        <div className="p-2 rounded-lg bg-zora-bg border border-zora-border text-center">
          <div className="text-lg font-bold text-zora-green">
            {metrics.faithfulness_mean != null
              ? (metrics.faithfulness_mean * 100).toFixed(1)
              : '—'}%
          </div>
          <div className="text-[10px] text-zora-muted">Faithfulness</div>
        </div>
        <div className="p-2 rounded-lg bg-zora-bg border border-zora-border text-center">
          <div className="text-lg font-bold text-blue-400">
            {metrics.vectors_count?.toLocaleString() || '—'}
          </div>
          <div className="text-[10px] text-zora-muted">Векторов</div>
        </div>
      </div>

      {hitRateEntries.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-medium text-zora-muted">Hit Rate по источникам</div>
          {hitRateEntries.map(([source, rate]) => (
            <div key={source} className="flex items-center gap-2">
              <span className="text-xs text-zora-muted w-20 truncate">{source}</span>
              <div className="flex-1 h-2 rounded-full bg-zora-bg overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-zora-accent to-zora-accent-light"
                  style={{ width: `${(rate * 100).toFixed(0)}%` }}
                />
              </div>
              <span className="text-xs text-white font-medium w-12 text-right">
                {(rate * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
