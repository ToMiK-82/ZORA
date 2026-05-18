import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getDataPipeline, getParsingStatus } from '../api/dashboardApi';
import { FiShare2, FiDatabase, FiCloud, FiFileText } from 'react-icons/fi';

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

  // Parsing progress
  const parsingProgress = parsing?.data?.progress;
  const progressPct = parsingProgress?.percent ?? 0;
  const isParsing = parsingProgress?.is_running ?? false;

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiShare2 className="text-zora-accent" />
        <h3>Конвейер данных</h3>
      </div>

      {/* Sources */}
      <div className="flex-1 space-y-2">
        {sources.length === 0 && !isLoading && (
          <p className="text-zora-muted text-sm text-center py-4">Нет данных о конвейере</p>
        )}
        {sources.map(source => (
          <div
            key={source.name}
            className="flex items-center gap-3 p-3 rounded-xl bg-zora-bg/50 border border-zora-border"
          >
            <div className="w-8 h-8 rounded-lg bg-zora-card flex items-center justify-center text-zora-accent">
              {sourceIcons[source.name] || <FiDatabase />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm">{source.name}</div>
              <div className="text-xs text-zora-muted">
                {source.throughput_chunks_per_hour} чанков/ч
                {source.queue_size > 0 && ` | очередь: ${source.queue_size}`}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${statusColors[source.status] || 'bg-zora-gray'}`} />
              <span className="text-xs text-zora-muted capitalize">{source.status}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Parsing Progress */}
      {isParsing && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-zora-muted">
              {parsingProgress?.operation || 'Парсинг'}
            </span>
            <span className="text-xs text-zora-accent">{progressPct.toFixed(0)}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="text-xs text-zora-muted mt-1">
            Шаг {parsingProgress?.current_step ?? 0} / {parsingProgress?.total_steps ?? 0}
            {parsingProgress?.current_subject && ` • ${parsingProgress.current_subject}`}
          </div>
        </div>
      )}
    </div>
  );
}
