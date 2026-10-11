import { Shield, ShieldCheck, ShieldAlert } from "lucide-react";
import type { PermissionEntry } from "@/types";
import { ACTION_GROUPS } from "@/types";

const PERMISSIONS: PermissionEntry[] = [
  { action: "INSPECIONAR", group: "A", description: "Inspecionar arquivos e diretórios", requiresConfirmation: false, enabled: true },
  { action: "STATUS", group: "A", description: "Consultar status do sistema", requiresConfirmation: false, enabled: true },
  { action: "LISTAR", group: "A", description: "Listar arquivos do workspace", requiresConfirmation: false, enabled: true },
  { action: "DIAGNOSTICO", group: "A", description: "Diagnosticar ambiente", requiresConfirmation: false, enabled: true },
  { action: "VERSAO", group: "A", description: "Verificar versões de ferramentas", requiresConfirmation: false, enabled: true },
  { action: "CRIAR", group: "B", description: "Criar arquivos no workspace", requiresConfirmation: true, enabled: true },
  { action: "MODIFICAR", group: "B", description: "Modificar arquivos existentes", requiresConfirmation: true, enabled: true },
  { action: "TESTAR", group: "B", description: "Executar testes", requiresConfirmation: true, enabled: true },
  { action: "VALIDAR", group: "B", description: "Validar arquivos e código", requiresConfirmation: true, enabled: true },
  { action: "EXECUTAR", group: "C", description: "Executar comandos no terminal", requiresConfirmation: true, enabled: false },
  { action: "INSTALAR", group: "C", description: "Instalar pacotes", requiresConfirmation: true, enabled: false },
  { action: "REMOVER", group: "C", description: "Remover arquivos", requiresConfirmation: true, enabled: false },
  { action: "PUBLICAR", group: "C", description: "Publicar aplicações", requiresConfirmation: true, enabled: false },
  { action: "CONFIGURAR", group: "C", description: "Alterar configurações do sistema", requiresConfirmation: true, enabled: false },
];

function GroupIcon({ group }: { group: "A" | "B" | "C" }) {
  if (group === "A") return <ShieldCheck className="w-4 h-4 text-emerald-400" />;
  if (group === "B") return <Shield className="w-4 h-4 text-amber-400" />;
  return <ShieldAlert className="w-4 h-4 text-red-400" />;
}

export function PermissionsPanel() {
  return (
    <div className="nexus-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200">Permissões de Operação</h3>
        <div className="flex gap-2">
          {(["A", "B", "C"] as const).map((g) => (
            <span key={g} className={`nexus-badge border ${ACTION_GROUPS[g].color}`}>
              {ACTION_GROUPS[g].label}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-1 max-h-[340px] overflow-y-auto scrollbar-thin">
        {PERMISSIONS.map((p) => (
          <div
            key={p.action}
            className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-800/50 transition-colors"
          >
            <GroupIcon group={p.group} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-mono font-medium text-slate-200">{p.action}</span>
                {p.requiresConfirmation && (
                  <span className="text-[10px] text-amber-400/80 font-mono">confirmação</span>
                )}
              </div>
              <p className="text-xs text-slate-500 truncate">{p.description}</p>
            </div>
            <div className={`w-2 h-2 rounded-full ${p.enabled ? "bg-emerald-400" : "bg-slate-600"}`} />
          </div>
        ))}
      </div>
    </div>
  );
}
