export type BridgeStatus = "online" | "offline" | "disabled";

export type ActionGroup = "A" | "B" | "C";

export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export type LogLevel = "INFO" | "WARN" | "ERROR" | "STEP" | "BRAIN" | "EXEC" | "RESULT";

export interface NexusTask {
  id: string;
  timestamp: number;
  request: string;
  action: string;
  group: ActionGroup;
  status: TaskStatus;
  response: string;
  durationMs: number;
  source: "alexa" | "manual" | "system";
  requiresConfirmation: boolean;
}

export interface LogEntry {
  id: string;
  timestamp: number;
  level: LogLevel;
  source: string;
  message: string;
}

export interface SystemMetric {
  label: string;
  value: number;
  unit: string;
  max: number;
}

export interface PermissionEntry {
  action: string;
  group: ActionGroup;
  description: string;
  requiresConfirmation: boolean;
  enabled: boolean;
}

export interface CognitivePhase {
  name: string;
  label: string;
  active: boolean;
  completed: boolean;
}

export const ACTION_GROUPS: Record<ActionGroup, { label: string; color: string; description: string }> = {
  A: { label: "Leitura", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30", description: "Consultas e diagnósticos sem alteração" },
  B: { label: "Reversível", color: "text-amber-400 bg-amber-500/10 border-amber-500/30", description: "Criação e edição com backup" },
  C: { label: "Sensível", color: "text-red-400 bg-red-500/10 border-red-500/30", description: "Operações privilegiadas com confirmação" },
};

export const LOG_COLORS: Record<LogLevel, string> = {
  INFO: "text-slate-400",
  WARN: "text-amber-400",
  ERROR: "text-red-400",
  STEP: "text-cyan-400",
  BRAIN: "text-violet-400",
  EXEC: "text-amber-300",
  RESULT: "text-emerald-400",
};
