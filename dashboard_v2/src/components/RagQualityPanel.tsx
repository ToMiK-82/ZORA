import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRagMetrics, getRagDatasetStats, runRagEvaluation } from '../api/dashboardApi';
import { FiCpu, FiBarChart2 } from 'react-icons/fi';
import toast from 'react-hot-toast';

export default function RagQualityPanel() {
  const { data: metrics, isLoading: mLoading } = useQuery({
    queryKey: ['ragMetrics'],
    queryFn: getRagMetrics,
    refetchInterval: 30_000,
  });

  const { data: datasetStats } = useQuery({
    queryKey: ['ragDatasetStats'],
    queryFn: getRagDatasetStats,
    refetchInterval: 60_000,
  });

  const handleRunEvaluation = async () => {
    try {
      const result = await runRagEvaluation();
      if (result.success) {
        toast.success('Оценка RAG запущена');
      } else {
        toast.error(result.message || 'Ошибка запуска');
      }
    } catch (e: any) {
      toast.error(e.message || 'Ошибка сети');
    }
  };

  const hitRate = metrics?.hit_rate?.['@5'];
  const hitRatePct = hitRate !== undefined ? (hitRate * 100).toFixed(1) : '—';
  const mrr = metrics?.mrr;
  const vectorsCount = metrics?.vectors_count;
  const faithfulness = metrics?.faithfulness_mean;
  const totalPairs = datasetStats?.total_pairs ?? 0;
  const isLowDataset = totalPairs > 0 && totalPairs < 10;

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiCpu className="text-zora-accent" />
        <h3>Качество RAG</h3>
        <button
          onClick={handleRunEvaluation}
          disabled={metrics?.evaluation_running}
          className="ml-auto btn btn-ghost text-xs"
        >
          {metrics?.evaluation_running ? '⏳ Оценка...' : '▶ Оценить'}
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-3">
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl">
          <span className="metric-value">{hitRatePct}%</span>
          <span className="metric-label">Hit Rate@5</span>
          <span className={`text-xs mt-0.5 ${hitRate !== undefined && hitRate >= 0.85 ? 'text-zora-green' : 'text-zora-yellow'}`}>
            {hitRate !== undefined && hitRate >= 0.85 ? '✅ цель' : 'цель 85%'}
          </span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl">
          <span className="metric-value">{mrr !== undefined ? mrr.toFixed(3) : '—'}</span>
          <span className="metric-label">MRR@5</span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl">
          <span className="metric-value">{vectorsCount ?? '—'}</span>
          <span className="metric-label">Векторов</span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl">
          <span className="metric-value">{faithfulness !== undefined && faithfulness !== null ? faithfulness.toFixed(1) : '—'}</span>
          <span className="metric-label">Faithfulness</span>
        </div>
      </div>

      {/* Dataset Stats */}
      <div className="flex gap-4 text-xs text-zora-muted">
        <span>Пар в датасете: <strong className="text-white">{totalPairs}</strong></span>
        <span>Чанков: <strong className="text-white">{datasetStats?.unique_chunk_ids ?? '—'}</strong></span>
        <span>Источников: <strong className="text-white">
          {datasetStats?.sources ? Object.keys(datasetStats.sources).length : '—'}
        </strong></span>
      </div>

      {isLowDataset && (
        <div className="mt-2 p-2 rounded-lg bg-zora-yellow/10 text-zora-yellow text-xs">
          ⚠️ Датасет содержит менее 10 вопросов. Сгенерируйте датасет для получения метрик.
        </div>
      )}

      {metrics?.timestamp && (
        <div className="mt-auto pt-2 text-xs text-zora-muted">
          Последняя оценка: {new Date(metrics.timestamp).toLocaleString('ru-RU')}
        </div>
      )}
    </div>
  );
}
