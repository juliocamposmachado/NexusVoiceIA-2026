import { Bot, Mic, CheckCircle2, XCircle, Clock, AlertTriangle, Loader2, X } from "lucide-react";
import type { NexusTask } from "@/types";
import { ACTION_GROUPS } from "@/types";

function timeAgo(ts: number): string {
  const sec = Math.floor((Date.now() - ts) / 1000);
  if (sec < 60) return `${sec}s atrás`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m atrás`;
  return `${Math.floor(sec / 3600)}h atrás`;
}

const STATUS_ICONS: Record<string, typeof CheckCircle2> = {
  completed: CheckCircle2,
  failed: XCircle,
  running: Loader2,
  pending: Clock,
  cancelled: X,
};

const STATUS_COLORS: Record<string, string> = {
  completed: "text-emerald-400",
  failed: "text-red-400",
  running: "text-cyan-400",
  pending: "text-amber-400",
  cancelled: "text-slate-500",
};

export function TaskHistory({ tasks }: { tasks: NexusTask[] }) {
  return (
    <div className="nexus-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200">Histórico de Tarefas</h3>
        <span className="text-xs font-mono text-slate-500">{tasks.length} registros</span>
      </div>
      <div className="space-y-2 max-h-[380px] overflow-y-auto scrollbar-thin">
        {tasks.map((task) => {
          const Icon = STATUS_ICONS[task.status] ?? Clock;
          const color = STATUS_COLORS[task.status] ?? "text-slate-400";
          const groupInfo = ACTION_GROUPS[task.group];
          return (
            <div
              key={task.id}
              className="border border-slate-800 rounded-lg p-3 hover:border-slate-700 transition-colors animate-fade-in"
            >
              <div className="flex items-start gap-3">
                <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${color} ${task.status === "running" ? "animate-spin" : ""}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-mono text-slate-200 truncate">{task.request}</span>
                    <span className={`nexus-badge border ${groupInfo.color}`}>
                      {task.action}
                    </span>
                    {task.source === "alexa" && <Mic className="w-3 h-3 text-blue-400" />}
                    {task.source === "manual" && <Bot className="w-3 h-3 text-violet-400" />}
                  </div>
                  {task.response && (
                    <p className="text-xs text-slate-500 mt-1 line-clamp-2">{task.response}</p>
                  )}
                  <div className="flex items-center gap-3 mt-1.5">
                    <span className="text-[10px] text-slate-600 font-mono">{timeAgo(task.timestamp)}</span>
                    <span className="text-[10px] text-slate-600 font-mono">{task.durationMs}ms</span>
                    {task.requiresConfirmation && (
                      <span className="flex items-center gap-0.5 text-[10px] text-amber-400/80">
                        <AlertTriangle className="w-2.5 h-2.5" /> confirmação
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
