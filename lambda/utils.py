# -*- coding: utf-8 -*-
"""Utilidades do NEXUS para a Skill da Alexa.

Funções reutilizáveis para:
- Normalização e validação de entradas em português.
- Construção de respostas da Alexa.
- Identificação de intenções e ações permitidas.
- Comunicação HTTP com o agente NEXUS local.
- Configuração segura por variáveis de ambiente.
- Controle de timeout, erros de rede e respostas inválidas.
- Registro de eventos sem segredos ou conteúdo privado.
- Validação de autorização para operações que alteram o sistema.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any, Dict, Optional

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────────────────
# Configuração por variáveis de ambiente
# ──────────────────────────────────────────────────────────────────────────────

_MAX_RESPONSE_CHARS = 800
_MAX_TASK_CHARS = 500
_NEXUS_TIMEOUT = 8  # segundos — AlexaLambda tem limite de ~8s para primeira resposta


def get_env(key: str, default: str = "") -> str:
    """Lê uma variável de ambiente de forma segura."""
    return os.environ.get(key, default)


def get_env_int(key: str, default: int) -> int:
    """Lê uma variável de ambiente como int, com fallback."""
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# ──────────────────────────────────────────────────────────────────────────────
# Operações permitidas — três grupos de segurança
# ──────────────────────────────────────────────────────────────────────────────

# Grupo A — leitura (sem confirmação)
GROUP_A_ACTIONS = {
    "INSPECIONAR",
    "DIAGNOSTICO",
    "STATUS",
    "VERSAO",
    "LISTAR",
}

# Grupo B — alterações reversíveis (confirmação recomendada)
GROUP_B_ACTIONS = {
    "CRIAR",
    "MODIFICAR",
    "TESTAR",
    "VALIDAR",
}

# Grupo C — operações sensíveis (confirmação humana obrigatória)
GROUP_C_ACTIONS = {
    "EXECUTAR",
    "INSTALAR",
    "REMOVER",
    "PUBLICAR",
    "CONFIGURAR",
}

ALL_ALLOWED_ACTIONS = GROUP_A_ACTIONS | GROUP_B_ACTIONS | GROUP_C_ACTIONS


def classify_action(action: str) -> str:
    """Classifica uma ação em A (leitura), B (reversível) ou C (sensível).

    Retorna 'A', 'B', 'C' ou 'UNKNOWN'.
    """
    action_upper = action.upper().strip()
    if action_upper in GROUP_A_ACTIONS:
        return "A"
    if action_upper in GROUP_B_ACTIONS:
        return "B"
    if action_upper in GROUP_C_ACTIONS:
        return "C"
    return "UNKNOWN"


def is_action_allowed(action: str) -> bool:
    """Verifica se a ação está na lista de operações permitidas."""
    return action.upper().strip() in ALL_ALLOWED_ACTIONS


def requires_confirmation(action: str) -> bool:
    """Retorna True se a ação exige confirmação humana explícita (Grupo B ou C)."""
    group = classify_action(action)
    return group in ("B", "C")


def is_destructive_action(action: str) -> bool:
    """Retorna True se a ação é do Grupo C (sensível/destrutiva)."""
    return classify_action(action) == "C"


# ──────────────────────────────────────────────────────────────────────────────
# Padrões proibidos — nunca permitir mesmo que a ação seja permitida
# ──────────────────────────────────────────────────────────────────────────────

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
    re.compile(r"\.\./", re.IGNORECASE),  # path traversal
]


def contains_forbidden_pattern(text: str) -> bool:
    """Verifica se o texto contém padrões perigosos ou tentativas de escape."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _FORBIDDEN_PATTERNS)


# ──────────────────────────────────────────────────────────────────────────────
# Normalização e validação de entradas em português
# ──────────────────────────────────────────────────────────────────────────────


def normalize_text(text: str) -> str:
    """Normaliza texto de entrada: remove espaços extras, controla tamanho."""
    if not text:
        return ""
    text = text.strip()
    # Remove caracteres de controle
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Colapsa espaços
    text = re.sub(r"\s+", " ", text)
    # Limita tamanho
    if len(text) > _MAX_TASK_CHARS:
        text = text[:_MAX_TASK_CHARS]
        logger.info("Entrada truncada para %d caracteres", _MAX_TASK_CHARS)
    return text


def validate_task_text(text: str) -> tuple[bool, str]:
    """Valida o texto da tarefa enviada pela Alexa.

    Retorna (válido, mensagem_erro).
    """
    normalized = normalize_text(text)
    if not normalized:
        return False, "Não entendi o que você disse. Pode repetir?"
    if len(normalized) < 3:
        return False, "O pedido é muito curto. Pode explicar melhor?"
    if contains_forbidden_pattern(normalized):
        logger.warning("Padrão proibido detectado na entrada do usuário")
        return False, "Essa solicitação não é permitida por segurança."
    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# Construção de respostas da Alexa
# ──────────────────────────────────────────────────────────────────────────────


def build_speech_response(
    speak_output: str,
    reprompt_text: str = "",
    should_end_session: bool = False,
    card_title: str = "",
    card_text: str = "",
) -> Dict[str, Any]:
    """Constrói uma resposta no formato esperado pela Alexa Skills Kit.

    Suporta fala (outputSpeech), reprompt, card simples e flag de fim de sessão.
    """
    speak_output = truncate_for_speech(speak_output)

    response: Dict[str, Any] = {
        "outputSpeech": {
            "type": "SSML",
            "ssml": f"<speak>{speak_output}</speak>",
        },
        "shouldEndSession": should_end_session,
    }

    if reprompt_text:
        reprompt_text = truncate_for_speech(reprompt_text)
        response["reprompt"] = {
            "outputSpeech": {
                "type": "SSML",
                "ssml": f"<speak>{reprompt_text}</speak>",
            }
        }

    if card_title and card_text:
        response["card"] = {
            "type": "Simple",
            "title": card_title,
            "content": card_text[:300],
        }

    return {"version": "1.0", "response": response}


def truncate_for_speech(text: str) -> str:
    """Trunca o texto para respeitar o limite de tamanho das respostas da Alexa."""
    if not text:
        return ""
    if len(text) > _MAX_RESPONSE_CHARS:
        text = text[:_MAX_RESPONSE_CHARS - 20].rstrip() + "..."
    return text


def build_error_response(message: str) -> Dict[str, Any]:
    """Constrói uma resposta de erro amigável para a Alexa."""
    return build_speech_response(
        speak_output=message,
        should_end_session=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Comunicação HTTP com o agente NEXUS local
# ──────────────────────────────────────────────────────────────────────────────


def send_to_nexus(
    task_text: str,
    action_hint: str = "",
    user_id: str = "",
    session_id: str = "",
) -> Dict[str, Any]:
    """Envia uma solicitação ao NEXUS local via endpoint HTTPS autenticado.

    Espera resposta JSON com campos:
        status: "ok" | "error" | "unavailable" | "unauthorized"
        response: str (texto falado de volta para Alexa)
        action: str (ação executada, se aplicável)
        requires_confirmation: bool

    Em caso de erro de rede, timeout ou resposta inválida, retorna status
    apropriado para que o handler da Alexa possa responder de forma amigável.
    """
    nexus_url = get_env("NEXUS_BRIDGE_URL", "")
    nexus_token = get_env("NEXUS_BRIDGE_TOKEN", "")
    timeout = get_env_int("NEXUS_BRIDGE_TIMEOUT", _NEXUS_TIMEOUT)

    if not nexus_url:
        logger.warning("NEXUS_BRIDGE_URL não configurada")
        return {
            "status": "unavailable",
            "response": "O NEXUS local não está configurado. Verifique as variáveis de ambiente.",
        }

    # Valida a URL — apenas HTTPS permitido
    if not nexus_url.startswith("https://"):
        logger.warning("NEXUS_BRIDGE_URL deve usar HTTPS")
        return {
            "status": "error",
            "response": "Configuração de segurança inválida: o endpoint deve usar HTTPS.",
        }

    # Prepara o payload
    payload: Dict[str, Any] = {
        "task": normalize_text(task_text),
        "action_hint": action_hint,
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": int(time.time()),
    }

    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {nexus_token}" if nexus_token else "",
        "X-Source": "alexa-skill",
    }
    # Remove header vazio
    if not headers["Authorization"]:
        del headers["Authorization"]

    # Log sem expor token ou conteúdo sensível
    logger.info(
        "Enviando solicitação ao NEXUS | url_host=%s | task_len=%d | action=%s",
        urllib.parse.urlparse(nexus_url).hostname,
        len(payload["task"]),
        action_hint or "auto",
    )

    try:
        req = urllib.request.Request(
            nexus_url,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            resp_body = resp.read().decode("utf-8", errors="replace")

        if status_code != 200:
            logger.warning("NEXUS respondeu HTTP %d", status_code)
            return {
                "status": "error",
                "response": "O NEXUS retornou um erro. Tente novamente.",
            }

        try:
            data = json.loads(resp_body)
        except json.JSONDecodeError:
            logger.warning("Resposta do NEXUS não é JSON válido")
            return {
                "status": "error",
                "response": "O NEXUS retornou uma resposta inválida.",
            }

        # Valida campos obrigatórios na resposta
        if "status" not in data:
            data["status"] = "ok"
        if "response" not in data:
            data["response"] = "Operação concluída."

        return data

    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            logger.warning("NEXUS rejeitou solicitação: não autorizado")
            return {
                "status": "unauthorized",
                "response": "Solicitação não autorizada pelo NEXUS local.",
            }
        if exc.code == 403:
            logger.warning("NEXUS rejeitou solicitação: ação proibida")
            return {
                "status": "unauthorized",
                "response": "Essa ação não está permitida no NEXUS.",
            }
        logger.warning("NEXUS erro HTTP %d: %s", exc.code, str(exc.reason))
        return {
            "status": "error",
            "response": "O NEXUS local reportou um erro.",
        }

    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        logger.warning("NEXUS indisponível: %s", reason)
        return {
            "status": "unavailable",
            "response": "Não consegui conectar ao NEXUS local. Verifique se ele está ativo.",
        }

    except TimeoutError:
        logger.warning("NEXUS timeout após %ds", timeout)
        return {
            "status": "unavailable",
            "response": "O NEXUS local demorou demais para responder. Tente novamente.",
        }

    except Exception as exc:
        logger.error("Erro inesperado ao contactar NEXUS: %s", type(exc).__name__)
        return {
            "status": "error",
            "response": "Ocorreu um erro inesperado ao contactar o NEXUS.",
        }


# ──────────────────────────────────────────────────────────────────────────────
# Registro de eventos (logs estruturados sem segredos)
# ──────────────────────────────────────────────────────────────────────────────


def log_event(event_type: str, details: Dict[str, Any]) -> None:
    """Registra um evento estruturado sem expor segredos ou dados privados.

    Filtra automaticamente chaves que podem conter credenciais.
    """
    sensitive_keys = {
        "token", "password", "secret", "key", "credential",
        "authorization", "auth", "api_key", "apikey",
        "nexus_bridge_token", "refresh_token",
    }

    safe_details = {}
    for key, value in details.items():
        if key.lower() in sensitive_keys:
            safe_details[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > 200:
            safe_details[key] = value[:200] + "..."
        else:
            safe_details[key] = value

    logger.info("EVENT type=%s | %s", event_type, json.dumps(safe_details, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────────────────
# Validação de autorização para solicitações que alteram o sistema
# ──────────────────────────────────────────────────────────────────────────────


def check_authorization(
    action: str,
    user_id: str,
    authorized_users: Optional[str] = None,
) -> tuple[bool, str]:
    """Verifica se um usuário está autorizado a executar uma ação.

    Para ações do Grupo A (leitura), qualquer usuário autenticado pode executar.
    Para ações dos Grupos B e C, apenas usuários autorizados podem executar.
    Para Grupo C, confirmação humana é obrigatória (retorna mensagem específica).

    Retorna (autorizado, mensagem).
    """
    group = classify_action(action)

    if group == "UNKNOWN":
        return False, "Essa ação não é reconhecida pelo NEXUS."

    if group == "A":
        return True, ""

    # Grupos B e C — verificar lista de usuários autorizados
    allowed_list = authorized_users or get_env("NEXUS_AUTHORIZED_USERS", "")
    if not allowed_list:
        # Se não há lista configurada, negar por padrão
        return False, "Nenhum usuário autorizado configurado para operações de alteração."

    allowed_ids = [uid.strip() for uid in allowed_list.split(",") if uid.strip()]
    if user_id not in allowed_ids:
        log_event("auth_denied", {"user_id": user_id[:50], "action": action})
        return False, "Você não está autorizado a executar essa operação."

    if group == "C":
        return True, "Operação sensível. Confirmação humana necessária via app NEXUS."

    return True, ""
