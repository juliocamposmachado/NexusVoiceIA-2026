import { Power, Wifi, Zap, ShieldCheck } from "lucide-react";

interface Props {
  online: boolean;
  autoMode: boolean;
  onToggleBridge: () => void;
  onToggleAuto: () => void;
}

export function BridgeControl({ online, autoMode, onToggleBridge, onToggleAuto }: Props) {
  return (
    <div className="nexus-card p-4 flex items-center gap-4">
      <div className="flex items-center gap-2.5">
        <div className={`w-3 h-3 rounded-full ${online ? "bg-emerald-400 animate-pulse-slow" : "bg-red-400"}`} />
        <div>
          <p className="text-sm font-semibold text-slate-200">Ponte NEXUS</p>
          <p className="text-xs text-slate-500 font-mono">HTTPS :8443</p>
        </div>
      </div>

      <div className="h-8 w-px bg-slate-800" />

      <button
        onClick={onToggleBridge}
        className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all ${
          online
            ? "bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-300"
            : "bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300"
        }`}
      >
        <Power className="w-3.5 h-3.5" />
        {online ? "Desativar" : "Ativar"}
      </button>

      <div className="h-8 w-px bg-slate-800" />

      <button
        onClick={onToggleAuto}
        className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all ${
          autoMode
            ? "bg-violet-500/15 border border-violet-500/30 text-violet-300"
            : "bg-slate-800/50 border border-slate-700/50 text-slate-400 hover:text-slate-300"
        }`}
      >
        <Zap className="w-3.5 h-3.5" />
        Auto Mode
      </button>

      <div className="ml-auto flex items-center gap-4">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <Wifi className="w-3.5 h-3.5 text-cyan-400" />
          <span>{online ? "Conectado" : "Offline"}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>Autenticado</span>
        </div>
      </div>
    </div>
  );
}
