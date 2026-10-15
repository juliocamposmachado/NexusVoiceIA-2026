import { useEffect, useRef, useState, useCallback } from "react";
import type { LogEntry, LogLevel, NexusTask, SystemMetric, CognitivePhase } from "@/types";

let idCounter = 0;
const nextId = () => `id-${++idCounter}`;

const INITIAL_TASKS: NexusTask[] = [
  {
    id: nextId(),
    timestamp: Date.now() - 42000,
    request: "verificar status do sistema",
    action: "STATUS",
    group: "A",
    status: "completed",
    response: "Sistema operacional Linux 6.9.12 | Uptime: 4h 23m | CPU: 12% | Memória: 3.2GB/16GB",
    durationMs: 820,
    source: "alexa",
    requiresConfirmation: false,
  },
  {
    id: nextId(),
    timestamp: Date.now() - 28000,
    request: "listar arquivos do workspace",
    action: "LISTAR",
    group: "A",
    status: "completed",
    response: "12 arquivos encontrados | lambda/ components/ src/ models/",
    durationMs: 1150,
    source: "alexa",
    requiresConfirmation: false,
  },
  {
    id: nextId(),
    timestamp: Date.now() - 15000,
    request: "executar diagnóstico do ambiente",
    action: "DIAGNOSTICO",
    group: "A",
    status: "completed",
    response: "Python 3.13.0 | Node 20.11.0 | Git 2.43.0 | pip3: 14 pacotes",
    durationMs: 2400,
    source: "manual",
    requiresConfirmation: false,
  },
];

const INITIAL_LOGS: LogEntry[] = [
  { id: nextId(), timestamp: Date.now() - 45000, level: "STEP", source: "NEXUS", message: "Ponte HTTPS iniciada na porta 8443" },
  { id: nextId(), timestamp: Date.now() - 44000, level: "INFO", source: "NEXUS", message: "Workspace autorizado: /home/user/projects" },
  { id: nextId(), timestamp: Date.now() - 43000, level: "INFO", source: "NEXUS", message: "Token de autenticação validado" },
  { id: nextId(), timestamp: Date.now() - 42000, level: "BRAIN", source: "ALEXA", message: "Solicitação recebida: verificar status do sistema" },
  { id: nextId(), timestamp: Date.now() - 41800, level: "EXEC", source: "NEXUS", message: "Executando comando seguro: uname -a" },
  { id: nextId(), timestamp: Date.now() - 41500, level: "RESULT", source: "NEXUS", message: "Comando executado com sucesso (exit 0)" },
  { id: nextId(), timestamp: Date.now() - 28000, level: "BRAIN", source: "ALEXA", message: "Solicitação recebida: listar arquivos do workspace" },
  { id: nextId(), timestamp: Date.now() - 27500, level: "EXEC", source: "NEXUS", message: "Executando: ls -la /home/user/projects" },
  { id: nextId(), timestamp: Date.now() - 27000, level: "RESULT", source: "NEXUS", message: "12 entradas listadas com sucesso" },
  { id: nextId(), timestamp: Date.now() - 15000, level: "STEP", source: "GUI", message: "Diagnóstico iniciado pelo painel" },
  { id: nextId(), timestamp: Date.now() - 14000, level: "EXEC", source: "NEXUS", message: "python3 --version | node --version | git --version" },
  { id: nextId(), timestamp: Date.now() - 13000, level: "RESULT", source: "NEXUS", message: "Diagnóstico concluído: todas as ferramentas OK" },
];

const COGNITIVE_PHASES: CognitivePhase[] = [
  { name: "PERCEPCAO", label: "Percepção", active: false, completed: true },
  { name: "INTERPRETACAO", label: "Interpretação", active: false, completed: true },
  { name: "PLANEJAMENTO", label: "Planejamento", active: false, completed: true },
  { name: "DECISAO", label: "Decisão", active: true, completed: false },
  { name: "EXECUCAO", label: "Execução", active: false, completed: false },
  { name: "VALIDACAO", label: "Validação", active: false, completed: false },
  { name: "CONCLUSAO", label: "Conclusão", active: false, completed: false },
];

const LOG_MESSAGES: { level: LogLevel; source: string; messages: string[] }[] = [
  { level: "INFO", source: "NEXUS", messages: ["Heartbeat OK", "Rate limit: 3/10 req/min", "Workspace acessível"] },
  { level: "STEP", source: "NEXUS", messages: ["Verificando permissões", "Validando entrada do usuário", "Solicitação autenticada"] },
  { level: "BRAIN", source: "COPILOT", messages: ["Analisando contexto", "Decidindo próxima ação", "Avaliando resultado da execução"] },
  { level: "EXEC", source: "NEXUS", messages: ["Executando comando seguro", "Processando tarefa", "Coletando resultado"] },
  { level: "RESULT", source: "NEXUS", messages: ["Operação bem-sucedida", "Comando concluído (exit 0)", "Arquivo validado"] },
  { level: "WARN", source: "NEXUS", messages: ["Timeout próximo do limite", "Rate limit em 80%"] },
];

export function useNexusData() {
  const [tasks, setTasks] = useState<NexusTask[]>(INITIAL_TASKS);
  const [logs, setLogs] = useState<LogEntry[]>(INITIAL_LOGS);
  const [metrics, setMetrics] = useState<SystemMetric[]>([
    { label: "CPU", value: 12, unit: "%", max: 100 },
    { label: "Memória", value: 3.2, unit: "GB", max: 16 },
    { label: "Disco", value: 47, unit: "GB", max: 256 },
    { label: "Rede", value: 1.4, unit: "Mbps", max: 100 },
  ]);
  const [phases] = useState<CognitivePhase[]>(COGNITIVE_PHASES);
  const [bridgeOnline, setBridgeOnline] = useState(true);
  const [autoMode, setAutoMode] = useState(false);
  const logCounter = useRef(0);

  // Simulate periodic metric updates
  useEffect(() => {
    const interval = setInterval(() => {
      setMetrics((prev) =>
        prev.map((m) => {
          const delta = (Math.random() - 0.5) * (m.max * 0.08);
          const newVal = Math.max(0, Math.min(m.max, m.value + delta));
          return { ...m, value: parseFloat(newVal.toFixed(m.unit === "GB" ? 1 : 1)) };
        })
      );
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // Simulate periodic log entries
  useEffect(() => {
    const interval = setInterval(() => {
      const entry = LOG_MESSAGES[Math.floor(Math.random() * LOG_MESSAGES.length)];
      const msg = entry.messages[Math.floor(Math.random() * entry.messages.length)];
      logCounter.current++;
      setLogs((prev) => [
        ...prev.slice(-80),
        { id: `log-${logCounter.current}`, timestamp: Date.now(), level: entry.level, source: entry.source, message: msg },
      ]);
    }, 5000 + Math.random() * 4000);
    return () => clearInterval(interval);
  }, []);

  const addLog = useCallback((level: LogLevel, source: string, message: string) => {
    logCounter.current++;
    setLogs((prev) => [
      ...prev.slice(-80),
      { id: `log-${logCounter.current}`, timestamp: Date.now(), level, source, message },
    ]);
  }, []);

  const addTask = useCallback((task: Omit<NexusTask, "id" | "timestamp">) => {
    const newTask: NexusTask = {
      ...task,
      id: nextId(),
      timestamp: Date.now(),
    };
    setTasks((prev) => [newTask, ...prev].slice(0, 50));
    return newTask;
  }, []);

  const updateTask = useCallback((id: string, updates: Partial<NexusTask>) => {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...updates } : t)));
  }, []);

  const toggleBridge = useCallback(() => {
    setBridgeOnline((prev) => {
      const next = !prev;
      addLog(next ? "INFO" : "WARN", "NEXUS", next ? "Ponte reativada" : "Ponte desativada pelo operador");
      return next;
    });
  }, [addLog]);

  return { tasks, logs, metrics, phases, bridgeOnline, autoMode, addLog, addTask, updateTask, setAutoMode, toggleBridge };
}
