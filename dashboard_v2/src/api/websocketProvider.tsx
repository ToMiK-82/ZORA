import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import type { WsMessage, WsSystemResources, WsAgentStatus, WsAlert } from '../types';

interface WebSocketState {
  resources: WsSystemResources['data'] | null;
  agentStatuses: Record<string, string>;
  alerts: WsAlert['data'][];
  connected: boolean;
}

interface WebSocketContextValue extends WebSocketState {
  lastUpdate: string | null;
}

const WebSocketContext = createContext<WebSocketContextValue>({
  resources: null,
  agentStatuses: {},
  alerts: [],
  connected: false,
  lastUpdate: null,
});

export function useWebSocket() {
  return useContext(WebSocketContext);
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<WebSocketState>({
    resources: null,
    agentStatuses: {},
    alerts: [],
    connected: false,
  });
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/ws/telemetry`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setState(prev => ({ ...prev, connected: true }));
      };

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data);
          setState(prev => {
            switch (msg.type) {
              case 'system_resources':
                return { ...prev, resources: msg.data };
              case 'agent_status':
                return {
                  ...prev,
                  agentStatuses: { ...prev.agentStatuses, [msg.data.agent]: msg.data.state },
                };
              case 'alert':
                return {
                  ...prev,
                  alerts: [...prev.alerts.slice(-49), msg.data],
                };
              default:
                return prev;
            }
          });
          setLastUpdate(new Date().toLocaleTimeString('ru-RU'));
        } catch (e) {
          console.error('WS parse error:', e);
        }
      };

      ws.onclose = () => {
        setState(prev => ({ ...prev, connected: false }));
        wsRef.current = null;
        // Reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      console.error('WS connection error:', e);
      reconnectTimeoutRef.current = setTimeout(connect, 5000);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  return (
    <WebSocketContext.Provider value={{ ...state, lastUpdate }}>
      {children}
    </WebSocketContext.Provider>
  );
}
