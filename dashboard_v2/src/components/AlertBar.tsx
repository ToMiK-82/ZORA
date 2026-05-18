import React from 'react';
import { useWebSocket } from '../api/websocketProvider';
import { FiAlertTriangle, FiInfo, FiAlertCircle } from 'react-icons/fi';

const severityConfig: Record<string, { icon: React.ReactNode; color: string }> = {
  error: { icon: <FiAlertCircle />, color: 'text-zora-red bg-zora-red/10 border-zora-red/30' },
  warning: { icon: <FiAlertTriangle />, color: 'text-zora-yellow bg-zora-yellow/10 border-zora-yellow/30' },
  info: { icon: <FiInfo />, color: 'text-blue-400 bg-blue-400/10 border-blue-400/30' },
};

export default function AlertBar() {
  const { alerts } = useWebSocket();

  if (alerts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm">
      {alerts.slice(-3).reverse().map((alert, i) => {
        const config = severityConfig[alert.severity] || severityConfig.info;
        return (
          <div
            key={i}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl border backdrop-blur-sm shadow-lg animate-slide-up ${config.color}`}
          >
            {config.icon}
            <span className="text-sm">{alert.message}</span>
          </div>
        );
      })}
    </div>
  );
}
