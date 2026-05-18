import React, { useEffect, useState, useRef } from 'react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { useWebSocket } from '../api/websocketProvider';
import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/dashboardApi';
import { FiCpu, FiMonitor, FiHardDrive, FiServer } from 'react-icons/fi';

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

  return (
    <div className="card flex flex-col">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-zora-accent">{icon}</span>
        <span className="text-xs text-zora-muted font-medium">{label}</span>
      </div>
      <div className="h-12">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
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
