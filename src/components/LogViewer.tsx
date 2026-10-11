import { useEffect, useRef } from "react";
import { Terminal } from "lucide-react";
import type { LogEntry } from "@/types";
import { LOG_COLORS } from "@/types";

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString("pt-BR", { hour12: false });
}

export function LogViewer({ logs }: { logs: LogEntry[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="nexus-card flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
        <Terminal className="w-4 h-4 text-cyan-400" />
        <h3 className="text-sm font-semibold text-slate-200">Log do Sistema</h3>
        <span className="ml-auto text-xs font-mono text-slate-500">{logs.length} entradas</span>
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse-slow" />
      </div>
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3 font-mono text-xs space-y-0.5 min-h-[280px] max-h-[420px]"
      >
        {logs.map((log) => (
          <div key={log.id} className="flex items-start gap-2 animate-slide-in">
            <span className="text-slate-600 select-none">{formatTime(log.timestamp)}</span>
            <span className={`font-bold w-14 shrink-0 ${LOG_COLORS[log.level]}`}>
              [{log.level}]
            </span>
            <span className="text-slate-500 w-16 shrink-0">{log.source}</span>
            <span className="text-slate-300">{log.message}</span>
          </div>
        ))}
        <div className="flex items-center gap-1 text-slate-600">
          <span>nexus@local:~$</span>
          <span className="w-2 h-4 bg-cyan-400 animate-blink" />
        </div>
      </div>
    </div>
  );
}
