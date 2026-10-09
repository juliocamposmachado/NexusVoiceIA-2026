"""NEXUS Agent Loop — Copilot as brain, NEXUS as executor.

This module implements the iterative agent cycle:
    USER → NEXUS → COPILOT (decides) → NEXUS (executes) → result → COPILOT → ... → CONCLUIR

The Copilot receives the user's request plus a tool inventory, returns one
action at a time, NEXUS executes it, feeds the real result back, and the
loop continues until Copilot returns CONCLUIR.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import ast
from pathlib import Path
from typing import Any, Callable, Optional

# Action types the Copilot can request
VALID_ACTIONS = {
    "RESPONDER",
    "INSPECIONAR",
    "CRIAR",
    "MODIFICAR",
    "EXECUTAR",
    "TESTAR",
    "VALIDAR",
    "FIGMA",
    "PERGUNTAR",
    "CONFIRMAR",
    "CONCLUIR",
}

MAX_LOOP_ITERATIONS = 40

COGNITIVE_PHASES = (
    "PERCEPCAO",
    "INTERPRETACAO",
    "PLANEJAMENTO",
    "DECISAO",
    "EXECUCAO",
    "VALIDACAO",
    "CONCLUSAO",
)

PHASE_COLORS = {
    "PERCEPCAO": "\033[1;34m",
    "INTERPRETACAO": "\033[1;36m",
    "PLANEJAMENTO": "\033[1;35m",
    "DECISAO": "\033[1;33m",
    "EXECUCAO": "\033[1;32m",
    "VALIDACAO": "\033[1;36m",
    "CONCLUSAO": "\033[1;32m",
}

VALID_TRANSITIONS: dict[str, list[str]] = {
    "PERCEPCAO": ["INTERPRETACAO", "PERCEPCAO"],
    "INTERPRETACAO": ["PLANEJAMENTO", "PERCEPCAO", "INTERPRETACAO"],
    "PLANEJAMENTO": ["DECISAO", "INTERPRETACAO", "PLANEJAMENTO"],
    "DECISAO": ["EXECUCAO", "PLANEJAMENTO", "DECISAO", "CONCLUSAO"],
    "EXECUCAO": ["VALIDACAO", "PLANEJAMENTO", "DECISAO", "EXECUCAO"],
    "VALIDACAO": ["CONCLUSAO", "DECISAO", "PLANEJAMENTO", "EXECUCAO", "VALIDACAO"],
    "CONCLUSAO": ["CONCLUSAO"],
}


class CognitiveState:
    """Persistent working memory for a single cognitive cycle.

    Tracks not just WHAT the agent is doing, but WHY, what it expects,
    what actually happened, and what the next step should be.
    """

    def __init__(self, user_request: str) -> None:
        self.user_request: str = user_request
        self.fase_atual: str = "PERCEPCAO"
        self.objetivo: str = ""
        self.intencao: str = ""
        self.contexto: dict[str, Any] = {}
        self.hipotese: str = ""
        self.decisao: str = ""
        self.acao_planejada: str = ""
        self.acao_executada: str = ""
        self.resultado_esperado: str = ""
        self.resultado_obtido: str = ""
        self.evidencias: list[str] = []
        self.confianca: float = 0.0
        self.erros: list[str] = []
        self.pendencias: list[str] = []
        self.motivo_transicao: str = ""
        self.proximo_estado: str = ""
        self.iteration: int = 0
        self._history: list[dict[str, Any]] = []
        self._action_attempts: dict[str, int] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "fase_atual": self.fase_atual,
            "objetivo": self.objetivo,
            "intencao": self.intencao,
            "contexto": self.contexto,
            "hipotese": self.hipotese,
            "decisao": self.decisao,
            "acao_planejada": self.acao_planejada,
            "acao_executada": self.acao_executada,
            "resultado_esperado": self.resultado_esperado,
            "resultado_obtido": self.resultado_obtido,
            "evidencias": list(self.evidencias),
            "confianca": self.confianca,
            "erros": list(self.erros),
            "pendencias": list(self.pendencias),
            "motivo_transicao": self.motivo_transicao,
            "proximo_estado": self.proximo_estado,
            "iteration": self.iteration,
        }

    def snapshot_for_copilot(self) -> dict[str, Any]:
        """Compact state summary sent to Copilot each iteration."""
        d = self.to_dict()
        d["user_request"] = self.user_request
        d["history_summary"] = self._history_summary()
        return d

    def record_transition(self, from_phase: str, to_phase: str, reason: str) -> None:
        entry = {
            "from": from_phase,
            "to": to_phase,
            "reason": reason,
            "iteration": self.iteration,
            "timestamp": _now_iso(),
        }
        self._history.append(entry)

    def _history_summary(self) -> list[dict[str, Any]]:
        return self._history[-12:]

    def record_action_attempt(self, action_key: str) -> int:
        """Track repeated actions to detect loops. Returns attempt count."""
        self._action_attempts[action_key] = self._action_attempts.get(action_key, 0) + 1
        return self._action_attempts[action_key]

    def is_looping(self, action_key: str, threshold: int = 3) -> bool:
        return self._action_attempts.get(action_key, 0) >= threshold

    def add_evidence(self, evidence: str) -> None:
        if evidence and evidence not in self.evidencias:
            self.evidencias.append(evidence)

    def add_error(self, error: str) -> None:
        if error:
            self.erros.append(error)

    def add_pendencia(self, pendencia: str) -> None:
        if pendencia and pendencia not in self.pendencias:
            self.pendencias.append(pendencia)

    def can_transition(self, target: str) -> bool:
        return target in VALID_TRANSITIONS.get(self.fase_atual, [])


class CognitiveStateMachine:
    """Manages phase transitions, loop detection, and state recovery.

    Enforces valid transitions, prevents infinite loops, and provides
    backtracking when validation reveals the plan or interpretation was wrong.
    """

    def __init__(self, user_request: str) -> None:
        self.state = CognitiveState(user_request)
        self.max_retries_per_phase: int = 5
        self._phase_retry_count: dict[str, int] = {}

    def transition_to(self, target: str, reason: str) -> bool:
        """Attempt a phase transition. Returns True if allowed."""
        if target == self.state.fase_atual:
            return True

        if not self.state.can_transition(target):
            return False

        old = self.state.fase_atual
        self.state.record_transition(old, target, reason)
        self.state.fase_atual = target
        self.state.motivo_transicao = reason
        self._print_transition(old, target, reason)
        return True

    def retry_phase(self, reason: str) -> bool:
        """Retry current phase. Returns False if max retries exceeded."""
        phase = self.state.fase_atual
        self._phase_retry_count[phase] = self._phase_retry_count.get(phase, 0) + 1
        if self._phase_retry_count[phase] > self.max_retries_per_phase:
            return False
        self.state.record_transition(phase, phase, f"retry: {reason}")
        return True

    def backtrack(self, target: str, reason: str) -> bool:
        """Backtrack to a previous phase when evidence shows the plan was wrong."""
        if not self.state.can_transition(target):
            return False
        old = self.state.fase_atual
        self.state.record_transition(old, target, f"backtrack: {reason}")
        self.state.fase_atual = target
        self.state.motivo_transicao = f"backtrack: {reason}"
        self.state.add_evidence(f"Backtrack {old}→{target}: {reason}")
        self._print_transition(old, target, f"backtrack: {reason}")
        return True

    def detect_loop(self, action_key: str) -> bool:
        """Returns True if the same action has been attempted too many times."""
        return self.state.is_looping(action_key)

    def _print_transition(self, from_phase: str, to_phase: str, reason: str) -> None:
        color = PHASE_COLORS.get(to_phase, "\033[0m")
        reset = "\033[0m"
        print(
            f"{color}[{to_phase}] {from_phase} → {to_phase} "
            f"| motivo: {reason}{reset}",
            flush=True,
        )

    def print_state(self) -> None:
        """Display current cognitive state for observability."""
        s = self.state
        color = PHASE_COLORS.get(s.fase_atual, "\033[0m")
        reset = "\033[0m"
        print(f"\n{color}{'─' * 50}{reset}")
        print(f"{color}ESTADO COGNITIVO — FASE: {s.fase_atual}{reset}")
        if s.objetivo:
            print(f"  objetivo:            {s.objetivo}")
        if s.intencao:
            print(f"  intenção:            {s.intencao}")
        if s.hipotese:
            print(f"  hipótese:            {s.hipotese}")
        if s.decisao:
            print(f"  decisão:             {s.decisao}")
        if s.acao_planejada:
            print(f"  ação planejada:      {s.acao_planejada}")
        if s.acao_executada:
            print(f"  ação executada:      {s.acao_executada}")
        if s.resultado_esperado:
            print(f"  resultado esperado:  {s.resultado_esperado}")
        if s.resultado_obtido:
            preview = s.resultado_obtido[:200]
            print(f"  resultado obtido:    {preview}")
        if s.evidencias:
            print(f"  evidências:          {len(s.evidencias)}")
            for ev in s.evidencias[-3:]:
                print(f"    - {ev[:120]}")
        if s.erros:
            print(f"  erros:               {len(s.erros)}")
            for er in s.erros[-2:]:
                print(f"    - {er[:120]}")
        if s.confianca > 0:
            print(f"  confiança:           {s.confianca:.0%}")
        if s.pendencias:
            print(f"  pendências:          {len(s.pendencias)}")
        print(f"  iteração:            {s.iteration}")
        print(f"{color}{'─' * 50}{reset}\n", flush=True)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat()


class ToolRegistry:
    """Discovers and inventories capabilities available to the Copilot brain."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._cache: Optional[list[dict[str, Any]]] = None

    def discover(self) -> list[dict[str, Any]]:
        """Returns a list of available tool groups with their capabilities."""
        if self._cache is not None:
            return self._cache

        tools: list[dict[str, Any]] = []

        # Linux terminal
        tools.append({
            "group": "terminal",
            "description": "Executar comandos Linux no terminal real (bash)",
            "capabilities": ["pwd", "ls", "cat", "grep", "find", "df", "du", "free", "ps", "whoami", "uname", "uptime", "head", "tail", "wc", "sort", "uniq", "diff", "chmod", "mkdir", "cp", "mv", "touch"],
        })

        # Filesystem
        tools.append({
            "group": "filesystem",
            "description": "Ler, criar, modificar e inspecionar arquivos e diretórios",
            "capabilities": ["read_file", "write_file", "list_directory", "file_exists", "file_size", "create_directory"],
        })

        # Python execution
        py = shutil.which("python3") or shutil.which("python")
        if py:
            tools.append({
                "group": "python",
                "description": f"Executar scripts Python ({py})",
                "capabilities": ["execute_script", "validate_syntax", "install_dependencies"],
            })

        # Node.js
        node = shutil.which("node")
        if node:
            tools.append({
                "group": "node",
                "description": f"Executar JavaScript/Node.js ({node})",
                "capabilities": ["execute_script", "npm", "npx"],
            })

        # Git
        git = shutil.which("git")
        if git:
            tools.append({
                "group": "git",
                "description": "Operações Git (status, diff, log, add, commit)",
                "capabilities": ["status", "diff", "log", "add", "commit", "branch"],
            })

        # Browser (Copilot itself)
        tools.append({
            "group": "browser",
            "description": "Navegador Microsoft Edge com Copilot integrado",
            "capabilities": ["open_url", "screenshot", "interactive"],
        })

        # Figma MCP
        figma_tools = self._discover_figma()
        if figma_tools:
            tools.append(figma_tools)

        self._cache = tools
        return tools

    def _discover_figma(self) -> Optional[dict[str, Any]]:
        """Discovers Figma MCP availability and tools."""
        try:
            import sys
            base = Path(__file__).resolve().parent
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            from figma_mcp import FigmaMCPClient, ALL_FIGMA_TOOLS  # type: ignore
            client = FigmaMCPClient(self.config)
            diag = client.detect()
            if not diag.get("available"):
                return None
            tool_names = list(ALL_FIGMA_TOOLS.keys()) if ALL_FIGMA_TOOLS else []
            client.close()
            return {
                "group": "figma_mcp",
                "description": f"Figma MCP Server (modo={diag['mode']}) — leitura de designs, assets, variáveis, escrita no canvas",
                "capabilities": tool_names,
            }
        except Exception:
            return None

    def inventory_text(self) -> str:
        """Returns a human-readable inventory for the Copilot prompt."""
        tools = self.discover()
        lines = ["FERRAMENTAS DISPONÍVEIS NO NEXUS:"]
        for t in tools:
            caps = ", ".join(t["capabilities"][:20])
            lines.append(f"  [{t['group']}] {t['description']}")
            lines.append(f"    capacidades: {caps}")
        return "\n".join(lines)


class AgentLoop:
    """The Copilot ↔ NEXUS iterative agent cycle.

    Each iteration:
    1. Build state (user request + tool inventory + conversation history + last result)
    2. Send to Copilot via the BrainClient
    3. Parse the action JSON
    4. Execute the action via the Executor
    5. Collect the result
    6. Feed result back to Copilot in next iteration
    7. Repeat until CONCLUIR or max iterations
    """

    def __init__(
        self,
        brain_ask: Callable[[str, dict[str, Any]], str],
        executor: "ActionExecutor",
        config: dict[str, Any],
    ) -> None:
        self.brain_ask = brain_ask
        self.executor = executor
        self.config = config
        self.history: list[dict[str, Any]] = []
        self.iteration = 0
        self.csm: Optional[CognitiveStateMachine] = None
        self._retry_count: int = 0
        self._max_retries: int = 3

    def run(self, user_request: str, auto_mode: bool = False) -> dict[str, Any]:
        """Execute the full cognitive agent loop. Returns the final conclusion."""
        self.history = []
        self.iteration = 0
        self._retry_count = 0
        self.csm = CognitiveStateMachine(user_request)
        stop_event = self.executor.stop_event

        # Phase 1: PERCEPCAO
        self.csm.transition_to("PERCEPCAO", "Pedido do usuário recebido")
        self.csm.state.objetivo = user_request
        self.csm.print_state()

        # Phase 2: INTERPRETACAO — Copilot interprets intent
        self.csm.transition_to("INTERPRETACAO", "Iniciando interpretação da intenção")
        self._log("USUÁRIO → COPILOT", "STEP")

        while self.iteration < MAX_LOOP_ITERATIONS:
            if stop_event is not None and stop_event.is_set():
                return {"action": "CONCLUIR", "response": "Tarefa interrompida pelo usuário."}

            self.iteration += 1
            self.csm.state.iteration = self.iteration
            self._log(f"ITERAÇÃO {self.iteration} — FASE: {self.csm.state.fase_atual}", "STEP")

            state = self._build_state(user_request, auto_mode)
            raw_response = self.brain_ask("nexus_agente", state)
            action = self._parse_action(raw_response)

            # Detect echo/empty responses where Copilot copied the template
            if self._is_echo_response(action, raw_response):
                self._log("Resposta eco detectada — Copilot copiou o template. Retentando...", "WARN")
                self.csm.state.add_error("Copilot retornou template vazio")
                retry_action: Optional[dict[str, Any]] = None
                if self._retry_count < self._max_retries:
                    self._retry_count += 1
                    retry_state = self._build_retry_state(user_request, auto_mode)
                    raw_retry = self.brain_ask("nexus_agente", retry_state)
                    retry_action = self._parse_action(raw_retry)
                    if self._is_echo_response(retry_action, raw_retry):
                        self._log("Retentativa também ecoou. Mais uma vez com instrução direta.", "WARN")
                        if self._retry_count < self._max_retries:
                            self._retry_count += 1
                            retry_state2 = self._build_retry_state(user_request, auto_mode, force_direct=True)
                            raw_retry2 = self.brain_ask("nexus_agente", retry_state2)
                            retry_action = self._parse_action(raw_retry2)
                        if retry_action is not None and self._is_echo_response(retry_action, ""):
                            self._log("Copilot não respondeu após retentativas. Concluindo.", "WARN")
                            return {
                                "action": "CONCLUIR",
                                "response": "O Copilot não conseguiu decidir uma ação. Tente reformular o pedido.",
                                "reason": "echo_response_exhausted",
                            }
                    action = retry_action

            self._log(f"COPILOT → {action['action']}", "BRAIN")
            if action.get("reason"):
                self._log(f"  motivo: {action['reason']}", "INFO")

            # Track action for loop detection
            action_key = f"{action['action']}:{action.get('path', action.get('command', ''))[:60]}"
            attempt_count = self.csm.state.record_action_attempt(action_key)
            if self.csm.detect_loop(action_key):
                self._log(f"LOOP DETECTADO: {action['action']} repetido {attempt_count}x", "WARN")
                self.csm.state.add_error(f"Loop detectado: ação {action['action']} repetida {attempt_count} vezes")
                self.csm.backtrack("PLANEJAMENTO", "Loop detectado — revisar plano")
                self.csm.print_state()
                continue

            self.history.append({"role": "copilot", "action": action, "iteration": self.iteration})

            if action["action"] == "CONCLUIR":
                # Block premature CONCLUIR if files were created but not validated
                created_files = [
                    e for e in self.csm.state.evidencias if e.startswith("arquivo=")
                ]
                validated_files = [
                    e for e in self.csm.state.evidencias if "bem-sucedida" in e and "VALIDAR" in e
                ]
                if created_files and len(validated_files) < len(created_files):
                    self._log("CONCLUIR bloqueado — arquivos criados sem validação", "WARN")
                    self.csm.state.add_pendencia("Validar arquivos criados antes de concluir")
                    self.csm.backtrack("VALIDACAO", "Arquivos criados sem validação")
                    self.csm.print_state()
                    continue
                self.csm.transition_to("CONCLUSAO", "Copilot determinou conclusão")
                self.csm.state.resultado_obtido = action.get("response", "")
                self.csm.state.confianca = 1.0
                self.csm.print_state()
                return action

            if action["action"] == "RESPONDER":
                response_text = action.get("response", "")
                redirected = self._redirect_code_to_create(action, response_text)
                if redirected is not None:
                    self._log(
                        f"Código lido da resposta → arquivo proposto: {redirected.get('path', '')}",
                        "STEP",
                    )
                    self.csm.state.add_evidence("Código extraído da resposta do Copilot")
                    if not self._confirm_save_action(redirected):
                        return {
                            "action": "CONCLUIR",
                            "response": "O arquivo não foi salvo porque a confirmação foi recusada.",
                            "reason": "save_cancelled",
                        }
                    redirected["_save_approved"] = True
                    action = redirected
                else:
                    self.csm.transition_to("DECISAO", "Copilot enviou uma resposta textual")
                    self.csm.transition_to("CONCLUSAO", "Resposta textual processada")
                    self.csm.state.resultado_obtido = response_text
                    self.csm.state.confianca = 0.9
                    self.csm.print_state()
                    return action

            if action["action"] == "PERGUNTAR":
                question = action.get("question", action.get("response", "Pergunta do Copilot:"))
                self._log(f"COPILOT → PERGUNTAR: {question}", "ASK")
                answer = self.executor.ask_user(question)
                self.csm.state.add_evidence(f"Pergunta: {question[:100]} → Resposta: {answer[:100]}")
                self.history.append({"role": "user", "response": answer, "iteration": self.iteration})
                continue

            if action["action"] == "CONFIRMAR":
                prompt = action.get("question", action.get("response", "Confirma?"))
                approved = self.executor.confirm(prompt)
                result = {"approved": approved, "status": "ok" if approved else "cancelled"}
                self.csm.state.add_evidence(f"Confirmação: {'aprovado' if approved else 'recusado'}")
                self.history.append({"role": "nexus", "result": result, "iteration": self.iteration})
                continue

            # Move through cognitive phases for executable actions
            self._advance_phase_for_action(action)

            # Ask before writing files. The generated content stays in memory until approved.
            if action["action"] in ("CRIAR", "MODIFICAR") and not self._confirm_save_action(action):
                result = {
                    "status": "cancelled",
                    "error": "Usuário recusou salvar o arquivo.",
                    "path": action.get("path", ""),
                }
                self._log("SALVAMENTO CANCELADO PELO USUÁRIO", "WARN")
            else:
                self._log(f"AÇÃO → {action['action']}", "EXEC")
                self.csm.state.acao_planejada = action["action"]
                result = self.executor.execute(action)
            self._log(f"RESULTADO → {result['status']}", "RESULT")

            # Update cognitive state with results
            self.csm.state.acao_executada = action["action"]
            if result.get("output"):
                preview = result["output"][:500]
                self._log(f"  saída: {preview}", "INFO")
                self.csm.state.resultado_obtido = result["output"][:500]
            if result.get("error"):
                self._log(f"  erro: {result['error'][:300]}", "WARN")
                self.csm.state.add_error(result["error"][:200])

            # Record evidence
            if result.get("exit_code") is not None:
                self.csm.state.add_evidence(f"exit_code={result['exit_code']}")
            if result.get("path"):
                self.csm.state.add_evidence(f"arquivo={result['path']}")

            # Move to VALIDACAO
            self.csm.transition_to("VALIDACAO", "Ação executada — verificando resultado")
            self.csm.state.resultado_esperado = action.get("reason", "")

            # Evaluate: did the action succeed?
            if result["status"] == "ok":
                self.csm.state.confianca = min(1.0, self.csm.state.confianca + 0.2)
                self.csm.state.add_evidence(f"Ação {action['action']} bem-sucedida")

                # Auto-validate after CRIAR or MODIFICAR
                if action["action"] in ("CRIAR", "MODIFICAR") and result.get("path"):
                    self._log(f"Auto-validando arquivo criado: {result['path']}", "STEP")
                    val_result = self.executor.execute({
                        "action": "VALIDAR",
                        "path": result["path"],
                        "reason": "Validação automática após criação",
                    })
                    val_status = val_result.get("status", "error")
                    self._log(f"VALIDAÇÃO → {val_status}", "RESULT")
                    if val_status == "ok":
                        self.csm.state.add_evidence(f"VALIDAR bem-sucedida: {result['path']}")
                    else:
                        self.csm.state.add_error(f"Validação falhou: {val_result.get('error', '')}")
                        self.csm.state.add_pendencia(f"Corrigir arquivo: {result['path']}")

                self.csm.transition_to("DECISAO", "Resultado validado — aguardando próxima decisão do Copilot")
            else:
                self.csm.state.confianca = max(0.0, self.csm.state.confianca - 0.3)
                self.csm.state.add_error(f"Falha na ação {action['action']}")
                # Backtrack to DECISAO for Copilot to diagnose and correct
                self.csm.transition_to("DECISAO", "Falha detectada — Copilot deve diagnosticar e corrigir")

            self.csm.print_state()
            self.history.append({"role": "nexus", "result": result, "iteration": self.iteration})

        return {"action": "CONCLUIR", "response": "Limite de iterações atingido.", "reason": "max_iterations"}

    def _advance_phase_for_action(self, action: dict[str, Any]) -> None:
        """Advance cognitive state phases based on the action type."""
        s = self.csm.state

        # First executable action: complete INTERPRETACAO → PLANEJAMENTO → DECISAO
        if s.fase_atual == "INTERPRETACAO":
            s.intencao = action.get("reason", "")
            self.csm.transition_to("PLANEJAMENTO", "Interpretação concluída — decompondo em etapas")
            s.hipotese = action.get("reason", "")

        if s.fase_atual == "PLANEJAMENTO":
            self.csm.transition_to("DECISAO", "Plano formulado — escolhendo ação")

        if s.fase_atual == "DECISAO":
            s.decisao = action["action"]
            self.csm.transition_to("EXECUCAO", "Decisão tomada — executando ação")

    def _confirm_save_action(self, action: dict[str, Any]) -> bool:
        """Ask permission before persisting generated content to the filesystem."""
        if action.get("_save_approved") is True:
            return True
        path = str(action.get("path", "")).strip()
        content = str(action.get("content", ""))
        if not path or not content:
            return False
        prompt = (
            f"O Copilot gerou um arquivo de {len(content)} caracteres.\n"
            f"Nome sugerido: {Path(path).name}\n"
            f"Diretório escolhido: {Path(path).parent}\n"
            "Deseja salvar nesse local?"
        )
        approved = self.executor.confirm(prompt)
        if approved:
            action["_save_approved"] = True
            self._log(f"SALVAMENTO AUTORIZADO: {path}", "STEP")
        return approved

    def _redirect_code_to_create(self, action: dict[str, Any], response_text: str) -> Optional[dict[str, Any]]:
        """Detect code in a RESPONDER action and redirect to CRIAR.

        Returns a CRIAR action dict if code is detected, None otherwise.
        """
        if not response_text or len(response_text) < 50:
            return None

        # Detect HTML
        if re.search(r"<(?:html|!DOCTYPE|head|body|div|section|header|footer)\b", response_text, re.I):
            return self._build_create_from_code(response_text, "html")

        # Detect CSS blocks (substantial style content)
        if re.search(r"(?:^|\n)\s*(?:[.#]?[\w-]+\s*\{[^}]*\}|@media|@import)", response_text) and len(response_text) > 100:
            return self._build_create_from_code(response_text, "css")

        # Detect JavaScript/TypeScript
        if re.search(r"(?:function\s+\w+|const\s+\w+\s*=|class\s+\w+|import\s+|export\s+|=>\s*\{)", response_text) and len(response_text) > 100:
            return self._build_create_from_code(response_text, "js")

        # Detect Python
        if re.search(r"(?:^|\n)\s*(?:def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import)", response_text) and len(response_text) > 100:
            return self._build_create_from_code(response_text, "python")

        return None

    def _build_create_from_code(self, code: str, language: str) -> dict[str, Any]:
        """Build a CRIAR action from detected code content."""
        # Determine filename based on language
        cwd = self.executor.environment_info().get("cwd", os.getcwd())
        extensions = {
            "html": "index.html",
            "css": "styles.css",
            "js": "script.js",
            "python": "script.py",
        }
        filename = extensions.get(language, "output.txt")
        filepath = str(Path(cwd) / filename)

        # Strip markdown fences if present
        content = code
        if content.startswith("```"):
            lines = content.split("\n")
            if len(lines) > 1:
                content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3].strip()

        # Strip trailing conversation text (anything after the code block)
        if language == "html" and "</html>" in content:
            content = content[:content.index("</html>") + len("</html>")]

        return {
            "action": "CRIAR",
            "path": filepath,
            "content": content,
            "language": language,
            "reason": f"Código {language} detectado na resposta — redirecionado de RESPONDER para CRIAR",
        }

    def _build_state(self, user_request: str, auto_mode: bool) -> dict[str, Any]:
        """Builds the state dict sent to Copilot, including cognitive state."""
        inventory = self.executor.tool_registry.inventory_text()
        env_info = self.executor.environment_info()
        history_summary = self._summarize_history()

        state = {
            "user_request": user_request,
            "auto_mode": auto_mode,
            "iteration": self.iteration,
            "tool_inventory": inventory,
            "environment": env_info,
            "conversation_history": history_summary,
            "last_result": self.history[-1]["result"] if self.history and self.history[-1].get("result") else None,
        }

        # Include cognitive state when available
        if self.csm is not None:
            state["cognitive_state"] = self.csm.state.snapshot_for_copilot()

        return state

    def _is_echo_response(self, action: dict[str, Any], raw: str) -> bool:
        """Detect when Copilot copied the prompt template with empty values."""
        # All meaningful fields empty
        has_content = any(
            str(action.get(k, "")).strip()
            for k in ("response", "command", "path", "content", "question")
        )
        if has_content:
            return False

        # Check if reason matches the template example text
        reason = str(action.get("reason", "")).strip().lower()
        template_phrases = {
            "explicação curta e objetiva da decisão",
            "explicacao curta e objetiva da decisao",
            "explicação curta da decisão",
            "explicacao curta da decisao",
        }
        if reason in template_phrases:
            return True

        # If action is RESPONDER with empty response and empty reason
        if action.get("action") == "RESPONDER" and not has_content and not reason:
            return True

        return False

    def _build_retry_state(self, user_request: str, auto_mode: bool, force_direct: bool = False) -> dict[str, Any]:
        """Build a simplified, more direct state for retry after echo."""
        env_info = self.executor.environment_info()
        cwd = env_info.get("cwd", os.getcwd())

        if force_direct:
            # Ultra-direct: minimal context, maximum instruction clarity
            return {
                "user_request": user_request,
                "auto_mode": auto_mode,
                "iteration": self.iteration,
                "environment": {"cwd": cwd},
                "instruction": (
                    f"O usuário pediu: \"{user_request}\". "
                    f"Você deve decidir a PRÓXIMA AÇÃO agora. "
                    f"Se precisa ver o ambiente, use INSPECIONAR com command=\"pwd && ls\". "
                    f"Se já sabe o que fazer, use CRIAR com path (caminho completo), "
                    f"content (código completo) e language. "
                    f"NÃO retorne o template com valores vazios. "
                    f"Preencha TODOS os campos com conteúdo real. "
                    f"O campo reason deve ter a explicação real da sua decisão."
                ),
                "last_result": self.history[-1]["result"] if self.history and self.history[-1].get("result") else None,
            }

        return {
            "user_request": user_request,
            "auto_mode": auto_mode,
            "iteration": self.iteration,
            "tool_inventory": self.executor.tool_registry.inventory_text(),
            "environment": env_info,
            "conversation_history": self._summarize_history(),
            "last_result": self.history[-1]["result"] if self.history and self.history[-1].get("result") else None,
            "retry_warning": (
                "SUA RESPOSTA ANTERIOR FOI UM TEMPLATE VAZIO. "
                "Você copiou o formato JSON com todos os campos vazios. "
                "Isso é um erro. Agora você deve responder com conteúdo real. "
                "Decida uma ação concreta e preencha os campos com dados reais. "
                f"O usuário quer: {user_request}"
            ),
        }

    def _summarize_history(self) -> list[dict[str, Any]]:
        """Returns a compact summary of the conversation so far."""
        summary: list[dict[str, Any]] = []
        for entry in self.history[-10:]:  # Last 10 entries
            if entry["role"] == "copilot":
                action = entry["action"]
                summary.append({
                    "iteration": entry["iteration"],
                    "role": "copilot",
                    "action": action["action"],
                    "reason": action.get("reason", ""),
                })
            elif entry["role"] == "nexus":
                result = entry["result"]
                summary.append({
                    "iteration": entry["iteration"],
                    "role": "nexus",
                    "status": result.get("status", ""),
                    "output_preview": str(result.get("output", ""))[:200],
                    "error": result.get("error", ""),
                })
            elif entry["role"] == "user":
                summary.append({
                    "iteration": entry["iteration"],
                    "role": "user",
                    "response": entry["response"][:200],
                })
        return summary

    def _parse_action(self, raw: str) -> dict[str, Any]:
        """Parses Copilot's response into a validated action dict."""
        text = str(raw or "").strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text
            if text.endswith("```"):
                text = text[:-3].strip()

        # Try JSON parse
        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(text[i:])
                    if isinstance(obj, dict):
                        return self._validate_action(obj)
                except (json.JSONDecodeError, ValueError):
                    continue

        # Preserve natural responses so HTML/CSS/JS blocks can be extracted.
        if text:
            return {
                "action": "RESPONDER",
                "response": text,
                "reason": "Resposta natural recebida; conteúdo será analisado antes de salvar.",
            }
        return {
            "action": "RESPONDER",
            "response": "",
            "reason": "Resposta vazia do Copilot.",
        }

    def _validate_action(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Validates and normalizes the action dict from Copilot."""
        action = str(obj.get("action", "")).strip().upper()
        if action not in VALID_ACTIONS:
            # Try to infer from common alternatives
            if obj.get("response") and not obj.get("command") and not obj.get("content"):
                action = "RESPONDER"
            elif obj.get("command"):
                action = "EXECUTAR"
            elif obj.get("content") and obj.get("path"):
                action = "CRIAR"
            else:
                action = "RESPONDER"

        result: dict[str, Any] = {"action": action}
        for key in ("response", "command", "path", "content", "language", "reason", "question", "tool", "params", "search_pattern", "framework"):
            if key in obj and obj[key] is not None:
                result[key] = obj[key]
        return result

    def _log(self, message: str, level: str = "INFO") -> None:
        """Observability output to terminal."""
        colors = {
            "STEP": "\033[1;36m",
            "BRAIN": "\033[1;35m",
            "EXEC": "\033[1;33m",
            "RESULT": "\033[1;32m",
            "ASK": "\033[1;36m",
            "WARN": "\033[33m",
            "INFO": "\033[0m",
        }
        color = colors.get(level, "\033[0m")
        print(f"{color}[NEXUS] {message}\033[0m")


class ActionExecutor:
    """Executes actions decided by the Copilot brain.

    Each method returns a dict with at minimum:
        {"status": "ok"|"error", "output": str, "error": str, "exit_code": int|None}
    """

    def __init__(
        self,
        pty: Any,
        config: dict[str, Any],
        stop_event: Any = None,
        figma_client: Any = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.pty = pty
        self.config = config
        self.stop_event = stop_event
        self.figma = figma_client
        self.tool_registry = tool_registry or ToolRegistry(config)
        self._confirm_callback: Optional[Callable[[str], bool]] = None
        self._ask_callback: Optional[Callable[[str], str]] = None

    def set_confirm_callback(self, cb: Callable[[str], bool]) -> None:
        self._confirm_callback = cb

    def set_ask_callback(self, cb: Callable[[str], str]) -> None:
        self._ask_callback = cb

    def environment_info(self) -> dict[str, Any]:
        """Collects real environment info for the Copilot."""
        info: dict[str, Any] = {
            "cwd": str(self.pty.cwd) if hasattr(self.pty, "cwd") else os.getcwd(),
            "shell": str(getattr(self.pty, "shell", os.environ.get("SHELL", "/bin/bash"))),
        }
        try:
            info["home"] = str(Path.home())
        except Exception:
            pass
        try:
            info["user"] = os.environ.get("USER", "")
        except Exception:
            pass
        try:
            info["python_version"] = "{}.{}.{}".format(*sys_version_tuple())
        except Exception:
            pass
        for tool in ("node", "npm", "npx", "git", "python3", "pip3"):
            path = shutil.which(tool)
            if path:
                info[tool] = path
        return info

    def confirm(self, prompt: str) -> bool:
        if self._confirm_callback:
            return self._confirm_callback(prompt)
        return True

    def ask_user(self, question: str) -> str:
        if self._ask_callback:
            return self._ask_callback(question)
        return ""

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        """Dispatches an action to the appropriate executor method."""
        action_type = action.get("action", "")

        if action_type == "RESPONDER":
            return {"status": "ok", "output": action.get("response", ""), "action": "RESPONDER"}

        if action_type == "INSPECIONAR":
            return self._inspect(action)

        if action_type == "CRIAR":
            return self._create_file(action)

        if action_type == "MODIFICAR":
            return self._modify_file(action)

        if action_type == "EXECUTAR":
            return self._execute_command(action)

        if action_type == "TESTAR":
            return self._test(action)

        if action_type == "VALIDAR":
            return self._validate(action)

        if action_type == "FIGMA":
            return self._figma(action)

        return {"status": "error", "error": f"Ação desconhecida: {action_type}", "action": action_type}

    def _inspect(self, action: dict[str, Any]) -> dict[str, Any]:
        """Inspect filesystem, environment, or run a read-only command."""
        path = action.get("path")
        command = action.get("command")

        if command:
            return self._run_command(command, dangerous_check=True)

        if path:
            p = Path(path).expanduser()
            if not p.exists():
                return {"status": "error", "error": f"Caminho não existe: {p}"}
            if p.is_dir():
                try:
                    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                    lines = []
                    for item in items[:200]:
                        prefix = "DIR " if item.is_dir() else "FILE"
                        size = item.stat().st_size if item.is_file() else 0
                        lines.append(f"{prefix} {item.name:<40} {size:>10}")
                    return {"status": "ok", "output": "\n".join(lines), "path": str(p)}
                except (OSError, PermissionError) as exc:
                    return {"status": "error", "error": str(exc)}
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    max_chars = int(self.config.get("max_output_chars", 8000))
                    return {"status": "ok", "output": content[:max_chars], "path": str(p), "size": p.stat().st_size}
                except (OSError, PermissionError) as exc:
                    return {"status": "error", "error": str(exc)}

        # Default: inspect current directory
        return self._run_command("pwd && ls -la", dangerous_check=True)

    def _create_file(self, action: dict[str, Any]) -> dict[str, Any]:
        """Create a file with the given content."""
        path = action.get("path")
        content = action.get("content", "")
        if not path:
            return {"status": "error", "error": "CRIAR requer o campo path."}

        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.pty.cwd if hasattr(self.pty, "cwd") else os.getcwd()) / p

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content), encoding="utf-8")
            return {"status": "ok", "output": f"Arquivo criado: {p} ({p.stat().st_size} bytes)", "path": str(p)}
        except (OSError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def _modify_file(self, action: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing file — full content replacement."""
        path = action.get("path")
        content = action.get("content", "")
        if not path:
            return {"status": "error", "error": "MODIFICAR requer o campo path."}

        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(self.pty.cwd if hasattr(self.pty, "cwd") else os.getcwd()) / p

        if not p.exists():
            return {"status": "error", "error": f"Arquivo não existe: {p}"}

        try:
            old_content = p.read_text(encoding="utf-8", errors="replace")
            p.write_text(str(content), encoding="utf-8")
            return {
                "status": "ok",
                "output": f"Arquivo modificado: {p}",
                "path": str(p),
                "old_size": len(old_content),
                "new_size": p.stat().st_size,
            }
        except (OSError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def _execute_command(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute a shell command via PTY."""
        command = action.get("command")
        if not command:
            return {"status": "error", "error": "EXECUTAR requer o campo command."}
        return self._run_command(command, dangerous_check=True)

    def _test(self, action: dict[str, Any]) -> dict[str, Any]:
        """Run a test — either a script or a command."""
        path = action.get("path")
        command = action.get("command")

        if path:
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = Path(self.pty.cwd if hasattr(self.pty, "cwd") else os.getcwd()) / p
            if not p.exists():
                return {"status": "error", "error": f"Arquivo não existe: {p}"}
            if p.suffix == ".py":
                return self._run_command(f"python3 {p}", dangerous_check=False)
            if command:
                return self._run_command(command, dangerous_check=True)
            return self._run_command(f"chmod +x {p} && {p}", dangerous_check=True)

        if command:
            return self._run_command(command, dangerous_check=True)

        return {"status": "error", "error": "TESTAR requer path ou command."}

    def _validate(self, action: dict[str, Any]) -> dict[str, Any]:
        """Validate a file or result."""
        path = action.get("path")
        if path:
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = Path(self.pty.cwd if hasattr(self.pty, "cwd") else os.getcwd()) / p
            if not p.exists():
                return {"status": "error", "error": f"Arquivo não existe: {p}"}
            if p.suffix == ".py":
                try:
                    source = p.read_text(encoding="utf-8", errors="replace")
                    ast.parse(source)
                    result = subprocess.run(
                        [sys_executable(), "-m", "py_compile", str(p)],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        return {"status": "ok", "output": f"Python válido: {p}", "exit_code": 0}
                    return {"status": "error", "error": result.stderr, "exit_code": result.returncode}
                except SyntaxError as exc:
                    return {"status": "error", "error": f"Erro de sintaxe: {exc}", "exit_code": 1}
                except Exception as exc:
                    return {"status": "error", "error": str(exc)}
            # Non-Python file: just check exists and non-empty
            size = p.stat().st_size
            if size > 0:
                return {"status": "ok", "output": f"Arquivo válido: {p} ({size} bytes)", "exit_code": 0}
            return {"status": "error", "error": "Arquivo vazio", "exit_code": 1}

        return {"status": "ok", "output": "Validação sem alvo específico.", "exit_code": 0}

    def _figma(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute a Figma MCP tool call."""
        if self.figma is None:
            return {"status": "error", "error": "Figma MCP indisponível. Configure FIGMA_API_KEY ou NEXUS_FIGMA_MCP_URL."}

        tool_name = action.get("tool", "")
        params = action.get("params", {})
        if not tool_name:
            return {"status": "error", "error": "FIGMA requer o campo tool (nome da ferramenta Figma MCP)."}

        try:
            result = self.figma.call_tool(tool_name, params if isinstance(params, dict) else {})
            self.figma.close()
            return result
        except Exception as exc:
            return {"status": "error", "error": f"Figma MCP erro: {exc}"}

    def _run_command(self, command: str, dangerous_check: bool = True) -> dict[str, Any]:
        """Run a command via PTY with danger checking."""
        if dangerous_check and _is_dangerous_external(command):
            if not self.confirm(f"COMANDO POTENCIALMENTE PERIGOSO: {command}\nExecutar?"):
                return {"status": "error", "error": "Comando cancelado pelo usuário.", "cancelled": True}

        try:
            timeout = int(self.config.get("terminal_timeout", 300))
            output, exit_code = self.pty.run_command(command, timeout=timeout)
            max_chars = int(self.config.get("max_output_chars", 8000))
            return {
                "status": "ok" if exit_code == 0 else "error",
                "output": (output or "")[:max_chars],
                "exit_code": exit_code,
                "command": command,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "command": command}


def _is_dangerous_external(command: str) -> bool:
    """Checks if a command matches dangerous patterns."""
    import re
    normalized = re.sub(r"\s+", " ", command).strip().lower()
    dangerous = [
        r"\brm\s+-rf\s+/",
        r"\bmkfs\b",
        r"\bwipefs\b",
        r"\bdd\s+.*\bof=/dev/",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bpoweroff\b",
        r":\(\)\s*\{",
        r"\bchmod\s+777\s+/$",
    ]
    return any(re.search(pat, normalized) for pat in dangerous)


def sys_version_tuple() -> tuple[int, int, int]:
    import sys
    return sys.version_info[0], sys.version_info[1], sys.version_info[2]


def sys_executable() -> str:
    import sys
    return sys.executable
