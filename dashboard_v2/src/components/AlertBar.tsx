import React, { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from '../api/websocketProvider';
import { FiAlertTriangle, FiInfo, FiAlertCircle, FiX, FiClock } from 'react-icons/fi';

const severityConfig: Record<string, { icon: React.ReactNode; color: string }> = {
  critical: { icon: <FiAlertCircle className="animate-pulse" />, color: 'text-red-400 bg-red-500/15 border-red-500/40' },
  error: { icon: <FiAlertCircle />, color: 'text-zora-red bg-zora-red/10 border-zora-red/30' },
  warning: { icon: <FiAlertTriangle />, color: 'text-zora-yellow bg-zora-yellow/10 border-zora-yellow/30' },
  info: { icon: <FiInfo />, color: 'text-blue-400 bg-blue-400/10 border-blue-400/30' },
  success: { icon: <FiInfo />, color: 'text-zora-green bg-zora-green/10 border-zora-green/30' },
};

interface AlertItem {
  severity: string;
  message: string;
  timestamp?: string;
  id: number;
}

let _alertCounter = 0;

export default function AlertBar() {
  const { alerts } = useWebSocket();
  const [visibleAlerts, setVisibleAlerts] = useState<AlertItem[]>([]);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (alerts.length === 0) return;
    const newItems: AlertItem[] = alerts
      .filter((a) => !dismissed.has(a.id ?? -1))
      .map((a) => ({
        severity: a.severity,
        message: a.message,
        timestamp: a.timestamp,
        id: a.id ?? ++_alertCounter,
      }));
    setVisibleAlerts((prev) => [...newItems, ...prev].slice(0, 10));
  }, [alerts, dismissed]);

  useEffect(() => {
    if (visibleAlerts.length === 0) return;
    const timer = setTimeout(() => setVisibleAlerts((prev) => prev.slice(0, -1)), 8000);
    return () => clearTimeout(timer);
  }, [visibleAlerts]);

  const dismiss = useCallback((id: number) => {
    setDismissed((prev) => new Set(prev).add(id));
    setVisibleAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  if (visibleAlerts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm">
      {visibleAlerts.slice(0, 5).map((alert) => {
        const config = severityConfig[alert.severity] || severityConfig.info;
        return (
          <div
            key={alert.id}
            className={`flex items-start gap-2 px-4 py-2.5 rounded-xl border backdrop-blur-sm shadow-lg animate-slide-up ${config.color}`}
          >
            <span className="mt-0.5 shrink-0">{config.icon}</span>
            <div className="flex-1 min-w-0">
              <span className="text-sm block">{alert.message}</span>
              {alert.timestamp && (
                <span className="text-[10px] text-muted-foreground flex items-center gap-1 mt-0.5">
                  <FiClock className="text-[10px]" />
                  {new Date(alert.timestamp).toLocaleTimeString('ru-RU')}
                </span>
              )}
            </div>
            <button
              onClick={() => dismiss(alert.id)}
              className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
            >
              <FiX className="text-sm" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
