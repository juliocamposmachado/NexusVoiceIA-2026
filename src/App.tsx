import { useCallback } from "react";
import { Cpu, Github, BookOpen } from "lucide-react";
import { useNexusData } from "@/useNexusData";
import { SystemMetrics } from "@/components/SystemMetrics";
import { PermissionsPanel } from "@/components/PermissionsPanel";
import { LogViewer } from "@/components/LogViewer";
import { TaskHistory } from "@/components/TaskHistory";
import { CognitivePipeline } from "@/components/CognitivePipeline";
import { TaskInput } from "@/components/TaskInput";
import { BridgeControl } from "@/components/BridgeControl";
<<<<<<< HEAD
import type { ActionGroup } from "@/types";
=======
import type { ActionGroup, LogLevel } from "@/types";
>>>>>>> origin/main

function App() {
  const {
    tasks,
    logs,
    metrics,
    phases,
    bridgeOnline,
    autoMode,
    addLog,
    addTask,
    updateTask,
    setAutoMode,
    toggleBridge,
  } = useNexusData();

  const handleSubmit = useCallback(
    (request: string, action: string, group: ActionGroup) => {
      const requiresConfirmation = group !== "A";
      addLog("BRAIN", "GUI", `Solicitação enviada: ${request}`);

      const task = addTask({
        request,
        action,
        group,
        status: "running",
        response: "",
        durationMs: 0,
        source: "manual",
        requiresConfirmation,
      });

      setTimeout(() => {
        const responses: Record<string, string> = {
          STATUS: "Sistema operacional Linux 6.9.12 | Uptime: 4h 23m | CPU: 14% | Memória: 3.4GB/16GB",
          LISTAR: "14 arquivos encontrados | lambda/ components/ src/ models/ nexus_bridge/",
          DIAGNOSTICO: "Python 3.13.0 | Node 20.11.0 | Git 2.43.0 | pip3: 14 pacotes instalados",
          VERSAO: "Python 3.13.0 | Node 20.11.0 | Git 2.43.0 | npm 10.2.4",
          INSPECIONAR: "Inspeção concluída: diretório acessível, 14 entradas encontradas",
        };

        const duration = Math.floor(600 + Math.random() * 1800);
        updateTask(task.id, {
          status: "completed",
          response: responses[action] ?? "Operação concluída com sucesso.",
          durationMs: duration,
        });
        addLog("RESULT", "NEXUS", `${action} concluído em ${duration}ms`);
      }, 800 + Math.random() * 1200);
    },
    [addLog, addTask, updateTask]
  );

  return (
    <div className="min-h-screen bg-[#0a0e14] text-slate-200 grid-pattern">
      {/* Header */}
      <header className="border-b border-slate-800/80 bg-[#0a0e14]/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 lg:px-6 py-3 flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-500 to-emerald-500 flex items-center justify-center glow-primary">
              <Cpu className="w-5 h-5 text-slate-900" />
            </div>
            <div>
              <h1 className="text-base font-bold text-slate-100 tracking-tight">NEXUS</h1>
              <p className="text-[10px] text-slate-500 font-mono -mt-0.5">Dashboard de Controle</p>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <a
              href="#"
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              <BookOpen className="w-4 h-4" />
              Docs
            </a>
            <a
              href="#"
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              <Github className="w-4 h-4" />
              Repo
            </a>
            <div className="flex items-center gap-1.5 bg-slate-800/50 border border-slate-700/50 rounded-md px-2.5 py-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse-slow" />
              <span className="text-xs font-mono text-slate-400">v1.0.0</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 lg:px-6 py-6 space-y-4">
        {/* Bridge control bar */}
        <BridgeControl
          online={bridgeOnline}
          autoMode={autoMode}
          onToggleBridge={toggleBridge}
          onToggleAuto={() => {
            setAutoMode(!autoMode);
            addLog("STEP", "GUI", `Auto mode ${!autoMode ? "ativado" : "desativado"}` as const as string);
          }}
        />

        {/* System metrics */}
        <SystemMetrics metrics={metrics} />

        {/* Cognitive pipeline */}
        <CognitivePipeline phases={phases} />

        {/* Task input */}
        <TaskInput onSubmit={handleSubmit} bridgeOnline={bridgeOnline} autoMode={autoMode} />

        {/* Two-column layout: tasks + permissions */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TaskHistory tasks={tasks} />
          <PermissionsPanel />
        </div>

        {/* Log viewer */}
        <LogViewer logs={logs} />

        {/* Footer */}
        <footer className="pt-4 pb-8 text-center">
          <p className="text-xs text-slate-600 font-mono">
            NEXUS Terminal — Alexa Skill + Ponte Local Segura |{" "}
            <span className="text-slate-500">pt-BR</span>
          </p>
        </footer>
      </main>
    </div>
  );
}

export default App;
