import React from 'react';
import GridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import TopBar from './components/TopBar';
import SystemHealthGraph from './components/SystemHealthGraph';
import ResourceSparklines from './components/ResourceSparklines';
import AgentExecutionGraph from './components/AgentExecutionGraph';
import RagQualityPanel from './components/RagQualityPanel';
import DataPipeline from './components/DataPipeline';
import FileSystemGraph from './components/FileSystemGraph';
import KnowledgeGraph from './components/KnowledgeGraph';
import AlertBar from './components/AlertBar';

const defaultLayout = [
  { i: 'system-graph', x: 0, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
  { i: 'resources', x: 3, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
  { i: 'agents', x: 6, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
  { i: 'rag-quality', x: 9, y: 0, w: 3, h: 4, minW: 2, minH: 3 },
  { i: 'data-pipeline', x: 0, y: 4, w: 4, h: 3, minW: 3, minH: 2 },
  { i: 'knowledge-graph', x: 4, y: 4, w: 4, h: 3, minW: 3, minH: 2 },
  { i: 'filesystem', x: 8, y: 4, w: 4, h: 5, minW: 4, minH: 3 },
];

export default function App() {
  const [layout, setLayout] = React.useState(() => {
    try {
      const saved = localStorage.getItem('zora-dashboard-layout');
      return saved ? JSON.parse(saved) : defaultLayout;
    } catch {
      return defaultLayout;
    }
  });

  const handleLayoutChange = (newLayout: any[]) => {
    setLayout(newLayout);
    localStorage.setItem('zora-dashboard-layout', JSON.stringify(newLayout));
  };

  return (
    <div className="min-h-screen bg-zora-bg">
      <TopBar />

      <main className="p-4">
        <GridLayout
          className="layout"
          layout={layout}
          cols={12}
          rowHeight={80}
          width={window.innerWidth - 32}
          onLayoutChange={handleLayoutChange}
          draggableHandle=".drag-handle"
          isResizable={true}
          compactType="vertical"
          margin={[12, 12]}
          containerPadding={[0, 0]}
        >
          <div key="system-graph">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <SystemHealthGraph />
          </div>

          <div key="resources">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <ResourceSparklines />
          </div>

          <div key="agents">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <AgentExecutionGraph />
          </div>

          <div key="rag-quality">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <RagQualityPanel />
          </div>

          <div key="data-pipeline">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <DataPipeline />
          </div>

          <div key="knowledge-graph">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <KnowledgeGraph />
          </div>

          <div key="filesystem">
            <div className="drag-handle h-6 -mt-2 -mx-2 mb-0 rounded-t-xl cursor-grab active:cursor-grabbing flex items-center justify-center text-zora-muted/30 hover:text-zora-muted/60 transition-colors">
              ⋮⋮⋮
            </div>
            <FileSystemGraph />
          </div>
        </GridLayout>
      </main>

      <AlertBar />
    </div>
  );
}
