import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getFileSystemGraph } from '../api/dashboardApi';
import { FiFolder, FiFile, FiSearch, FiFilter } from 'react-icons/fi';
import type { FileSystemNode } from '../types';

const statusColors: Record<string, string> = {
  indexed_used: 'border-zora-green bg-zora-green/10',
  indexed_unused: 'border-zora-yellow bg-zora-yellow/10',
  not_indexed: 'border-zora-gray bg-zora-gray/10',
  stale: 'border-zora-red bg-zora-red/10',
};

const statusLabels: Record<string, string> = {
  indexed_used: 'Индексирован, используется',
  indexed_unused: 'Индексирован, не используется',
  not_indexed: 'Не индексирован',
  stale: 'Устарел',
};

export default function FileSystemGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['fileSystemGraph'],
    queryFn: getFileSystemGraph,
    refetchInterval: 60_000,
  });

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileSystemNode | null>(null);

  const allNodes = data?.nodes ?? [];

  const filteredNodes = useMemo(() => {
    return allNodes.filter(node => {
      if (node.type === 'directory') return false;
      if (search && !node.label.toLowerCase().includes(search.toLowerCase())) return false;
      if (statusFilter.length > 0 && !statusFilter.includes(node.status)) return false;
      return true;
    });
  }, [allNodes, search, statusFilter]);

  const toggleStatusFilter = (status: string) => {
    setStatusFilter(prev =>
      prev.includes(status) ? prev.filter(s => s !== status) : [...prev, status]
    );
  };

  // Group by directory
  const grouped = useMemo(() => {
    const groups: Record<string, FileSystemNode[]> = {};
    filteredNodes.forEach(node => {
      const parts = node.id.split('/');
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '/';
      if (!groups[dir]) groups[dir] = [];
      groups[dir].push(node);
    });
    return groups;
  }, [filteredNodes]);

  if (isLoading) {
    return (
      <div className="card h-full flex items-center justify-center">
        <p className="text-zora-muted">Загрузка графа файлов...</p>
      </div>
    );
  }

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header">
        <FiFolder className="text-zora-accent" />
        <h3>Граф файловой системы</h3>
        <span className="ml-auto text-xs text-zora-muted">{allNodes.filter(n => n.type === 'file').length} файлов</span>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-3 flex-wrap">
        <div className="flex-1 relative min-w-[150px]">
          <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-zora-muted" />
          <input
            type="text"
            placeholder="Поиск файла..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-zora-bg border border-zora-border rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-zora-muted focus:outline-none focus:border-zora-accent"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {['indexed_used', 'indexed_unused', 'not_indexed', 'stale'].map(status => (
            <button
              key={status}
              onClick={() => toggleStatusFilter(status)}
              className={`px-2 py-1 rounded-lg text-xs border transition-colors ${
                statusFilter.includes(status)
                  ? `${statusColors[status]} border-current`
                  : 'bg-zora-bg border-zora-border text-zora-muted'
              }`}
            >
              {statusLabels[status].split(',')[0]}
            </button>
          ))}
        </div>
      </div>

      {/* File List */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {Object.entries(grouped).map(([dir, files]) => (
          <div key={dir}>
            <div className="text-xs text-zora-muted font-medium px-2 py-1 sticky top-0 bg-zora-card z-10">
              <FiFolder className="inline mr-1" />{dir}
            </div>
            {files.map(file => (
              <button
                key={file.id}
                onClick={() => setSelectedFile(selectedFile?.id === file.id ? null : file)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors border-l-2 ${
                  statusColors[file.status] || 'border-zora-border'
                } hover:bg-zora-border/30 text-left ${
                  selectedFile?.id === file.id ? 'ring-1 ring-zora-accent' : ''
                }`}
              >
                <FiFile className="shrink-0 text-zora-muted" />
                <span className="truncate flex-1">{file.label}</span>
                <span className="text-zora-muted shrink-0">{file.chunks_count} ч.</span>
              </button>
            ))}
          </div>
        ))}
        {Object.keys(grouped).length === 0 && (
          <p className="text-center text-zora-muted text-sm py-8">Нет файлов</p>
        )}
      </div>

      {/* Detail Panel */}
      {selectedFile && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-sm">{selectedFile.label}</span>
            <span className={`px-2 py-0.5 rounded-full text-xs ${
              selectedFile.status === 'indexed_used' ? 'bg-zora-green/20 text-zora-green' :
              selectedFile.status === 'indexed_unused' ? 'bg-zora-yellow/20 text-zora-yellow' :
              selectedFile.status === 'stale' ? 'bg-zora-red/20 text-zora-red' :
              'bg-zora-gray/20 text-zora-gray'
            }`}>
              {statusLabels[selectedFile.status]}
            </span>
          </div>
          <div className="text-zora-muted">{selectedFile.id}</div>
          <div className="grid grid-cols-2 gap-2">
            <div><span className="text-zora-muted">Размер: </span>{selectedFile.size_kb.toFixed(1)} KB</div>
            <div><span className="text-zora-muted">Чанков: </span>{selectedFile.chunks_count}</div>
            <div><span className="text-zora-muted">Изменён: </span>{new Date(selectedFile.last_modified).toLocaleDateString('ru-RU')}</div>
            <div><span className="text-zora-muted">Индексирован: </span>
              {selectedFile.last_indexed ? new Date(selectedFile.last_indexed).toLocaleDateString('ru-RU') : '—'}
            </div>
          </div>
          {selectedFile.used_by_agents.length > 0 && (
            <div>
              <span className="text-zora-muted">Используется агентами: </span>
              {selectedFile.used_by_agents.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
