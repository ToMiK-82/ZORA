import type {
  HealthResponse,
  ZoraStatusResponse,
  AgentsResponse,
  RagMetricsResponse,
  RagDatasetStatsResponse,
  SystemGraphResponse,
  FileSystemGraphResponse,
  DataPipelineResponse,
  AgentGraphResponse,
} from '../types';


const API_BASE = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// ===== Health =====
export function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>('/health');
}

// ===== ZORA Status =====
export function getZoraStatus(): Promise<ZoraStatusResponse> {
  return fetchJson<ZoraStatusResponse>('/zora_status');
}

// ===== Agents =====
export function getAgents(): Promise<AgentsResponse> {
  return fetchJson<AgentsResponse>('/agents');
}

// ===== RAG =====
export function getRagMetrics(): Promise<RagMetricsResponse> {
  return fetchJson<RagMetricsResponse>('/rag/metrics');
}

export function getRagDatasetStats(): Promise<RagDatasetStatsResponse> {
  return fetchJson<RagDatasetStatsResponse>('/rag/dataset_stats');
}

export function runRagEvaluation(): Promise<{ success: boolean; message: string }> {
  return fetchJson('/rag/evaluate', { method: 'POST' });
}

// ===== System Graph =====
export function getSystemGraph(): Promise<SystemGraphResponse> {
  return fetchJson<SystemGraphResponse>('/system/graph');
}

// ===== File System Graph =====
export function getFileSystemGraph(): Promise<FileSystemGraphResponse> {
  return fetchJson<FileSystemGraphResponse>('/filesystem/graph');
}

// ===== Data Pipeline =====
export function getDataPipeline(): Promise<DataPipelineResponse> {
  return fetchJson<DataPipelineResponse>('/datapipeline');
}

// ===== Parsing Status =====
export function getParsingStatus(): Promise<any> {
  return fetchJson<any>('/parsing/status');
}

// ===== Metrics History =====
export function getMetricsHistory(limit = 100): Promise<{ metrics: any[] }> {
  return fetchJson<{ metrics: any[] }>(`/metrics?limit=${limit}`);
}

// ===== Agents Graph =====
export function getAgentsGraph(): Promise<AgentGraphResponse> {
  return fetchJson<AgentGraphResponse>('/agents/graph');
}

// ===== Knowledge Graph (агент–файл) =====
export function getKnowledgeGraph(): Promise<{ nodes: any[]; edges: any[] }> {
  return fetchJson<{ nodes: any[]; edges: any[] }>('/knowledge_graph');
}

// ===== Reindex =====
export function runReindex(mode = 'incremental'): Promise<{ success: boolean; message: string }> {
  return fetchJson(`/reindex?mode=${mode}`, { method: 'POST' });
}

// ===== Parser Tasks =====
export function runParserTask(taskName: string): Promise<{ success: boolean; message: string }> {
  return fetchJson(`/agent/parser/task/${taskName}`, { method: 'POST' });
}

// ===== Scheduler =====
export function startScheduler(): Promise<{ success: boolean; message: string }> {
  return fetchJson('/scheduler/start', { method: 'POST' });
}

// ===== Index Single File =====
export function indexFile(filePath: string): Promise<{ success: boolean; message: string }> {
  return fetchJson(`/index_file?file_path=${encodeURIComponent(filePath)}`, { method: 'POST' });
}
