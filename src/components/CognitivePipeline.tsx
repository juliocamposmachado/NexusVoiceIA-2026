import { Brain } from "lucide-react";
import type { CognitivePhase } from "@/types";

export function CognitivePipeline({ phases }: { phases: CognitivePhase[] }) {
  return (
    <div className="nexus-card p-5">
      <div className="flex items-center gap-2 mb-4">
        <Brain className="w-4 h-4 text-violet-400" />
        <h3 className="text-sm font-semibold text-slate-200">Pipeline Cognitivo</h3>
      </div>
      <div className="flex items-center gap-0.5 overflow-x-auto scrollbar-thin pb-2">
        {phases.map((phase, idx) => (
          <div key={phase.name} className="flex items-center shrink-0">
            <div
              className={`flex flex-col items-center gap-1.5 px-3 py-2 rounded-lg transition-all ${
                phase.active
                  ? "bg-violet-500/15 border border-violet-500/40 glow-secondary"
                  : phase.completed
                  ? "bg-emerald-500/5 border border-emerald-500/20"
                  : "bg-slate-800/30 border border-slate-800"
              }`}
            >
              <div
                className={`w-2 h-2 rounded-full ${
                  phase.active
                    ? "bg-violet-400 animate-pulse-slow"
                    : phase.completed
                    ? "bg-emerald-400"
                    : "bg-slate-600"
                }`}
              />
              <span
                className={`text-[10px] font-mono whitespace-nowrap ${
                  phase.active
                    ? "text-violet-300"
                    : phase.completed
                    ? "text-emerald-400/80"
                    : "text-slate-600"
                }`}
              >
                {phase.label}
              </span>
            </div>
            {idx < phases.length - 1 && (
              <div
                className={`h-px w-4 ${
                  phase.completed ? "bg-emerald-500/30" : "bg-slate-800"
                }`}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
