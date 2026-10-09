"""NEXUS ChatGPT Agent Loop — ChatGPT as brain, NEXUS as executor.

This module implements an iterative agent cycle where ChatGPT (via browser)
generates code and commands in phases, the user approves each step (yes/no/auto),
and NEXUS executes them in a real terminal.

Flow:
    USER → NEXUS → CHATGPT (generates code/command) → USER (yes/no/auto) → NEXUS (executes) → result → CHATGPT → ... → DONE
"""

from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional


PHASE_LABELS = {
    1: "ANALISE",
    2: "PLANEJAMENTO",
    3: "GERACAO",
    4: "APROVACAO",
    5: "EXECUCAO",
    6: "VALIDACAO",
    7: "CONCLUSAO",
}

PHASE_COLORS = {
    "ANALISE": "\033[1;34m",
    "PLANEJAMENTO": "\033[1;36m",
    "GERACAO": "\033[1;35m",
    "APROVACAO": "\033[1;33m",
    "EXECUCAO": "\033[1;32m",
    "VALIDACAO": "\033[1;36m",
    "CONCLUSAO": "\033[1;32m",
}

MAX_PHASE_ITERATIONS = 30

# Patterns that indicate ChatGPT page noise, not actual response content.
_NOISE_PATTERNS = [
    re.compile(r"^Show more\s*$", re.MULTILINE),
    re.compile(r"^More options\s*$", re.MULTILINE),
    re.compile(r"^Think\s*$", re.MULTILINE),
    re.compile(r"^ChatGPT can make mistakes.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Check important info.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Ad\s*$", re.MULTILINE),
    re.compile(r"^HostGator.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Crie seu Site com IA.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Mesmo sem saber nada.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Para colocar .* no ar.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^[Uu]ma opção de hospedagem.*$", re.MULTILINE),
    # Prompt echo — ChatGPT sometimes shows the prompt we sent
    re.compile(r"^Você é um agente desenvolvedor.*$", re.MULTILINE),
    re.compile(r"^O NEXUS executa seus comandos.*$", re.MULTILINE),
    re.compile(r"^Solicitação do usuário:.*$", re.MULTILINE),
    re.compile(r"^Diretório atual:.*$", re.MULTILINE),
    re.compile(r"^\d+\.\s+(?:Analise|Para criar|Para executar|Envie|Quando|NÃO)\b.*$", re.MULTILINE),
    re.compile(r"^Instruções:.*$", re.MULTILINE),
    re.compile(r"^Continuando a tarefa:.*$", re.MULTILINE),
    re.compile(r"^Histórico de ações.*$", re.MULTILINE),
    re.compile(r"^Arquivos criados até agora:.*$", re.MULTILINE),
    re.compile(r"^Erros recentes:.*$", re.MULTILINE),
    re.compile(r"^Último resultado:.*$", re.MULTILINE),
    re.compile(r"^Qual é a PRÓXIMA ação\?.*$", re.MULTILINE),
    re.compile(r"^Se terminou.*$", re.MULTILINE),
]

# Language labels that ChatGPT uses for code blocks
_LANG_MAP = {
    "python": "python", "py": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "html": "html",
    "css": "css",
    "bash": "bash", "sh": "bash", "shell": "bash",
    "json": "json",
    "text": "text", "plaintext": "text",
}


class PhaseState:
    """Tracks the current phase, history, and results for one task."""

    def __init__(self, user_request: str) -> None:
        self.user_request: str = user_request
        self.current_phase: int = 1
        self.iteration: int = 0
        self.history: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.files_created: list[str] = []

    @property
    def phase_name(self) -> str:
        return PHASE_LABELS.get(self.current_phase, "DESCONHECIDO")

    def advance_phase(self) -> None:
        if self.current_phase < 7:
            self.current_phase += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_request": self.user_request,
            "current_phase": self.current_phase,
            "phase_name": self.phase_name,
            "iteration": self.iteration,
            "history": self.history[-8:],
            "results": self.results[-4:],
            "errors": self.errors[-3:],
            "files_created": self.files_created,
        }


class ResponseCleaner:
    """Cleans raw browser response by removing page noise and prompt echoes."""

    @classmethod
    def clean(cls, raw: str) -> str:
        """Remove noise patterns and return clean text."""
        text = raw or ""

        # Remove known noise patterns
        for pattern in _NOISE_PATTERNS:
            text = pattern.sub("", text)

        # Remove lines that are just UI labels (NOT language labels like Bash/HTML)
        ui_labels = {"Show more", "More options", "Think", "Ad", "Copy", "Regenerate"}
        code_labels = {"Bash", "Shell", "Sh", "HTML", "Python", "Py", "JavaScript", "JS", "TypeScript", "TS", "CSS", "JSON"}
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in ui_labels:
                continue
            # Keep language labels — they mark code blocks in ChatGPT's UI
            if stripped in code_labels:
                cleaned_lines.append(line)
                continue
            cleaned_lines.append(line)

        text = "\n".join(cleaned_lines)

        # Collapse excessive blank lines
        text = re.sub(r"\n{4,}", "\n\n\n", text)

        return text.strip()


class ChatGPTActionParser:
    """Parses ChatGPT responses into structured actions.

    Key fix: code/command extraction happens BEFORE "done" detection.
    This prevents the parser from matching "TAREFA CONCLUÍDA" in echoed
    prompt text when the response actually contains code.
    """

    DEFAULT_NAMES = {
        "python": "script.py",
        "py": "script.py",
        "javascript": "script.js",
        "js": "script.js",
        "typescript": "script.ts",
        "ts": "script.ts",
        "html": "index.html",
        "css": "styles.css",
        "bash": "script.sh",
        "sh": "script.sh",
        "json": "data.json",
    }

    @classmethod
    def parse_all(cls, response: str, cwd: str) -> list[dict[str, Any]]:
        """Parse a ChatGPT response into a list of actions.

        Extracts ALL code blocks and commands found, in order.
        Only returns "done" or "answer" if NO code/command was found.

        Returns a list of action dicts.
        """
        text = ResponseCleaner.clean(response)
        if not text:
            return [{"type": "answer", "content": ""}]

        # FIRST: extract all code blocks and commands
        actions: list[dict[str, Any]] = []

        # Extract all fenced code blocks
        code_blocks = cls._extract_all_code_blocks(text)
        for language, content in code_blocks:
            if language in ("bash", "sh", "shell"):
                # Bash blocks are commands, not files
                cmd = content.strip()
                if cmd:
                    # Multiple lines = multiple commands joined
                    cmd_lines = [l.strip() for l in cmd.splitlines() if l.strip() and not l.strip().startswith("#")]
                    if cmd_lines:
                        actions.append({
                            "type": "command",
                            "command": " && ".join(cmd_lines),
                        })
            else:
                # Code block = file to create
                filename = cls._detect_filename(text, language, cwd)
                actions.append({
                    "type": "code",
                    "language": language,
                    "content": content,
                    "path": filename,
                })

        # If we found code blocks, return them — do NOT check for "done"
        if actions:
            return actions

        # No code blocks found. Check for unfenced code (HTML without fences)
        unfenced = cls._detect_unfenced_code(text)
        if unfenced:
            language, content = unfenced
            filename = cls._detect_filename(text, language, cwd)
            return [{
                "type": "code",
                "language": language,
                "content": content,
                "path": filename,
            }]

        # No code at all. Check for "done" signal.
        if cls._is_done_signal(text):
            return [{"type": "done", "content": cls._extract_done_text(text)}]

        # Check if there's a standalone command (not in a code block)
        command = cls._extract_standalone_command(text)
        if command:
            return [{"type": "command", "command": command}]

        # Just a conversational answer
        return [{"type": "answer", "content": text}]

    @classmethod
    def parse(cls, response: str, cwd: str) -> dict[str, Any]:
        """Parse and return the first action (backwards compat)."""
        actions = cls.parse_all(response, cwd)
        return actions[0] if actions else {"type": "answer", "content": ""}

    @classmethod
    def _extract_all_code_blocks(cls, text: str) -> list[tuple[str, str]]:
        """Extract ALL code blocks from the text.

        Handles two formats:
        1. Standard fenced: ```language\\ncode```
        2. ChatGPT web UI: language label on its own line (Bash, HTML, Python)
           followed by the code until the next label or end of text.

        Returns a list of (language, content) tuples in order of appearance.
        """
        blocks: list[tuple[str, str]] = []

        # Format 1: Standard fenced blocks
        fence_pattern = re.compile(
            r"```(\w+)?\s*\n(.*?)```",
            re.DOTALL,
        )
        for match in fence_pattern.finditer(text):
            lang_raw = (match.group(1) or "text").lower().strip()
            language = _LANG_MAP.get(lang_raw, lang_raw)
            content = match.group(2).strip()
            if content and len(content) > 5:
                blocks.append((language, content))

        # Format 2: ChatGPT web UI label-based blocks
        # Labels appear on their own line: "Bash", "HTML", "Python", etc.
        # Code follows until the next blank line + label, or noise pattern
        if not blocks:
            blocks = cls._extract_label_based_blocks(text)

        return blocks

    @classmethod
    def _extract_label_based_blocks(cls, text: str) -> list[tuple[str, str]]:
        """Extract code blocks that use ChatGPT's label format.

        ChatGPT's web UI shows code like:
            Bash
            mkdir -p /path

            HTML
            <!DOCTYPE html>
            ...

        The label is a known language name on its own line, followed by code.
        """
        label_re = re.compile(
            r"^(Bash|Shell|Sh|HTML|Python|Py|JavaScript|JS|TypeScript|TS|CSS|JSON)\s*$",
            re.MULTILINE,
        )

        # Find all label positions
        labels = []
        for match in label_re.finditer(text):
            label = match.group(1).strip()
            pos = match.end()
            labels.append((label, pos))

        if not labels:
            return []

        blocks: list[tuple[str, str]] = []

        # Noise markers that signal end of a code block
        noise_re = re.compile(
            r"^(Show more|More options|Think|Ad|HostGator|Crie seu|Mesmo sem|"
            r"Para colocar|Uma opção|ChatGPT can|Check important|"
            r"Você é um|O NEXUS|Solicitação|Diretório|Instruções|"
            r"\d+\.\s+(?:Analise|Para criar|Para executar|Envie|Quando|NÃO)|"
            r"Continuando|Histórico|Arquivos criados|Erros recentes|"
            r"Último resultado|Qual a PRÓXIMA|Se terminou)",
            re.MULTILINE | re.IGNORECASE,
        )

        for i, (label_raw, start_pos) in enumerate(labels):
            lang_lower = label_raw.lower()
            language = _LANG_MAP.get(lang_lower, lang_lower)

            # End position: next label start, or end of text
            if i + 1 < len(labels):
                next_label_match = label_re.search(text, start_pos)
                end_pos = next_label_match.start() if next_label_match else len(text)
            else:
                end_pos = len(text)

            # Also check for noise markers within the block
            noise_match = noise_re.search(text, start_pos, end_pos)
            if noise_match:
                end_pos = noise_match.start()

            content = text[start_pos:end_pos].strip()

            # Skip if content is too short or looks like noise
            if content and len(content) > 3:
                # For bash, strip trailing blank lines and noise
                if language in ("bash", "sh", "shell"):
                    # Keep only actual command lines
                    cmd_lines = []
                    for line in content.splitlines():
                        stripped = line.strip()
                        if not stripped:
                            if cmd_lines:
                                break
                            continue
                        if noise_re.match(stripped):
                            break
                        cmd_lines.append(stripped)
                    content = "\n".join(cmd_lines).strip()

                if content and len(content) > 3:
                    blocks.append((language, content))

        return blocks

    @classmethod
    def _detect_unfenced_code(cls, text: str) -> Optional[tuple[str, str]]:
        """Detect substantial code without fences."""
        if len(text) < 80:
            return None

        # HTML — must have both opening and closing tags to be real code
        if re.search(r"<(?:html|!DOCTYPE)\b", text, re.I) and "</html>" in text:
            start_idx = text.index("<")
            if "!" in text[start_idx:start_idx+10] or "<html" in text[start_idx:start_idx+20].lower():
                content = text[start_idx:]
                if "</html>" in content:
                    content = content[:content.index("</html>") + len("</html>")]
                return ("html", content.strip())

        if re.search(r"(?:^|\n)\s*(?:def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import)", text):
            return ("python", text.strip())

        if re.search(r"(?:function\s+\w+|const\s+\w+\s*=|class\s+\w+|=>\s*\{)", text):
            return ("javascript", text.strip())

        return None

    @classmethod
    def _detect_filename(cls, text: str, language: str, cwd: str) -> str:
        """Try to find a filename mentioned in the response, else use default."""
        name_pattern = re.compile(
            r"(?:arquivo|file|nome|name|salvar|save|criar|create)[:\s]+"
            r"[\w./-]+\.\w+",
            re.I,
        )
        match = name_pattern.search(text)
        if match:
            found = match.group(0).split(":")[-1].strip().split()[-1]
            if "." in found and not found.endswith("."):
                return str(Path(cwd) / found) if not Path(found).is_absolute() else found

        # For HTML, use index.html in a project folder based on the request
        default_name = cls.DEFAULT_NAMES.get(language, "output.txt")
        return str(Path(cwd) / default_name)

    @classmethod
    def _is_done_signal(cls, text: str) -> bool:
        """Check if the response signals task completion.

        Only matches 'TAREFA CONCLUÍDA' as a standalone phrase, NOT when
        it appears inside quoted instructions or prompt echoes.
        """
        # Must appear as a standalone line or heading, not in quotes
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Skip lines that are quoting instructions
            if "'" in stripped and "diga" in stripped.lower():
                continue
            if "instru" in stripped.lower():
                continue
            # Check for done phrases as standalone statements
            lower = stripped.lower()
            done_phrases = [
                "tarefa concluída", "tarefa concluida",
                "projeto concluído", "projeto concluido",
                "nada mais a fazer",
                "concluído com sucesso", "concluido com sucesso",
                "all done", "task complete",
                "tarefa finalizada", "trabalho concluído",
            ]
            for phrase in done_phrases:
                if phrase in lower and len(stripped) < 100:
                    return True
        return False

    @classmethod
    def _extract_done_text(cls, text: str) -> str:
        """Extract a clean completion message."""
        # Find the line with the done phrase and include a few lines after
        lines = text.split("\n")
        for i, line in enumerate(lines):
            lower = line.strip().lower()
            if any(p in lower for p in ["tarefa concluída", "tarefa concluida", "all done"]):
                # Include this line and up to 3 lines after
                end = min(i + 4, len(lines))
                return "\n".join(lines[i:end]).strip()
        return "Tarefa concluída pelo ChatGPT."

    @classmethod
    def _extract_standalone_command(cls, text: str) -> Optional[str]:
        """Extract a shell command not in a code block."""
        patterns = [
            re.compile(r"(?:comando|command|executar|execute|rodar|run)[:\s]+```(?:bash|sh)?\s*\n(.*?)```", re.DOTALL | re.I),
            re.compile(r"^\s*(?:\$|>)\s*(.+)$", re.MULTILINE),
        ]
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                cmd = match.group(1).strip().strip("`").strip()
                if cmd and len(cmd) > 2:
                    if "\n" in cmd:
                        cmd = cmd.split("\n")[0].strip()
                    return cmd
        return None


class ApprovalMode:
    """Approval modes for the agent loop."""

    MANUAL = "manual"
    AUTO = "auto"

    @staticmethod
    def prompt(action: dict[str, Any], auto_mode: bool, action_index: int, total: int) -> tuple[str, str]:
        """Ask the user for approval. Returns (decision, new_mode).

        decision: 'yes', 'no', 'auto', 'edit'
        new_mode: current mode, possibly upgraded to auto
        """
        if auto_mode:
            return ("yes", ApprovalMode.AUTO)

        action_type = action.get("type", "")
        counter = f" [{action_index}/{total}]" if total > 1 else ""

        if action_type == "code":
            preview = action.get("content", "")[:400]
            path = action.get("path", "")
            prompt_text = (
                f"\n\033[1;33m[APROVAÇÃO]{counter}\033[0m\n"
                f"  ChatGPT gerou um arquivo ({action.get('language', '?')}): {Path(path).name}\n"
                f"  Caminho: {path}\n"
                f"  Prévia ({len(action.get('content', ''))} chars):\n"
                f"  {preview}{'...' if len(action.get('content', '')) > 400 else ''}\n"
                f"\n  [s]im  [n]ão  [a]uto (aprovar tudo)  [e]ditar"
            )
        elif action_type == "command":
            cmd = action.get("command", "")
            prompt_text = (
                f"\n\033[1;33m[APROVAÇÃO]{counter}\033[0m\n"
                f"  ChatGPT quer executar o comando:\n"
                f"  $ {cmd}\n"
                f"\n  [s]im  [n]ão  [a]uto (aprovar tudo)"
            )
        else:
            return ("yes", ApprovalMode.MANUAL)

        print(prompt_text)
        choice = input("> ").strip().lower()

        if choice in {"a", "auto"}:
            return ("yes", ApprovalMode.AUTO)
        if choice in {"s", "sim", "y", "yes"}:
            return ("yes", ApprovalMode.MANUAL)
        if choice in {"e", "editar", "edit"} and action_type == "code":
            return ("edit", ApprovalMode.MANUAL)
        return ("no", ApprovalMode.MANUAL)


class ChatGPTAgentLoop:
    """Iterative agent loop with ChatGPT as the brain.

    Each iteration:
    1. Build context (user request + phase + history + last result)
    2. Send to ChatGPT via DirectChatBrowser
    3. Parse the response into actions (code/command/answer/done)
    4. For each action: ask user for approval (yes/no/auto) unless in auto mode
    5. Execute the action via PTY
    6. Feed result back to ChatGPT
    7. Repeat until done or max iterations
    """

    def __init__(
        self,
        chatgpt_ask: Callable[[str], str],
        pty: Any,
        config: dict[str, Any],
        stop_event: Any = None,
    ) -> None:
        self.chatgpt_ask = chatgpt_ask
        self.pty = pty
        self.config = config
        self.stop_event = stop_event
        self.state: Optional[PhaseState] = None

    def run(self, user_request: str, auto_mode: bool = False) -> dict[str, Any]:
        """Execute the full ChatGPT-brained agent loop."""
        self.state = PhaseState(user_request)
        current_auto = auto_mode

        self._print_phase("ANALISE", f"Solicitação recebida: {user_request[:120]}")
        self._print_phase("PLANEJAMENTO", "Enviando para ChatGPT analisar e planejar...")

        while self.state.iteration < MAX_PHASE_ITERATIONS:
            if self.stop_event is not None and self.stop_event.is_set():
                return {"action": "done", "response": "Tarefa interrompida pelo usuário."}

            self.state.iteration += 1
            self._print_phase("GERACAO", f"Iteração {self.state.iteration} — aguardando ChatGPT...")

            prompt = self._build_prompt(user_request, current_auto)
            raw_response = self.chatgpt_ask(prompt)

            if not raw_response or not raw_response.strip():
                self.state.errors.append("ChatGPT retornou resposta vazia")
                self._print_phase("VALIDACAO", "Resposta vazia — retentando...")
                continue

            cwd = str(getattr(self.pty, "cwd", os.getcwd()))
            actions = ChatGPTActionParser.parse_all(raw_response, cwd)

            if not actions:
                self.state.errors.append("Parser não extraiu nenhuma ação")
                continue

            # Process each action from the response
            for idx, action in enumerate(actions):
                if self.stop_event is not None and self.stop_event.is_set():
                    return {"action": "done", "response": "Tarefa interrompida."}

                self._print_action(action, idx + 1, len(actions))

                if action["type"] == "done":
                    self._print_phase("CONCLUSAO", action.get("content", "Tarefa concluída."))
                    return {
                        "action": "done",
                        "response": action.get("content", "Tarefa concluída pelo ChatGPT."),
                        "iterations": self.state.iteration,
                        "files_created": self.state.files_created,
                    }

                if action["type"] == "answer":
                    content = action.get("content", "")
                    if content:
                        print(f"\n\033[1;36m[CHATGPT]\033[0m\n{content[:500]}")
                    self._print_phase("CONCLUSAO", "ChatGPT enviou uma resposta textual.")
                    return {
                        "action": "answer",
                        "response": content,
                        "iterations": self.state.iteration,
                        "files_created": self.state.files_created,
                    }

                # Approval phase
                self._print_phase("APROVACAO", "Aguardando aprovação do usuário...")
                decision, new_mode = ApprovalMode.prompt(action, current_auto, idx + 1, len(actions))
                current_auto = (new_mode == ApprovalMode.AUTO)

                if decision == "no":
                    self._print_phase("EXECUCAO", f"Ação {idx+1} recusada pelo usuário.")
                    self.state.history.append({
                        "iteration": self.state.iteration,
                        "action": action,
                        "result": {"status": "cancelled", "reason": "user_rejected"},
                    })
                    continue

                if decision == "edit":
                    edited = self._edit_content(action.get("content", ""))
                    if edited:
                        action["content"] = edited

                # Execution phase
                self._print_phase("EXECUCAO", f"Executando ação {idx+1}/{len(actions)}...")
                result = self._execute_action(action)
                self._print_result(result)

                self.state.results.append(result)
                self.state.history.append({
                    "iteration": self.state.iteration,
                    "action": action,
                    "result": result,
                })

                if result.get("status") == "ok":
                    if result.get("path"):
                        self.state.files_created.append(result["path"])
                    self._print_phase("VALIDACAO", "Ação executada com sucesso.")
                else:
                    self.state.errors.append(result.get("error", "Erro desconhecido"))
                    self._print_phase("VALIDACAO", f"Falha: {result.get('error', '')[:120]}")

            # After processing all actions in this response, continue to next iteration
            # ChatGPT will decide the next step based on results

        return {
            "action": "done",
            "response": "Limite de iterações atingido.",
            "iterations": self.state.iteration,
            "files_created": self.state.files_created,
        }

    def _build_prompt(self, user_request: str, auto_mode: bool) -> str:
        """Build the prompt sent to ChatGPT each iteration."""
        state = self.state
        history_text = ""
        if state.history:
            lines = []
            for entry in state.history[-6:]:
                act = entry["action"]
                res = entry["result"]
                if act["type"] == "code":
                    lines.append(f"  - Criou arquivo: {act.get('path', '')} -> {res.get('status', '')}")
                elif act["type"] == "command":
                    lines.append(f"  - Executou: {act.get('command', '')[:80]} -> {res.get('status', '')}")
                else:
                    lines.append(f"  - {act['type']} -> {res.get('status', '')}")
            history_text = "\n".join(lines)

        errors_text = ""
        if state.errors:
            errors_text = "\n".join(f"  - {e[:120]}" for e in state.errors[-3:])

        files_text = ""
        if state.files_created:
            files_text = "\n".join(f"  - {f}" for f in state.files_created)

        env_text = ""
        try:
            cwd = str(getattr(self.pty, "cwd", os.getcwd()))
            env_text = f"Diretorio atual: {cwd}"
        except Exception:
            pass

        if state.iteration == 1:
            prompt = (
                f"Voce e um agente desenvolvedor trabalhando em um terminal Linux real.\n"
                f"O NEXUS executa seus comandos e cria seus arquivos.\n\n"
                f"Solicitacao do usuario: {user_request}\n\n"
                f"{env_text}\n\n"
                f"Instrucoes:\n"
                f"1. Para criar um arquivo, escreva o codigo completo dentro de uma block ```linguagem\n"
                f"2. Para executar um comando, escreva-o dentro de uma block ```bash\n"
                f"3. Pode enviar varios arquivos e comandos na mesma resposta\n"
                f"4. NAO explique - foque no codigo/comando\n"
                f"5. Quando tudo estiver pronto, escreva: TAREFA CONCLUIDA\n"
            )
        else:
            prompt = (
                f"Continuando a tarefa: {user_request}\n\n"
                f"{env_text}\n\n"
                f"Historico de acoes ({state.iteration - 1} passos):\n{history_text}\n\n"
            )
            if files_text:
                prompt += f"Arquivos criados ate agora:\n{files_text}\n\n"
            if errors_text:
                prompt += f"Erros recentes:\n{errors_text}\n\n"
            prompt += (
                f"Ultimo resultado: {state.results[-1].get('status', '')} - "
                f"{str(state.results[-1].get('output', state.results[-1].get('error', '')))[:200]}\n\n"
                f"Qual a PROXIMA acao? Envie arquivo (```linguagem) ou comando (```bash).\n"
                f"Se terminou, escreva: TAREFA CONCLUIDA\n"
            )

        return prompt

    def _execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute an action and return the result dict."""
        action_type = action.get("type", "")

        if action_type == "code":
            return self._create_file(action)

        if action_type == "command":
            return self._run_command(action.get("command", ""))

        return {"status": "error", "error": f"Tipo de acao desconhecido: {action_type}"}

    def _create_file(self, action: dict[str, Any]) -> dict[str, Any]:
        """Create a file with the given content."""
        path = action.get("path", "")
        content = action.get("content", "")
        if not path or not content:
            return {"status": "error", "error": "Caminho ou conteudo vazio."}

        p = Path(path).expanduser()
        if not p.is_absolute():
            cwd = str(getattr(self.pty, "cwd", os.getcwd()))
            p = Path(cwd) / p

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {
                "status": "ok",
                "output": f"Arquivo criado: {p} ({p.stat().st_size} bytes)",
                "path": str(p),
            }
        except (OSError, PermissionError) as exc:
            return {"status": "error", "error": str(exc)}

    def _run_command(self, command: str) -> dict[str, Any]:
        """Run a shell command via PTY."""
        if not command:
            return {"status": "error", "error": "Comando vazio."}

        if self._is_dangerous(command):
            if not self._confirm_dangerous(command):
                return {"status": "error", "error": "Comando perigoso cancelado.", "cancelled": True}

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

    @staticmethod
    def _is_dangerous(command: str) -> bool:
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
        ]
        return any(re.search(pat, normalized) for pat in dangerous)

    @staticmethod
    def _confirm_dangerous(command: str) -> bool:
        print(f"\n\033[1;31m[PERIGO] Comando potencialmente destrutivo:\033[0m\n  $ {command}")
        answer = input("Confirmar execucao? [s/N]: ").strip().lower()
        return answer in {"s", "sim", "y", "yes"}

    @staticmethod
    def _edit_content(content: str) -> Optional[str]:
        """Open content in the user's editor for manual editing."""
        import tempfile
        editor = os.environ.get("EDITOR", "nano")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tmp", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            os.system(f"{editor} {tmp_path}")
            edited = Path(tmp_path).read_text(encoding="utf-8")
            os.unlink(tmp_path)
            return edited
        except Exception:
            return None

    @staticmethod
    def _print_phase(phase: str, message: str) -> None:
        color = PHASE_COLORS.get(phase, "\033[0m")
        reset = "\033[0m"
        print(f"{color}[{phase}] {message}{reset}", flush=True)

    @staticmethod
    def _print_action(action: dict[str, Any], index: int, total: int) -> None:
        action_type = action.get("type", "")
        counter = f" ({index}/{total})" if total > 1 else ""
        if action_type == "code":
            lang = action.get("language", "?")
            path = action.get("path", "")
            content = action.get("content", "")
            print(f"\n\033[1;35m[CHATGPT -> CODIGO]{counter}\033[0m {lang} -> {Path(path).name} ({len(content)} chars)")
        elif action_type == "command":
            cmd = action.get("command", "")
            print(f"\n\033[1;35m[CHATGPT -> COMANDO]{counter}\033[0m $ {cmd}")
        elif action_type == "answer":
            content = action.get("content", "")
            print(f"\n\033[1;35m[CHATGPT -> RESPOSTA]\033[0m {content[:200]}")

    @staticmethod
    def _print_result(result: dict[str, Any]) -> None:
        status = result.get("status", "")
        color = "\033[1;32m" if status == "ok" else "\033[1;31m"
        reset = "\033[0m"
        output = str(result.get("output", result.get("error", "")))[:300]
        print(f"{color}[RESULTADO] {status.upper()}{reset}")
        if output:
            print(f"  {output}")
