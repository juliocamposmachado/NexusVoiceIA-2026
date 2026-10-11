import { useState } from "react";
import { Send, Loader2, Mic } from "lucide-react";
import type { ActionGroup, LogLevel, NexusTask, TaskStatus } from "@/types";

interface Props {
  onSubmit: (request: string, action: string, group: ActionGroup) => void;
  bridgeOnline: boolean;
  autoMode: boolean;
}

const QUICK_ACTIONS: { label: string; action: string; group: ActionGroup; request: string }[] = [
  { label: "Status", action: "STATUS", group: "A", request: "verificar status do sistema" },
  { label: "Listar", action: "LISTAR", group: "A", request: "listar arquivos do workspace" },
  { label: "Diagnóstico", action: "DIAGNOSTICO", group: "A", request: "executar diagnóstico do ambiente" },
  { label: "Versões", action: "VERSAO", group: "A", request: "verificar versões das ferramentas" },
];

export function TaskInput({ onSubmit, bridgeOnline, autoMode }: Props) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = (request?: string, action?: string, group?: ActionGroup) => {
    const taskRequest = request ?? input;
    if (!taskRequest.trim() || !bridgeOnline || busy) return;

    setBusy(true);
    const finalAction = action ?? "INSPECIONAR";
    const finalGroup = group ?? "A";

    setTimeout(() => {
      onSubmit(taskRequest, finalAction, finalGroup);
      setInput("");
      setBusy(false);
    }, 600 + Math.random() * 800);
  };

  return (
    <div className="nexus-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200">Enviar Solicitação</h3>
        {autoMode && (
          <span className="nexus-badge bg-violet-500/15 text-violet-300 border border-violet-500/30">
            Auto Mode
          </span>
        )}
      </div>

      <div className="flex gap-2 mb-3">
        <div className="flex-1 relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            disabled={!bridgeOnline || busy}
            placeholder="Digite uma solicitação para o NEXUS..."
            className="w-full bg-slate-900/60 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 transition-colors disabled:opacity-50 font-mono"
          />
        </div>
        <button
          onClick={() => handleSubmit()}
          disabled={!bridgeOnline || busy || !input.trim()}
          className="flex items-center gap-2 bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-300 rounded-lg px-4 py-2.5 text-sm font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          Enviar
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-slate-600 mr-1">Ações rápidas:</span>
        {QUICK_ACTIONS.map((qa) => (
          <button
            key={qa.action}
            onClick={() => handleSubmit(qa.request, qa.action, qa.group)}
            disabled={!bridgeOnline || busy}
            className="flex items-center gap-1.5 bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 rounded-md px-2.5 py-1.5 text-xs text-slate-300 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {qa.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1.5 text-xs text-slate-600">
          <Mic className="w-3 h-3" />
          <span>Voz via Alexa</span>
        </div>
      </div>
    </div>
  );
}
