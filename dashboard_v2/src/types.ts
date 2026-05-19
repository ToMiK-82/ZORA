// ===== System Health =====
export interface SystemData {
  cpu_percent: number;
  cpu_count: number;
  cpu_count_logical: number;
  cpu_name: string;
  cpu_freq_current: number | null;
  cpu_freq_max: number | null;
  cpu_temp: number | null;
  memory_percent: number;
  memory_total: number;
  memory_used: number;
  memory_free: number;
  disk_percent: number;
  disk_total: number;
  disk_used: number;
  disk_name: string;
  disk_temp: number | null;
  gpu_name: string;
  gpu_percent: number;
  gpu_memory_total: number;
  gpu_memory_used: number;
  gpu_temp: number | null;
}

export interface HealthResponse {
  success: boolean;
  system: SystemData;
  health_score: number;
  issues: string[];
}

// ===== ZORA Status =====
export interface ZoraStatusResponse {
  success: boolean;
  status: string;
  message: string;
  working_components: number;
  total_components: number;
  components: Record<string, boolean>;
  uptime: string;
  docker_running: boolean;
  qdrant_vectors: number;
}

// ===== Agents =====
export interface AgentData {
  status: string;
  state: string;
  current_task: string;
  last_activity: string;
  start_time: string;
  metrics: Record<string, number>;
  class: string;
  module: string;
}

export interface AgentsResponse {
  total_agents: number;
  available_agents: number;
  agents: Record<string, AgentData>;
}

// ===== RAG Metrics =====
export interface RagMetricsResponse {
  success: boolean;
  hit_rate: Record<string, number>;
  mrr: number;
  vectors_count: number;
  timestamp: string;
  evaluation_running?: boolean;
  faithfulness_mean?: number | null;
}

export interface RagDatasetStatsResponse {
  success: boolean;
  total_pairs: number;
  unique_chunk_ids: number;
  sources: Record<string, number>;
}

// ===== System Graph =====
export interface SystemGraphNode {
  id: string;
  label: string;
  type: 'service' | 'database' | 'agent' | 'external';
  status: 'healthy' | 'degraded' | 'down';
  metrics?: Record<string, number>;
  position?: { x: number; y: number };
}

export interface SystemGraphEdge {
  source: string;
  target: string;
  label: string;
  animated?: boolean;
}

export interface SystemGraphResponse {
  nodes: SystemGraphNode[];
  edges: SystemGraphEdge[];
}

// ===== File System Graph =====
export interface FileSystemNode {
  id: string;
  label: string;
  type: 'file' | 'directory';
  size_kb: number;
  last_modified: string;
  status: 'indexed_used' | 'indexed_unused' | 'not_indexed' | 'stale';
  chunks_count: number;
  used_by_agents: string[];
  last_indexed: string | null;
  dependencies: string[];
  children?: FileSystemNode[];
}

export interface FileSystemEdge {
  source: string;
  target: string;
  type: 'import' | 'contains';
}

export interface FileSystemGraphResponse {
  nodes: FileSystemNode[];
  edges: FileSystemEdge[];
}

// ===== Data Pipeline =====
export interface PipelineSource {
  name: string;
  status: 'active' | 'idle' | 'error';
  throughput_chunks_per_hour: number;
  queue_size: number;
  last_run: string;
  error_rate: number;
}

export interface DataPipelineResponse {
  sources: PipelineSource[];
}

// ===== WebSocket =====
export interface WsSystemResources {
  type: 'system_resources';
  data: {
    cpu_percent: number;
    memory_percent: number;
    gpu_percent: number;
    disk_percent: number;
  };
}

export interface WsAgentStatus {
  type: 'agent_status';
  data: {
    agent: string;
    state: string;
  };
}

export interface WsAlert {
  type: 'alert';
  data: {
    message: string;
    severity: 'info' | 'warning' | 'error';
  };
}

export interface WsExecutionTrace {
  type: 'execution_trace';
  event: 'execution_trace' | 'trace_step' | 'trace_completed';
  data: {
    run_id: string;
    query?: string;
    steps?: Array<{ agent: string; timestamp: number; detail: string }>;
    started_at?: number;
    completed_at?: number;
    status?: string;
    result?: string;
  };
}

export type WsMessage = WsSystemResources | WsAgentStatus | WsAlert | WsExecutionTrace;

// ===== Agents Graph (Trace) =====
export interface AgentGraphNode {
  id: string;
  label: string;
  type: 'orchestrator' | 'agent' | 'user' | 'developer';
  status: 'healthy' | 'down' | 'idle' | 'running';
  current_task?: string | null;
  description?: string;
  metrics?: Record<string, number>;
  used_files?: string[];
}

export interface AgentGraphEdge {
  source: string;
  target: string;
  label: string;
}

export interface TraceStep {
  agent: string;
  timestamp: number;
  detail: string;
}

export interface TraceData {
  run_id: string;
  query: string;
  steps: string[];
  started_at: number;
}

export interface AgentGraphResponse {
  nodes: AgentGraphNode[];
  edges: AgentGraphEdge[];
  active_traces: TraceData[];
  recent_traces: TraceData[];
}

// ===== Layout =====
export interface WidgetLayout {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
}


