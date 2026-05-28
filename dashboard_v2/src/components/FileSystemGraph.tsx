import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ResponsiveTreeMap } from '@nivo/treemap';
import { getFileSystemGraph, indexFile } from '../api/dashboardApi';
import { FiFolder, FiFile, FiSearch, FiUpload } from 'react-icons/fi';
import toast from 'react-hot-toast';
import type { FileSystemNode } from '../types';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';

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
  const containerRef = useRef<HTMLDivElement>(null);
  const [treeHeight, setTreeHeight] = useState(200);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setTreeHeight(Math.max(entry.contentRect.height - 120, 120));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { data, isLoading } = useQuery({
    queryKey: ['fileSystemGraph'],
    queryFn: getFileSystemGraph,
    refetchInterval: 60_000,
  });

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string[]>(['indexed_used', 'indexed_unused', 'not_indexed', 'stale']);
  const [selectedFile, setSelectedFile] = useState<FileSystemNode | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

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

  const treeData = useMemo((): TreeMapData => {
    const root: TreeMapData = { id: 'root', name: 'Файлы', value: 0, color: '#2A3A4E', status: '', children: [] };
    const groups: Record<string, TreeMapData> = {};
    filteredNodes.forEach((node) => {
      const parts = node.id.split('/');
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '/';
      if (!groups[dir]) {
        groups[dir] = { id: dir, name: dir.split('/').pop() || dir, value: 0, color: '#1A2536', status: '', children: [] };
      }
      groups[dir].children!.push({
        id: node.id,
        name: node.label,
        value: Math.max(node.chunks_count, 1),
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
    if (node) setSelectedFile((prev) => (prev?.id === node.id ? null : node));
  };

  const handleIndexFile = async (filePath: string) => {
    setActionLoading(filePath);
    try {
      await indexFile(filePath);
      toast.success('Файл отправлен на индексацию');
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <Card className="h-full border-border bg-card/50 flex flex-col" style={{ maxHeight: '100%' }}>
      <CardHeader className="pb-2 shrink-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FiFolder className="text-zora-accent" />
            Граф файловой системы
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">
            {allNodes.filter((n) => n.type === 'file').length} файлов
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 flex flex-col flex-1 min-h-0 overflow-hidden" ref={containerRef}>
        {/* Filters */}
        <div className="flex gap-2 flex-wrap shrink-0">

          <div className="flex-1 relative min-w-[120px]">
            <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-xs" />
            <Input
              type="text"
              placeholder="Поиск файла..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs bg-background border-border"
            />
          </div>
          <div className="flex gap-1 flex-wrap">
            {['indexed_used', 'indexed_unused', 'not_indexed', 'stale'].map((status) => (
              <Button
                key={status}
                variant="ghost"
                size="sm"
                onClick={() => toggleStatusFilter(status)}
                className={`h-7 px-2 text-[10px] ${
                  statusFilter.includes(status)
                    ? `${statusBg[status]} border`
                    : 'text-muted-foreground'
                }`}
              >
                {statusLabels[status].split(',')[0]}
              </Button>
            ))}
          </div>
        </div>

        {/* TreeMap */}
        <div className="flex-1" style={{ minHeight: 120 }}>
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <p className="text-muted-foreground text-sm">Загрузка...</p>
            </div>
          ) : treeData.children && treeData.children.length > 0 ? (
            <div style={{ height: treeHeight }}>
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
                label={(d) => (d.width > 40 ? d.data.name : '')}
                labelTextColor="#FFFFFF"
                labelSkipSize={40}
                orientLabel={false}
                onClick={handleClick}
                tooltip={({ node }: { node: any }) => {
                  const n = node.data.node as FileSystemNode | undefined;
                  if (!n) return <div />;
                  return (
                    <div className="bg-card border border-border rounded-xl px-3 py-2 text-xs shadow-lg max-w-[250px]">
                      <div className="font-semibold text-foreground">{n.label}</div>
                      <div className="text-muted-foreground mt-0.5 truncate">{n.id}</div>
                      <div className="flex gap-2 mt-1">
                        <span className="text-muted-foreground">{n.size_kb.toFixed(0)} KB</span>
                        <span className="text-muted-foreground">{n.chunks_count} чанков</span>
                      </div>
                      <div className="mt-0.5">
                        <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ backgroundColor: statusColors[n.status] }} />
                        <span className="text-muted-foreground">{statusLabels[n.status]}</span>
                      </div>
                      {n.used_by_agents && n.used_by_agents.length > 0 && (
                        <div className="mt-1 pt-1 border-t border-border/50">
                          <span className="text-muted-foreground">Агенты: </span>
                          <span className="text-blue-400">{n.used_by_agents.join(', ')}</span>
                        </div>
                      )}
                    </div>
                  );
                }}
                theme={{
                  tooltip: { container: { background: '#131B2A', border: '1px solid #2A3A4E', borderRadius: 12, fontSize: 12 } },
                }}
              />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-muted-foreground text-sm">Нет файлов</p>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        {selectedFile && (
          <div className="p-3 rounded-xl bg-background border border-border text-xs space-y-1.5 shrink-0">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm">{selectedFile.label}</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] ${
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
            <div className="text-muted-foreground">{selectedFile.id}</div>
            <div className="grid grid-cols-2 gap-2">
              <div><span className="text-muted-foreground">Размер: </span>{selectedFile.size_kb.toFixed(1)} KB</div>
              <div><span className="text-muted-foreground">Чанков: </span>{selectedFile.chunks_count}</div>
              <div><span className="text-muted-foreground">Изменён: </span>{new Date(selectedFile.last_modified).toLocaleDateString('ru-RU')}</div>
              <div><span className="text-muted-foreground">Индексирован: </span>{selectedFile.last_indexed ? new Date(selectedFile.last_indexed).toLocaleDateString('ru-RU') : '—'}</div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleIndexFile(selectedFile.id)}
              disabled={actionLoading === selectedFile.id}
              className="h-7 text-[10px] border-border text-muted-foreground hover:text-white mt-1"
            >
              <FiUpload className={`text-xs mr-1 ${actionLoading === selectedFile.id ? 'animate-pulse' : ''}`} />
              {actionLoading === selectedFile.id ? '...' : 'Индексировать'}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
