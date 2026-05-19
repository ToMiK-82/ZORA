import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ResponsiveTreeMap } from '@nivo/treemap';
import { getFileSystemGraph } from '../api/dashboardApi';
import { FiFolder, FiFile, FiSearch, FiFilter } from 'react-icons/fi';
import type { FileSystemNode } from '../types';

const statusColors: Record<string, string> = {
  indexed_used: '#22C55E',
  indexed_unused: '#F59E0B',
  not_indexed: '#6B7280',
  stale: '#EF4444',
};

const statusLabels: Record<string, string> = {
  indexed_used: 'Индексирован, используется',
  indexed_unused: 'Индексирован, не используется',
  not_indexed: 'Не индексирован',
  stale: 'Устарел',
};

const statusBg: Record<string, string> = {
  indexed_used: 'bg-zora-green/10 border-zora-green',
  indexed_unused: 'bg-zora-yellow/10 border-zora-yellow',
  not_indexed: 'bg-zora-gray/10 border-zora-gray',
  stale: 'bg-zora-red/10 border-zora-red',
};

interface TreeMapData {
  id: string;
  name: string;
  value: number;
  color: string;
  status: string;
  node?: FileSystemNode;
  children?: TreeMapData[];
}

export default function FileSystemGraph() {
  const { data, isLoading } = useQuery({
    queryKey: ['fileSystemGraph'],
    queryFn: getFileSystemGraph,
    refetchInterval: 60_000,
  });

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string[]>(['indexed_used', 'indexed_unused', 'not_indexed', 'stale']);
  const [selectedFile, setSelectedFile] = useState<FileSystemNode | null>(null);

  const allNodes = data?.nodes ?? [];

  const filteredNodes = useMemo(() => {
    return allNodes.filter((node) => {
      if (node.type === 'directory') return false;
      if (search && !node.label.toLowerCase().includes(search.toLowerCase())) return false;
      if (statusFilter.length > 0 && !statusFilter.includes(node.status)) return false;
      return true;
    });
  }, [allNodes, search, statusFilter]);

  const toggleStatusFilter = (status: string) => {
    setStatusFilter((prev) =>
      prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status]
    );
  };

  // Build tree map data
  const treeData = useMemo((): TreeMapData => {
    const root: TreeMapData = {
      id: 'root',
      name: 'Файлы',
      value: 0,
      color: '#2A3A4E',
      status: '',
      children: [],
    };

    // Group by first directory
    const groups: Record<string, TreeMapData> = {};
    filteredNodes.forEach((node) => {
      const parts = node.id.split('/');
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '/';

      if (!groups[dir]) {
        groups[dir] = {
          id: dir,
          name: dir.split('/').pop() || dir,
          value: 0,
          color: '#1A2536',
          status: '',
          children: [],
        };
      }

      groups[dir].children!.push({
        id: node.id,
        name: node.label,
        value: Math.max(node.chunks_count, 1), // min 1 chunk to be visible
        color: statusColors[node.status] || '#6B7280',
        status: node.status,
        node,
      });
    });

    root.children = Object.values(groups);
    return root;
  }, [filteredNodes]);

  const handleClick = (datum: any) => {
    const node = datum.data?.node;
    if (node) {
      setSelectedFile((prev) => (prev?.id === node.id ? null : node));
    }
  };

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
        <span className="ml-auto text-xs text-zora-muted">
          {allNodes.filter((n) => n.type === 'file').length} файлов
        </span>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-3 flex-wrap">
        <div className="flex-1 relative min-w-[150px]">
          <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-zora-muted" />
          <input
            type="text"
            placeholder="Поиск файла..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-zora-bg border border-zora-border rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-zora-muted focus:outline-none focus:border-zora-accent"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {['indexed_used', 'indexed_unused', 'not_indexed', 'stale'].map((status) => (
            <button
              key={status}
              onClick={() => toggleStatusFilter(status)}
              className={`px-2 py-1 rounded-lg text-xs border transition-colors ${
                statusFilter.includes(status)
                  ? `${statusBg[status]} border-current`
                  : 'bg-zora-bg border-zora-border text-zora-muted'
              }`}
            >
              {statusLabels[status].split(',')[0]}
            </button>
          ))}
        </div>
      </div>

      {/* Tree Map */}
      <div className="flex-1" style={{ minHeight: 0 }}>
        {treeData.children && treeData.children.length > 0 ? (
          <ResponsiveTreeMap
            data={treeData}
            identity="id"
            value="value"
            tile="squarify"
            innerPadding={3}
            outerPadding={3}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            colors={{ datum: 'data.color' }}
            borderColor={{ from: 'color', modifiers: [['darker', 0.3]] }}
            nodeOpacity={0.85}
            motionConfig="gentle"
            animate={true}
            label={(d) => {
              // Only show label if rectangle is big enough
              return d.width > 40 ? d.data.name : '';
            }}
            labelTextColor="#FFFFFF"
            labelSkipSize={40}
            orientLabel={false}
            onClick={handleClick}
            tooltip={({ node }: { node: any }) => {
              const n = node.data.node as FileSystemNode | undefined;
              if (!n) return <div />;
              return (
                <div className="bg-zora-card border border-zora-border rounded-xl px-3 py-2 text-xs shadow-lg max-w-[250px]">
                  <div className="font-semibold text-white">{n.label}</div>
                  <div className="text-zora-muted mt-0.5 truncate">{n.id}</div>
                  <div className="flex gap-2 mt-1">
                    <span className="text-zora-muted">{n.size_kb.toFixed(0)} KB</span>
                    <span className="text-zora-muted">{n.chunks_count} чанков</span>
                  </div>
                  <div className="mt-0.5">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-1"
                      style={{ backgroundColor: statusColors[n.status] }}
                    />
                    <span className="text-zora-muted">{statusLabels[n.status]}</span>
                  </div>
                  {n.used_by_agents && n.used_by_agents.length > 0 && (
                    <div className="mt-1 pt-1 border-t border-zora-border/50">
                      <span className="text-zora-muted">Агенты: </span>
                      <span className="text-blue-400">{n.used_by_agents.join(', ')}</span>
                    </div>
                  )}
                </div>
              );
            }}
            theme={{
              tooltip: {
                container: {
                  background: '#131B2A',
                  border: '1px solid #2A3A4E',
                  borderRadius: 12,
                  fontSize: 12,
                },
              },
            }}
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-zora-muted text-sm">Нет файлов</p>
          </div>
        )}
      </div>

      {/* Detail Panel */}
      {selectedFile && (
        <div className="mt-3 p-3 rounded-xl bg-zora-bg border border-zora-border text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-sm">{selectedFile.label}</span>
            <span
              className={`px-2 py-0.5 rounded-full text-xs ${
                selectedFile.status === 'indexed_used'
                  ? 'bg-zora-green/20 text-zora-green'
                  : selectedFile.status === 'indexed_unused'
                  ? 'bg-zora-yellow/20 text-zora-yellow'
                  : selectedFile.status === 'stale'
                  ? 'bg-zora-red/20 text-zora-red'
                  : 'bg-zora-gray/20 text-zora-gray'
              }`}
            >
              {statusLabels[selectedFile.status]}
            </span>
          </div>
          <div className="text-zora-muted">{selectedFile.id}</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className="text-zora-muted">Размер: </span>
              {selectedFile.size_kb.toFixed(1)} KB
            </div>
            <div>
              <span className="text-zora-muted">Чанков: </span>
              {selectedFile.chunks_count}
            </div>
            <div>
              <span className="text-zora-muted">Изменён: </span>
              {new Date(selectedFile.last_modified).toLocaleDateString('ru-RU')}
            </div>
            <div>
              <span className="text-zora-muted">Индексирован: </span>
              {selectedFile.last_indexed
                ? new Date(selectedFile.last_indexed).toLocaleDateString('ru-RU')
                : '—'}
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
