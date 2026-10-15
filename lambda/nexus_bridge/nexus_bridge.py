# -*- coding: utf-8 -*-
"""Ponte local do NEXUS — componente executado no computador autorizado.

Recebe solicitações autenticadas da AWS Lambda (Skill da Alexa) e as encaminha
ao NEXUS local para execução controlada de tarefas.

Arquitetura:
    Alexa → AWS Lambda → [esta ponte HTTPS] → NEXUS local → resultado → Alexa

Segurança:
1. Recebe apenas solicitações autenticadas (Bearer token).
2. Verifica se a ação está em uma lista de operações permitidas.
3. Rejeita comandos desconhecidos, entradas malformadas e path traversal.
4. Aplica limites de tempo, tamanho e frequência.
5. Exige confirmação explícita para operações destrutivas (Grupo C).
6. Registra operações sem expor segredos.
7. Devolve apenas resultados necessários para a resposta da Alexa.
8. NÃO expõe um terminal shell aberto para a Internet.
9. NÃO executa comandos recebidos diretamente de texto de IA.
10. Pode ser desativado imediatamente via kill flag ou variável de ambiente.

Execução:
    python3 nexus_bridge.py --host 0.0.0.0 --port 8443 --ssl-cert /path/cert.pem --ssl-key /path/key.pem

Variáveis de ambiente:
    NEXUS_BRIDGE_TOKEN    — token de autenticação (compartilhado com a Lambda)
    NEXUS_WORKSPACE       — diretório base autorizado (ex: /home/user/projects)
    NEXUS_AUTHORIZED_ALEXA_USERS — comma-separated Alexa user IDs autorizados
    NEXUS_BRIDGE_DISABLED — se "1" ou "true", desativa a ponte imediatamente
    NEXUS_MAX_REQUESTS_PER_MIN — limite de requisições (padrão: 10)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import ssl
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from collections import defaultdict, deque

logger = logging.getLogger("nexus_bridge")
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────────────────

WORKSPACE = Path(os.environ.get("NEXUS_WORKSPACE", os.getcwd())).resolve()
BRIDGE_TOKEN = os.environ.get("NEXUS_BRIDGE_TOKEN", "")
AUTHORIZED_USERS = [
    uid.strip()
    for uid in os.environ.get("NEXUS_AUTHORIZED_ALEXA_USERS", "").split(",")
    if uid.strip()
]
DISABLED = os.environ.get("NEXUS_BRIDGE_DISABLED", "").lower() in ("1", "true")
MAX_REQUESTS_PER_MIN = int(os.environ.get("NEXUS_MAX_REQUESTS_PER_MIN", "10"))
MAX_TASK_CHARS = 500
MAX_OUTPUT_CHARS = 800
COMMAND_TIMEOUT = 6  # segundos — abaixo do timeout da Lambda

# Ações permitidas por grupo
GROUP_A = {"INSPECIONAR", "DIAGNOSTICO", "STATUS", "VERSAO", "LISTAR"}
GROUP_B = {"CRIAR", "MODIFICAR", "TESTAR", "VALIDAR"}
GROUP_C = {"EXECUTAR", "INSTALAR", "REMOVER", "PUBLICAR", "CONFIGURAR"}
ALL_ACTIONS = GROUP_A | GROUP_B | GROUP_C

# Comandos permitidos por ação (Grupo A — leitura, e Grupo B — reversível)
SAFE_COMMANDS = {
    "STATUS": ["pwd", "whoami", "uname -a", "uptime", "df -h", "free -h", "date"],
    "LISTAR": ["ls -la", "ls -la {workspace}", "find {workspace} -maxdepth 2 -type f"],
    "DIAGNOSTICO": ["python3 --version", "node --version", "git --version", "pip3 list 2>/dev/null | head -20"],
    "VERSAO": ["cat {workspace}/package.json 2>/dev/null || echo 'sem package.json'"],
    "INSPECIONAR": [],  # dinâmico — depende do task_text
}

# Padrões proibidos em qualquer entrada
import re

_FORBIDDEN_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bwipefs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*\bof=/dev/", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bpoweroff\b", re.IGNORECASE),
    re.compile(r":\(\)\s*\{", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\s+/$", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bsu\s+-\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),
    re.compile(r"\bpkill\b", re.IGNORECASE),
    re.compile(r">\s*/dev/sd", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|\s*sh", re.IGNORECASE),
    re.compile(r"\bwget\b.*\|\s*sh", re.IGNORECASE),
    re.compile(r"\.\./", re.IGNORECASE),
    re.compile(r"\bnc\b.*-l", re.IGNORECASE),
    re.compile(r"\bpython\b.*-c\s+.*import\s+os", re.IGNORECASE),
    re.compile(r"\beval\b", re.IGNORECASE),
    re.compile(r"\bexec\b\s*\(", re.IGNORECASE),
]


# ──────────────────────────────────────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────────────────────────────────────


class RateLimiter:
    """Limita requisições por user_id usando janela deslizante de 60s."""

    def __init__(self, max_per_min: int) -> None:
        self.max_per_min = max_per_min
        self._requests: Dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, user_id: str) -> bool:
        now = time.time()
        with self._lock:
            dq = self._requests[user_id]
            while dq and dq[0] < now - 60:
                dq.popleft()
            if len(dq) >= self.max_per_min:
                return False
            dq.append(now)
            return True


rate_limiter = RateLimiter(MAX_REQUESTS_PER_MIN)


# ──────────────────────────────────────────────────────────────────────────────
# Validação
# ──────────────────────────────────────────────────────────────────────────────


def contains_forbidden(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _FORBIDDEN_PATTERNS)


def is_within_workspace(path: Path) -> bool:
    """Verifica se um caminho está dentro do workspace autorizado."""
    try:
        resolved = path.resolve()
<<<<<<< HEAD
        return resolved.is_relative_to(WORKSPACE)
=======
        return str(resolved).startswith(str(WORKSPACE))
>>>>>>> origin/main
    except (OSError, ValueError):
        return False


def validate_request(payload: Dict[str, Any]) -> tuple[bool, str, str]:
    """Valida a requisição recebida da Lambda.

    Retorna (válido, user_id, mensagem_erro).
    """
    # Lê env vars dinamicamente para permitir patches em testes
    disabled = os.environ.get("NEXUS_BRIDGE_DISABLED", "").lower() in ("1", "true")
    bridge_token = os.environ.get("NEXUS_BRIDGE_TOKEN", "")
    authorized_users = [
        uid.strip()
        for uid in os.environ.get("NEXUS_AUTHORIZED_ALEXA_USERS", "").split(",")
        if uid.strip()
    ]

    if disabled:
        return False, "", "A ponte do NEXUS está desativada."

    if not bridge_token:
        return False, "", "Token da ponte não configurado."

    task = str(payload.get("task", "")).strip()
    if not task:
        return False, "", "Tarefa vazia."
    if len(task) > MAX_TASK_CHARS:
        return False, "", "Tarefa excede o tamanho máximo."

    if contains_forbidden(task):
        logger.warning("Padrão proibido detectado: task_len=%d", len(task))
        return False, "", "Padrão proibido detectado na solicitação."

    user_id = str(payload.get("user_id", "")).strip()

<<<<<<< HEAD
    # Classifica a ação antes de decidir a autorização.
    action_hint = str(payload.get("action_hint", "auto")).upper().strip()
    if action_hint == "AUTO":
        action_hint = _infer_action(task)
    group = classify_action(action_hint)

    # Ações desconhecidas não executam comandos; process_task trata esse caso.
    # Grupo A: somente leitura, disponível sem lista de usuários.
    if group == "A":
        return True, user_id, ""

    # Grupos B e C: negar por padrão se a lista estiver vazia,
    # o usuário não informar ID ou o ID não estiver autorizado.
    if group in ("B", "C"):
        if not authorized_users or not user_id or user_id not in authorized_users:
            logger.warning("Operação restrita negada: usuário ausente ou não autorizado.")
            return False, user_id, "Usuário não autorizado para esta operação."
=======
    # Verifica se o usuário está na lista de autorizados (se houver lista)
    if authorized_users and user_id and user_id not in authorized_users:
        logger.warning("Usuário não autorizado: %s...", user_id[:30])
        return False, user_id, "Usuário não autorizado."
>>>>>>> origin/main

    return True, user_id, ""


def classify_action(action_hint: str) -> str:
    """Classifica a ação em A, B, C ou UNKNOWN."""
    action = action_hint.upper().strip()
    if action in GROUP_A:
        return "A"
    if action in GROUP_B:
        return "B"
    if action in GROUP_C:
        return "C"
    return "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────────────
# Executor seguro — NUNCA executa comandos arbitrários da IA
# ──────────────────────────────────────────────────────────────────────────────


def execute_safe_command(command: str) -> Dict[str, Any]:
    """Executa um comando seguro pré-aprovado com timeout e limites.

    NUNCA executa comandos recebidos diretamente do texto da solicitação.
    Apenas comandos da lista SAFE_COMMANDS ou derivados validados.
    """
<<<<<<< HEAD
    # Aceita somente comandos estáticos definidos na allowlist do próprio código.
    allowed_commands = {
        item
        for commands in SAFE_COMMANDS.values()
        for item in commands
    }
    if command not in allowed_commands or contains_forbidden(command):
        return {"status": "error", "response": "Comando rejeitado por segurança."}

    # O placeholder é substituído por um caminho citado para o shell.
    import shlex
    safe_cmd = command.replace("{workspace}", shlex.quote(str(WORKSPACE)))
=======
    if contains_forbidden(command):
        return {"status": "error", "response": "Comando rejeitado por segurança."}

    # Substitui placeholder do workspace
    safe_cmd = command.replace("{workspace}", str(WORKSPACE))
>>>>>>> origin/main

    try:
        result = subprocess.run(
            safe_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            cwd=str(WORKSPACE),
        )
        output = (result.stdout or result.stderr or "").strip()
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "..."

        if result.returncode == 0:
            return {"status": "ok", "response": output or "Comando executado com sucesso."}
        return {
            "status": "error",
            "response": f"Comando falhou (código {result.returncode}). {output[:200]}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "response": "Comando excedeu o tempo limite."}
    except Exception as exc:
        return {"status": "error", "response": f"Erro ao executar: {type(exc).__name__}"}


def process_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa a tarefa recebida e retorna resposta para a Alexa.

    Mapeia ações para comandos seguros pré-aprovados.
    Para ações do Grupo C, retorna requires_confirmation=true.
    """
    action_hint = str(payload.get("action_hint", "auto")).upper().strip()
    task_text = str(payload.get("task", "")).strip()

    # Se action_hint é "auto", tenta inferir da tarefa
    if action_hint == "auto":
        action_hint = _infer_action(task_text)

    group = classify_action(action_hint)

    if group == "UNKNOWN":
        # Tenta responder como informação genérica
        return {
            "status": "ok",
            "response": f"Recebi sua solicitação: {task_text[:100]}. "
            f"No entanto, não consegui identificar uma ação permitida. "
            f"Tente ser mais específico.",
        }

    # Grupo C — sempre exige confirmação
    if group == "C":
        logger.info("Operação Grupo C solicitada: %s", action_hint)
        return {
            "status": "ok",
            "response": f"Operação sensível detectada: {action_hint}. "
            f"Confirmação necessária no app do NEXUS para prosseguir.",
            "requires_confirmation": True,
            "action": action_hint,
        }

    # Grupos A e B — executa comandos seguros
    if action_hint in SAFE_COMMANDS and SAFE_COMMANDS[action_hint]:
        commands = SAFE_COMMANDS[action_hint]
        outputs = []
        for cmd in commands:
            result = execute_safe_command(cmd)
            if result["status"] == "ok":
                outputs.append(result["response"])
            else:
                outputs.append(result["response"])

        combined = " | ".join(outputs)
        if len(combined) > MAX_OUTPUT_CHARS:
            combined = combined[:MAX_OUTPUT_CHARS] + "..."

        return {
            "status": "ok",
            "response": combined,
            "action": action_hint,
        }

    # INSPECIONAR com tarefa específica — apenas leitura de arquivo/diretório
    if action_hint == "INSPECIONAR":
        return _inspect_task(task_text)

    return {
        "status": "ok",
        "response": "Operação processada, mas sem comando específico para executar.",
        "action": action_hint,
    }


def _infer_action(task_text: str) -> str:
    """Inferência simples de ação a partir do texto da tarefa."""
    lower = task_text.lower()
    if any(w in lower for w in ["status", "estado", "como está", "funcionando"]):
        return "STATUS"
    if any(w in lower for w in ["listar", "lista", "arquivos", "quais arquivos", "mostrar"]):
        return "LISTAR"
    if any(w in lower for w in ["diagnóstico", "diagnostico", "diagnosticar", "verificar ambiente"]):
        return "DIAGNOSTICO"
    if any(w in lower for w in ["versão", "versao", "version"]):
        return "VERSAO"
    if any(w in lower for w in ["inspecionar", "ver", "examinar", "olhar"]):
        return "INSPECIONAR"
    if any(w in lower for w in ["cancelar", "parar", "abortar"]):
        return "CANCELAR"
    return "INSPECIONAR"  # padrão seguro — leitura


def _inspect_task(task_text: str) -> Dict[str, Any]:
<<<<<<< HEAD
    """Inspeciona arquivos usando Python, sem passar caminhos ao shell."""
    words = task_text.split()
    candidates = [w.strip(".,;\\\"'") for w in words if "/" in w or "." in w]

    if not candidates:
        target = WORKSPACE
    else:
        target = None
        for candidate in candidates:
            path = Path(candidate)
            if not path.is_absolute():
                path = WORKSPACE / path
            try:
                path = path.resolve()
                if is_within_workspace(path) and path.exists():
                    target = path
                    break
            except (OSError, ValueError):
                continue

        if target is None:
            return {
                "status": "ok",
                "response": "Não encontrei o caminho solicitado dentro do workspace autorizado.",
            }

    try:
        if not is_within_workspace(target):
            return {"status": "error", "response": "Caminho fora do workspace autorizado."}

        if target.is_dir():
            entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
            output = "\\n".join(
                ("d " if item.is_dir() else "f ") + item.name
                for item in entries[:80]
            )
            output = output or "Diretório vazio."
        elif target.is_file():
            output = "\\n".join(target.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()[:50])
            output = output or "Arquivo vazio."
        else:
            return {"status": "error", "response": "O caminho não é um arquivo nem diretório."}

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "..."
        return {"status": "ok", "response": output}
    except (OSError, PermissionError) as exc:
        logger.warning("Falha na inspeção: %s", type(exc).__name__)
        return {"status": "error", "response": "Não foi possível ler o caminho solicitado."}
=======
    """Executa inspeção de leitura baseada na tarefa (apenas caminhos do workspace)."""
    # Tenta extrair um caminho da tarefa
    words = task_text.split()
    candidate_paths = [w for w in words if "/" in w or "." in w]

    if not candidate_paths:
        # Sem caminho específico — lista workspace
        return execute_safe_command(f"ls -la {WORKSPACE}")

    # Valida cada caminho candidato
    for candidate in candidate_paths:
        candidate = candidate.strip(".,;\"'")
        path = Path(candidate)
        if not path.is_absolute():
            path = WORKSPACE / path
        if not is_within_workspace(path):
            continue
        if path.exists():
            if path.is_dir():
                return execute_safe_command(f"ls -la {path}")
            if path.is_file():
                return execute_safe_command(f"head -50 {path}")

    return {
        "status": "ok",
        "response": "Não encontrei o caminho solicitado dentro do workspace autorizado.",
    }
>>>>>>> origin/main


# ──────────────────────────────────────────────────────────────────────────────
# HTTP Server
# ──────────────────────────────────────────────────────────────────────────────


class NexusBridgeHandler(BaseHTTPRequestHandler):
    """Handler HTTP para a ponte do NEXUS."""

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _verify_token(self) -> bool:
        """Verifica o token Bearer no header Authorization."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:]
        return hmac.compare_digest(token, BRIDGE_TOKEN)

    def do_OPTIONS(self) -> None:
        """Responde a preflight CORS."""
        self._send_json(200, {"status": "ok"})

    def do_GET(self) -> None:
        """Endpoint de health check — sem expor dados."""
        if DISABLED:
            self._send_json(503, {"status": "disabled"})
            return
        self._send_json(200, {"status": "ok", "service": "nexus-bridge"})

    def do_POST(self) -> None:
        """Endpoint principal — recebe solicitações da Lambda."""
        if DISABLED:
            self._send_json(503, {"status": "disabled", "response": "Ponte desativada."})
            return

        if not self._verify_token():
            logger.warning("Token inválido recebido")
            self._send_json(401, {"status": "unauthorized", "response": "Não autorizado."})
            return

        # Lê o body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 10000:
                self._send_json(413, {"status": "error", "response": "Payload muito grande."})
                return
            body = self.rfile.read(content_length)
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"status": "error", "response": "JSON inválido."})
            return

        # Valida a requisição
        valid, user_id, error_msg = validate_request(payload)
        if not valid:
            logger.warning("Validação falhou: %s", error_msg[:100])
            status_code = 403 if "autorizado" in error_msg.lower() else 400
            self._send_json(status_code, {"status": "unauthorized" if "autorizado" in error_msg.lower() else "error", "response": error_msg})
            return

        # Rate limiting
        if user_id and not rate_limiter.allow(user_id):
            logger.warning("Rate limit excedido: %s...", user_id[:30])
            self._send_json(429, {"status": "error", "response": "Muitas solicitações. Aguarde um minuto."})
            return

        # Processa a tarefa
        try:
            result = process_task(payload)
            logger.info(
                "Tarefa processada | action=%s | status=%s",
                payload.get("action_hint", "auto"),
                result.get("status"),
            )
            self._send_json(200, result)
        except Exception as exc:
            logger.error("Erro ao processar tarefa: %s", type(exc).__name__)
            self._send_json(500, {"status": "error", "response": "Erro interno no NEXUS."})

    def log_message(self, format: str, *args: Any) -> None:
        """Override para usar logging estruturado ao invés de print."""
        logger.info("HTTP %s - %s", self.address_string(), format % args)


def run_server(host: str, port: int, ssl_cert: str, ssl_key: str) -> None:
    """Inicia o servidor HTTPS da ponte."""
    if not BRIDGE_TOKEN:
        logger.error("NEXUS_BRIDGE_TOKEN não configurado. Defina a variável de ambiente.")
        return

    if DISABLED:
        logger.error("NEXUS_BRIDGE_DISABLED=true — ponte não iniciará.")
        return

    server = HTTPServer((host, port), NexusBridgeHandler)

    if ssl_cert and ssl_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(ssl_cert, ssl_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        logger.info("Ponte NEXUS iniciada com TLS em https://%s:%d", host, port)
    else:
        logger.warning("Ponte NEXUS iniciada SEM TLS em http://%s:%d (apenas para testes!)", host, port)

    logger.info("Workspace autorizado: %s", WORKSPACE)
    logger.info("Usuários autorizados: %d", len(AUTHORIZED_USERS))
    logger.info("Rate limit: %d req/min", MAX_REQUESTS_PER_MIN)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Ponte encerrada pelo usuário.")
        server.shutdown()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Ponte NEXUS para Alexa Skill")
    parser.add_argument("--host", default="0.0.0.0", help="Host para bind")
    parser.add_argument("--port", type=int, default=8443, help="Porta para bind")
    parser.add_argument("--ssl-cert", default="", help="Caminho do certificado SSL")
    parser.add_argument("--ssl-key", default="", help="Caminho da chave SSL")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    run_server(args.host, args.port, args.ssl_cert, args.ssl_key)


if __name__ == "__main__":
    main()
