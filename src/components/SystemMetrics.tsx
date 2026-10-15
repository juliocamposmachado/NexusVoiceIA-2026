import { Activity, Cpu, HardDrive, MemoryStick, Wifi } from "lucide-react";
import type { SystemMetric } from "@/types";

const ICONS: Record<string, typeof Cpu> = {
  CPU: Cpu,
  Memória: MemoryStick,
  Disco: HardDrive,
  Rede: Wifi,
};

const COLORS: Record<string, string> = {
  CPU: "text-cyan-400",
  Memória: "text-emerald-400",
  Disco: "text-amber-400",
  Rede: "text-violet-400",
};

export function SystemMetrics({ metrics }: { metrics: SystemMetric[] }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {metrics.map((m) => {
        const Icon = ICONS[m.label] ?? Activity;
        const color = COLORS[m.label] ?? "text-slate-400";
        const pct = Math.min(100, (m.value / m.max) * 100);
        return (
          <div key={m.label} className="nexus-card p-4 animate-fade-in">
            <div className="flex items-center justify-between mb-3">
              <Icon className={`w-5 h-5 ${color}`} />
              <span className="text-xs font-mono text-slate-500">{m.unit}</span>
            </div>
            <div className="flex items-baseline gap-1.5 mb-2">
              <span className="text-2xl font-bold text-slate-100 font-mono tabular-nums">
                {m.value}
              </span>
              <span className="text-xs text-slate-500">/ {m.max}</span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  pct > 80 ? "bg-red-500" : pct > 60 ? "bg-amber-500" : "bg-emerald-500"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-2">{m.label}</p>
          </div>
        );
      })}
    </div>
  );
}
