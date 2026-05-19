import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRagMetrics, getRagDatasetStats, runRagEvaluation } from '../api/dashboardApi';
import { FiCpu, FiBarChart2 } from 'react-icons/fi';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from 'recharts';
import toast from 'react-hot-toast';

interface HistoryPoint {
  time: string;
  faithfulness: number | null;
  hitRate: number | null;
}

const HISTORY_KEY = 'zora-rag-metrics-history';
const MAX_HISTORY = 50;

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

  const [history, setHistory] = useState<HistoryPoint[]>(() => {
    try {
      const saved = localStorage.getItem(HISTORY_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Append new metrics to history
  useEffect(() => {
    if (!metrics?.timestamp) return;
    const hitRate = metrics.hit_rate?.['@5'];
    const faithfulness = metrics.faithfulness_mean;

    setHistory((prev) => {
      const last = prev[prev.length - 1];
      // Avoid duplicates
      if (last && last.time === new Date(metrics.timestamp!).toLocaleTimeString('ru-RU')) {
        return prev;
      }
      const newPoint: HistoryPoint = {
        time: new Date(metrics.timestamp!).toLocaleTimeString('ru-RU'),
        faithfulness: faithfulness ?? null,
        hitRate: hitRate ?? null,
      };
      const updated = [...prev, newPoint].slice(-MAX_HISTORY);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
      return updated;
    });
  }, [metrics?.timestamp, metrics?.hit_rate, metrics?.faithfulness_mean]);

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

      {/* Metric Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl min-w-0">
          <span className="metric-value">{hitRatePct}%</span>
          <span className="metric-label truncate w-full text-center" title="Hit Rate@5">Hit Rate@5</span>
          <span className={`text-xs mt-0.5 ${hitRate !== undefined && hitRate >= 0.85 ? 'text-zora-green' : 'text-zora-yellow'}`}>
            {hitRate !== undefined && hitRate >= 0.85 ? '✅ цель' : 'цель 85%'}
          </span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl min-w-0">
          <span className="metric-value">{mrr !== undefined ? mrr.toFixed(3) : '—'}</span>
          <span className="metric-label truncate w-full text-center" title="MRR@5">MRR@5</span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl min-w-0">
          <span className="metric-value">{vectorsCount ?? '—'}</span>
          <span className="metric-label truncate w-full text-center" title="Векторов">Векторов</span>
        </div>
        <div className="flex flex-col items-center p-2 bg-zora-bg rounded-xl min-w-0">
          <span className="metric-value">{faithfulness !== undefined && faithfulness !== null ? faithfulness.toFixed(1) : '—'}</span>
          <span className="metric-label truncate w-full text-center" title="Faithfulness (верность контексту)">Faithfulness</span>
        </div>
      </div>

      {/* Trend Chart */}
      {history.length >= 2 && (
        <div className="mb-3 p-2 bg-zora-bg rounded-xl" style={{ height: 100 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1A2536" />
              <XAxis dataKey="time" tick={{ fill: '#6B7280', fontSize: 9 }} tickLine={false} />
              <YAxis domain={[0, 5]} tick={{ fill: '#6B7280', fontSize: 9 }} tickLine={false} width={20} />
              <Tooltip
                contentStyle={{
                  background: '#131B2A',
                  border: '1px solid #2A3A4E',
                  borderRadius: 12,
                  fontSize: 12,
                }}
                labelStyle={{ color: '#A0B3CC' }}
              />
              <Line
                type="monotone"
                dataKey="faithfulness"
                stroke="#FF8C42"
                strokeWidth={2}
                dot={false}
                name="Faithfulness"
              />
              <Line
                type="monotone"
                dataKey="hitRate"
                stroke="#3B82F6"
                strokeWidth={2}
                dot={false}
                name="Hit Rate"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

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
