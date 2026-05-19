import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getDataPipeline, getParsingStatus } from '../api/dashboardApi';
import { FiShare2, FiDatabase, FiCloud, FiFileText, FiArrowRight, FiCpu, FiSearch } from 'react-icons/fi';

const stages = [
  { id: 'sources', label: 'Источники', icon: FiDatabase, color: 'text-blue-400' },
  { id: 'parsing', label: 'Парсинг', icon: FiCloud, color: 'text-purple-400' },
  { id: 'indexing', label: 'Индексация', icon: FiFileText, color: 'text-zora-accent' },
  { id: 'qdrant', label: 'Qdrant', icon: FiDatabase, color: 'text-zora-green' },
  { id: 'rag', label: 'RAG', icon: FiSearch, color: 'text-zora-accent-light' },
];

const sourceIcons: Record<string, React.ReactNode> = {
  '1C OData': <FiDatabase />,
  'ITS Parser': <FiCloud />,
  'File Indexer': <FiFileText />,
};

const statusColors: Record<string, string> = {
  active: 'bg-zora-green shadow-[0_0_6px_rgba(34,197,94,0.5)]',
  idle: 'bg-zora-yellow shadow-[0_0_6px_rgba(245,158,11,0.5)]',
  error: 'bg-zora-red shadow-[0_0_6px_rgba(239,68,68,0.5)]',
};

export default function DataPipeline() {
  const { data: pipeline, isLoading } = useQuery({
    queryKey: ['dataPipeline'],
    queryFn: getDataPipeline,
    refetchInterval: 10_000,
  });

  const { data: parsing } = useQuery({
    queryKey: ['parsingStatus'],
    queryFn: getParsingStatus,
    refetchInterval: 10_000,
  });

  const sources = pipeline?.sources ?? [];
  const parsingProgress = parsing?.data?.progress;
  const progressPct = parsingProgress?.percent ?? 0;
  const isParsing = parsingProgress?.is_running ?? false;

  // Determine stage statuses
  const stageStatuses: Record<string, 'active' | 'idle' | 'error'> = {
    sources: sources.some((s: any) => s.status === 'active') ? 'active' :
             sources.some((s: any) => s.status === 'error') ? 'error' : 'idle',
    parsing: isParsing ? 'active' : 'idle',
    indexing: sources.some((s: any) => s.status === 'active') ? 'active' : 'idle',
    qdrant: 'active',
    rag: 'idle',
  };

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiShare2 className="text-zora-accent" />
        <h3>Конвейер данных</h3>
      </div>

      {/* Horizontal Pipeline */}
      <div className="flex items-center justify-between gap-1 mb-4 px-2">
        {stages.map((stage, idx) => {
          const StageIcon = stage.icon;
          const status = stageStatuses[stage.id];
          return (
            <React.Fragment key={stage.id}>
              <div className="flex flex-col items-center gap-1.5 group relative">
                <div
                  className={`w-10 h-10 rounded-xl flex items-center justify-center border transition-all duration-200 ${
                    status === 'active'
                      ? 'bg-zora-green/10 border-zora-green text-zora-green'
                      : status === 'error'
                      ? 'bg-zora-red/10 border-zora-red text-zora-red'
                      : 'bg-zora-bg border-zora-border text-zora-muted'
                  }`}
                >
                  <StageIcon className="text-lg" />
                </div>
                <span className="text-[10px] text-zora-muted font-medium whitespace-nowrap">
                  {stage.label}
                </span>
                <span className={`w-1.5 h-1.5 rounded-full ${statusColors[status] || 'bg-zora-gray'}`} />
                {/* Tooltip on hover */}
                <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 bg-zora-card border border-zora-border rounded-lg px-2 py-1 text-[10px] text-zora-muted whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                  {status === 'active' ? 'Активно' : status === 'error' ? 'Ошибка' : 'Ожидает'}
                </div>
              </div>
              {idx < stages.length - 1 && (
                <FiArrowRight className="text-zora-border shrink-0 -mt-4" />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Sources Detail */}
      <div className="flex-1 space-y-2">
        <div className="text-xs font-semibold text-zora-muted mb-1">Источники</div>
        {sources.length === 0 && !isLoading && (
          <p className="text-zora-muted text-sm text-center py-2">Нет данных о конвейере</p>
        )}
        {sources.map((source: any) => (
          <div
            key={source.name}
            className="flex items-center gap-3 p-2.5 rounded-xl bg-zora-bg/50 border border-zora-border"
          >
            <div className="w-7 h-7 rounded-lg bg-zora-card flex items-center justify-center text-zora-accent shrink-0">
              {sourceIcons[source.name] || <FiDatabase />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-xs">{source.name}</div>
              <div className="text-[10px] text-zora-muted">
                {source.throughput_chunks_per_hour} чанков/ч
                {source.queue_size > 0 && ` | очередь: ${source.queue_size}`}
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${statusColors[source.status] || 'bg-zora-gray'}`} />
              <span className="text-[10px] text-zora-muted capitalize">{source.status}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Parsing Progress */}
      {isParsing && (
        <div className="mt-2 p-2.5 rounded-xl bg-zora-bg border border-zora-border">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-medium text-zora-muted">
              {parsingProgress?.operation || 'Парсинг'}
            </span>
            <span className="text-[10px] text-zora-accent">{progressPct.toFixed(0)}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="text-[10px] text-zora-muted mt-1">
            Шаг {parsingProgress?.current_step ?? 0} / {parsingProgress?.total_steps ?? 0}
            {parsingProgress?.current_subject && ` • ${parsingProgress.current_subject}`}
          </div>
        </div>
      )}
    </div>
  );
}
