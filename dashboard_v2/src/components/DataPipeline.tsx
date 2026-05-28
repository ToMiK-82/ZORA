import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getDataPipeline, runReindex } from '../api/dashboardApi';
import {
  FiArrowDown,
  FiFileText,
  FiGitBranch,
  FiDatabase,
  FiAlertCircle,
  FiCheckCircle,
  FiClock,
  FiRefreshCw,
} from 'react-icons/fi';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import toast from 'react-hot-toast';
import type { PipelineSource } from '../types';

const stageIcons: Record<string, React.ReactNode> = {
  collector_its: <FiArrowDown className="text-white text-lg" />,
  collector_ukorona: <FiArrowDown className="text-white text-lg" />,
  parser: <FiFileText className="text-white text-lg" />,
  chunk: <FiGitBranch className="text-white text-lg" />,
  embed: <FiDatabase className="text-white text-lg" />,
};

const stageGradients: Record<string, string> = {
  collector_its: 'from-blue-400 to-blue-600',
  collector_ukorona: 'from-blue-400 to-blue-600',
  parser: 'from-purple-400 to-purple-600',
  chunk: 'from-pink-400 to-pink-600',
  embed: 'from-emerald-400 to-emerald-600',
};


const statusIcons: Record<string, React.ReactNode> = {
  active: <FiCheckCircle className="w-4 h-4 text-zora-green" />,
  idle: <FiClock className="w-4 h-4 text-zora-gray" />,
  error: <FiAlertCircle className="w-4 h-4 text-zora-red" />,
};

export default function DataPipeline() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dataPipeline'],
    queryFn: getDataPipeline,
    refetchInterval: 15_000,
  });

  const [indexing, setIndexing] = useState(false);
  const [actionLabel, setActionLabel] = useState<string | null>(null);

  const sources: PipelineSource[] = data?.sources ?? [];

  const handleReindex = async (mode: 'full' | 'incremental') => {
    setIndexing(true);
    setActionLabel(mode === 'full' ? 'Полная индексация...' : 'Инкрементальная...');
    try {
      const result = await runReindex(mode);
      if (result.success) {
        toast.success(`Индексация (${mode}) запущена`);
        setTimeout(() => refetch(), 3000);
      } else {
        toast.error(result.message || 'Ошибка индексации');
      }
    } catch (e: any) {
      toast.error(e.message || 'Ошибка сети');
    } finally {
      setIndexing(false);
      setActionLabel(null);
    }
  };

  return (
    <Card className="h-full border-border bg-card/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FiGitBranch className="text-zora-accent" />
            Конвейер данных
          </CardTitle>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              className="h-7 w-7 p-0"
            >
              <FiRefreshCw className="text-xs text-muted-foreground" />
            </Button>
            <span className="text-[10px] text-muted-foreground">{sources.length} источников</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <p className="text-muted-foreground text-sm">Загрузка...</p>
          </div>
        ) : sources.length === 0 ? (
          <div className="flex items-center justify-center py-6">
            <p className="text-muted-foreground text-sm">Нет активных источников</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {sources.map((source, idx) => {
              const gradient = stageGradients[source.name] || 'from-zora-gray to-zora-gray/50';
              const icon = stageIcons[source.name] || <FiDatabase className="text-lg" />;
              const statusIcon = statusIcons[source.status];

              return (
                <div
                  key={source.name}
                  className={`flex items-center gap-3 p-2 rounded-xl border transition-all ${
                    source.status === 'active'
                      ? 'border-zora-green/30 bg-zora-green/5'
                      : source.status === 'error'
                      ? 'border-zora-red/30 bg-zora-red/5'
                      : 'border-border/50 bg-background/30'
                  }`}
                >
                  <div className={`w-8 h-8 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center shrink-0 shadow-lg shadow-black/20`}>
                    {icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-foreground truncate">{source.name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {source.throughput_chunks_per_hour} ч/ч · оч. {source.queue_size}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {statusIcon}
                    <span className="text-[10px] text-muted-foreground capitalize">{source.status}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Кнопки индексации */}
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleReindex('incremental')}
            disabled={indexing}
            className="flex-1 text-[10px] h-7 border-border text-muted-foreground hover:text-white"
          >
            {indexing && actionLabel === 'Инкрементальная...' ? (
              <span className="animate-pulse">⏳</span>
            ) : (
              '▶ Инкрементально'
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleReindex('full')}
            disabled={indexing}
            className="flex-1 text-[10px] h-7 border-border text-muted-foreground hover:text-white"
          >
            {indexing && actionLabel === 'Полная индексация...' ? (
              <span className="animate-pulse">⏳</span>
            ) : (
              '▶ Полная'
            )}
          </Button>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-3 gap-2 pt-1">
          <div className="text-center">
            <div className="text-lg font-bold text-zora-green">
              {sources.filter((s) => s.status === 'active').length}
            </div>
            <div className="text-[10px] text-muted-foreground">Активно</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-zora-yellow">
              {sources.filter((s) => s.status === 'idle').length}
            </div>
            <div className="text-[10px] text-muted-foreground">Ожидают</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-zora-red">
              {sources.filter((s) => s.status === 'error').length}
            </div>
            <div className="text-[10px] text-muted-foreground">Ошибок</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
