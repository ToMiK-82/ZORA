import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRagMetrics, runRagEvaluation } from '../api/dashboardApi';
import { TraceView, MetricsView } from './AgentPrism';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from './ui/card';
import { Button } from './ui/button';
import { FiSearch, FiRefreshCw, FiBarChart2 } from 'react-icons/fi';
import toast from 'react-hot-toast';

export default function RagQualityPanel() {
  const { data: metrics, isLoading, refetch } = useQuery({
    queryKey: ['ragMetrics'],
    queryFn: getRagMetrics,
    refetchInterval: 30_000,
  });

  const [evaluating, setEvaluating] = React.useState(false);

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      await runRagEvaluation();
      toast.success('Оценка RAG запущена');
      setTimeout(() => refetch(), 5000);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <Card className="h-full border-border bg-card/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FiSearch className="text-zora-accent" />
            Качество RAG
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
          </div>
        </div>
        <CardDescription className="text-[10px]">
          {metrics?.timestamp
            ? `Обновлено: ${new Date(metrics.timestamp).toLocaleTimeString('ru-RU')}`
            : 'Метрики retrieval-augmented generation'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <p className="text-muted-foreground text-sm">Загрузка метрик...</p>
          </div>
        ) : (
          <>
            <MetricsView
              metrics={
                metrics
                  ? {
                      hit_rate: metrics.hit_rate,
                      mrr: metrics.mrr,
                      faithfulness_mean: metrics.faithfulness_mean,
                      vectors_count: metrics.vectors_count,
                    }
                  : null
              }
            />

            <div className="border-t border-border/50 pt-2">
              <TraceView
                traces={
                  (metrics as any)?.recent_traces?.map((t: any) => ({
                    run_id: t.run_id,
                    query: t.query,
                    steps: t.steps || [],
                    started_at: t.started_at,
                    status: t.status,
                    result: t.result,
                  })) || []
                }
                maxHeight="160px"
              />
            </div>

            {metrics?.evaluation_running && (
              <div className="flex items-center gap-2 text-xs text-zora-accent animate-pulse">
                <FiBarChart2 />
                Оценка выполняется...
              </div>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={handleEvaluate}
              disabled={evaluating || metrics?.evaluation_running}
              className="w-full text-xs border-border text-muted-foreground hover:text-white"
            >
              {evaluating ? '⏳ Оценка...' : '▶ Запустить оценку'}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
