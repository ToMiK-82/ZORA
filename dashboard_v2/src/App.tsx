import React from 'react';
import TopBar from './components/TopBar';
import SystemHealthGraph from './components/SystemHealthGraph';
import ResourceSparklines from './components/ResourceSparklines';
import AgentExecutionGraph from './components/AgentExecutionGraph';
import RagQualityPanel from './components/RagQualityPanel';
import DataPipeline from './components/DataPipeline';
import FileSystemGraph from './components/FileSystemGraph';
import KnowledgeGraph from './components/KnowledgeGraph';
import AlertBar from './components/AlertBar';

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <main className="p-4">
        <div className="grid grid-cols-12 gap-3">
          {/* Ряд 1 */}
          <div className="col-span-3 min-h-[280px]"><SystemHealthGraph /></div>
          <div className="col-span-3 min-h-[280px]"><ResourceSparklines /></div>
          <div className="col-span-3 min-h-[280px]"><AgentExecutionGraph /></div>
          <div className="col-span-3 min-h-[280px]"><RagQualityPanel /></div>
          {/* Ряд 2 */}
          <div className="col-span-4 min-h-[280px]"><DataPipeline /></div>
          <div className="col-span-4 min-h-[280px]"><KnowledgeGraph /></div>
          <div className="col-span-4 min-h-[280px]"><FileSystemGraph /></div>
        </div>
      </main>
      <AlertBar />
    </div>
  );
}
