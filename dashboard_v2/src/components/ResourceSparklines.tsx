import React, { useEffect, useState, useMemo } from 'react';
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';
import { useWebSocket } from '../api/websocketProvider';
import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/dashboardApi';
import { FiCpu, FiMonitor, FiHardDrive, FiServer, FiTrendingUp, FiTrendingDown } from 'react-icons/fi';
import { Card, CardContent } from './ui/card';

interface SparklineProps {
  label: string;
  value: number;
  data: { v: number }[];
  color: string;
  icon: React.ReactNode;
  unit?: string;
}

function Sparkline({ label, value, data, color, icon, unit = '%' }: SparklineProps) {
  const valColor = value > 90 ? 'text-red-400' : value > 75 ? 'text-yellow-400' : 'text-zora-green';

  const trend = useMemo(() => {
    if (data.length < 2) return null;
    const last = data[data.length - 1].v;
    const prev = data[data.length - 2].v;
    if (last > prev + 0.5) return 'up';
    if (last < prev - 0.5) return 'down';
    return 'stable';
  }, [data]);

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
        <div className="bg-card border border-border rounded-xl px-3 py-2 text-xs shadow-lg min-w-[140px]">
          <div className="font-semibold text-foreground">{label}</div>
          <div className="text-muted-foreground mt-0.5">
            Текущее: <span className="text-foreground font-medium">{payload[0].value.toFixed(1)}{unit}</span>
          </div>
          {stats && (
            <>
              <div className="text-muted-foreground">
                Мин: <span className="text-blue-400">{stats.min.toFixed(1)}{unit}</span>
              </div>
              <div className="text-muted-foreground">
                Макс: <span className="text-red-400">{stats.max.toFixed(1)}{unit}</span>
              </div>
            </>
          )}
        </div>
      );
    }
    return null;
  };

  // Если данных нет, показываем хотя бы текущее значение
  const displayData = data.length > 0 ? data : [{ v: value }];

  return (
    <div className="bg-card/50 border border-border rounded-xl p-2.5 flex flex-col transition-all hover:border-zora-accent/30">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-zora-accent">{icon}</span>
        <span className="text-[10px] text-muted-foreground font-medium">{label}</span>
        {trend === 'up' && <FiTrendingUp className="text-red-400 text-[10px] ml-auto" />}
        {trend === 'down' && <FiTrendingDown className="text-zora-green text-[10px] ml-auto" />}
      </div>
      <div className="h-10">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={displayData}>
            <Tooltip content={<CustomTooltip />} />
            <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-baseline justify-between mt-0.5">
        <span className={`text-base font-bold ${valColor}`}>
          {value.toFixed(1)}
          <span className="text-[10px] text-muted-foreground font-normal">{unit}</span>
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

  const sys = health?.system;
  const cpuVal = resources?.cpu_percent ?? sys?.cpu_percent ?? 0;
  const ramVal = resources?.memory_percent ?? sys?.memory_percent ?? 0;
  const gpuVal = resources?.gpu_percent ?? sys?.gpu_percent ?? 0;
  const diskVal = resources?.disk_percent ?? sys?.disk_percent ?? 0;

  return (
    <Card className="h-full border-border bg-card/50">
      <CardContent className="p-2.5 h-full">
        <div className="grid grid-cols-2 gap-1.5 h-full">
          <Sparkline label="CPU" value={cpuVal} data={history.cpu} color="#3B82F6" icon={<FiCpu />} />
          <Sparkline label="RAM" value={ramVal} data={history.ram} color="#22C55E" icon={<FiServer />} />
          <Sparkline label="GPU" value={gpuVal} data={history.gpu} color="#FF8C42" icon={<FiMonitor />} />
          <Sparkline label="SSD" value={diskVal} data={history.disk} color="#EF4444" icon={<FiHardDrive />} />
        </div>
      </CardContent>
    </Card>
  );
}
