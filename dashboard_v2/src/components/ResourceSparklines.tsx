import React, { useEffect, useState, useRef, useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';
import { useWebSocket } from '../api/websocketProvider';
import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/dashboardApi';
import { FiCpu, FiMonitor, FiHardDrive, FiServer, FiTrendingUp, FiTrendingDown } from 'react-icons/fi';

interface SparklineProps {
  label: string;
  value: number;
  data: { v: number }[];
  color: string;
  icon: React.ReactNode;
  unit?: string;
}

function Sparkline({ label, value, data, color, icon, unit = '%' }: SparklineProps) {
  const valColor = value > 90 ? 'text-zora-red' : value > 75 ? 'text-zora-yellow' : 'text-zora-green';

  // Тренд: сравниваем последнее значение с предыдущим
  const trend = useMemo(() => {
    if (data.length < 2) return null;
    const last = data[data.length - 1].v;
    const prev = data[data.length - 2].v;
    if (last > prev + 0.5) return 'up';
    if (last < prev - 0.5) return 'down';
    return 'stable';
  }, [data]);

  // Статистика: min, max, среднее
  const stats = useMemo(() => {
    if (data.length === 0) return null;
    const vals = data.map(d => d.v);
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }, [data]);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-zora-card border border-zora-border rounded-xl px-3 py-2 text-xs shadow-lg min-w-[140px]">
          <div className="font-semibold text-white">{label}</div>
          <div className="text-zora-muted mt-0.5">
            Текущее: <span className="text-white font-medium">{payload[0].value.toFixed(1)}{unit}</span>
          </div>
          {stats && (
            <>
              <div className="text-zora-muted">
                Мин: <span className="text-blue-400">{stats.min.toFixed(1)}{unit}</span>
              </div>
              <div className="text-zora-muted">
                Макс: <span className="text-zora-red">{stats.max.toFixed(1)}{unit}</span>
              </div>
              <div className="text-zora-muted">
                Среднее: <span className="text-zora-green">{stats.avg.toFixed(1)}{unit}</span>
              </div>
              <div className="mt-1 pt-1 border-t border-zora-border/50">
                {trend === 'up' && <span className="text-zora-red">⬆ Растёт</span>}
                {trend === 'down' && <span className="text-zora-green">⬇ Падает</span>}
                {trend === 'stable' && <span className="text-zora-muted">→ Стабильно</span>}
              </div>
            </>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="card flex flex-col">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-zora-accent">{icon}</span>
        <span className="text-xs text-zora-muted font-medium">{label}</span>
        {trend === 'up' && <FiTrendingUp className="text-zora-red text-xs ml-auto" />}
        {trend === 'down' && <FiTrendingDown className="text-zora-green text-xs ml-auto" />}
      </div>
      <div className="h-12">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="v"
              stroke={color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-baseline justify-between mt-1">
        <span className={`text-lg font-bold ${valColor}`}>
          {value.toFixed(1)}
          <span className="text-xs text-zora-muted font-normal">{unit}</span>
        </span>
      </div>
    </div>
  );
}

export default function ResourceSparklines() {
  const { resources } = useWebSocket();
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth });

  const [history, setHistory] = useState<{
    cpu: { v: number }[];
    ram: { v: number }[];
    gpu: { v: number }[];
    disk: { v: number }[];
  }>({
    cpu: [],
    ram: [],
    gpu: [],
    disk: [],
  });

  const maxPoints = 30;

  useEffect(() => {
    if (!resources) return;
    setHistory(prev => ({
      cpu: [...prev.cpu.slice(-(maxPoints - 1)), { v: resources.cpu_percent }],
      ram: [...prev.ram.slice(-(maxPoints - 1)), { v: resources.memory_percent }],
      gpu: [...prev.gpu.slice(-(maxPoints - 1)), { v: resources.gpu_percent }],
      disk: [...prev.disk.slice(-(maxPoints - 1)), { v: resources.disk_percent }],
    }));
  }, [resources]);

  // Fallback to health data if no WS
  const sys = health?.system;
  const cpuVal = resources?.cpu_percent ?? sys?.cpu_percent ?? 0;
  const ramVal = resources?.memory_percent ?? sys?.memory_percent ?? 0;
  const gpuVal = resources?.gpu_percent ?? sys?.gpu_percent ?? 0;
  const diskVal = resources?.disk_percent ?? sys?.disk_percent ?? 0;

  return (
    <div className="grid grid-cols-2 gap-2 h-full">
      <Sparkline label="CPU" value={cpuVal} data={history.cpu.length ? history.cpu : [{ v: cpuVal }]} color="#3B82F6" icon={<FiCpu />} />
      <Sparkline label="RAM" value={ramVal} data={history.ram.length ? history.ram : [{ v: ramVal }]} color="#22C55E" icon={<FiServer />} />
      <Sparkline label="GPU" value={gpuVal} data={history.gpu.length ? history.gpu : [{ v: gpuVal }]} color="#FF8C42" icon={<FiMonitor />} />
      <Sparkline label="Диск" value={diskVal} data={history.disk.length ? history.disk : [{ v: diskVal }]} color="#EF4444" icon={<FiHardDrive />} />
    </div>
  );
}
