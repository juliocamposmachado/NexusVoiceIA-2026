# -*- coding: utf-8 -*-
"""NEXUS Alexa Skill — Handler principal.

Permite conversar em português brasileiro com o NEXUS por voz através da Alexa.
A Skill recebe solicitações, valida, encaminha ao NEXUS local via ponte HTTPS
autenticada e devolve respostas faladas.

Arquitetura:
    Alexa → AWS Lambda (esta Skill) → endpoint HTTPS → NEXUS local → resposta → Alexa

Intenções suportadas:
- LaunchRequest: boas-vindas
- ExecutarTarefaIntent: solicita tarefa ao NEXUS (slot: tarefa)
- StatusNexusIntent: consulta status do NEXUS
- ListarArquivosIntent: lista arquivos do workspace
- DiagnosticarIntent: executa diagnóstico do ambiente
- CancelarTarefaIntent: cancela tarefa em execução
- AMAZON.HelpIntent: ajuda
- AMAZON.CancelIntent / AMAZON.StopIntent: encerra
- AMAZON.FallbackIntent: fallback
- SessionEndedRequest: fim de sessão
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

import ask_sdk_core.utils as ask_utils
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
    AbstractRequestInterceptor,
)
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import SimpleCard

from utils import (
    normalize_text,
    validate_task_text,
    send_to_nexus,
    check_authorization,
    log_event,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────────────────────
# Mensagens em português brasileiro
# ──────────────────────────────────────────────────────────────────────────────

WELCOME_SPEECH = (
    "Bem-vindo ao NEXUS. "
    "Você pode pedir tarefas, consultar status, listar arquivos ou diagnosticar o ambiente. "
    "O que você gostaria de fazer?"
)

WELCOME_REPROMPT = "Diga algo como: solicite ao NEXUS verificar os arquivos do projeto."

HELP_SPEECH = (
    "O NEXUS pode executar tarefas no seu terminal Linux por voz. "
    "Você pode dizer: 'peça ao NEXUS listar os arquivos', "
    "'verifique o status do NEXUS', "
    "ou 'solicite um diagnóstico do ambiente'. "
    "Para operações que alteram arquivos ou executam comandos, "
    "será necessária confirmação no app do NEXUS. "
    "O que você gostaria de fazer?"
)

HELP_REPROMPT = "Pode dizer, por exemplo: 'peça ao NEXUS listar os arquivos do projeto'."

GOODBYE_SPEECH = "Encerrando o NEXUS. Até logo!"

FALLBACK_SPEECH = (
    "Não entendi isso. "
    "Você pode pedir tarefas ao NEXUS, consultar status ou diagnosticar o ambiente. "
    "O que você gostaria de fazer?"
)

FALLBACK_REPROMPT = "Tente dizer: 'peça ao NEXUS verificar o status'."

ERROR_SPEECH = (
    "Desculpe, ocorreu um problema. Tente novamente em alguns instantes."
)

NEXUS_DOWN_SPEECH = (
    "Não consegui conectar ao NEXUS local. "
    "Verifique se o NEXUS está ativo e a ponte configurada."
)

NEXUS_DOWN_REPROMPT = "Verifique se o NEXUS está ativo e tente novamente."

NEXUS_UNAUTHORIZED_SPEECH = (
    "Essa operação não está autorizada. "
    "Verifique as permissões no app do NEXUS."
)


# ──────────────────────────────────────────────────────────────────────────────
# Funções auxiliares
# ──────────────────────────────────────────────────────────────────────────────


def _get_user_id(handler_input: HandlerInput) -> str:
    try:
        return handler_input.request_envelope.context.system.user.user_id
    except (AttributeError, KeyError):
        return ""


def _get_session_id(handler_input: HandlerInput) -> str:
    try:
        return handler_input.request_envelope.session.session_id
    except (AttributeError, KeyError):
        return ""


def _get_slot_value(handler_input: HandlerInput, slot_name: str) -> str:
    try:
        slots = handler_input.request_envelope.request.intent.slots
        if slots and slot_name in slots:
            return slots[slot_name].value or ""
    except (AttributeError, KeyError):
        pass
    return ""


def _respond(
    handler_input: HandlerInput,
    speak_output: str,
    reprompt_text: str = "",
    should_end_session: bool = False,
    card_title: str = "",
    card_text: str = "",
) -> Response:
    """Constrói uma resposta usando o response_builder do SDK."""
    rb = handler_input.response_builder
    rb.speak(speak_output)

    if reprompt_text:
        rb.ask(reprompt_text)

    if should_end_session:
        rb.set_should_end_session(should_end_session)

    if card_title and card_text:
        rb.set_simple_card(SimpleCard(title=card_title, content=card_text[:300]))

    return rb.response


def _handle_nexus_response(
    handler_input: HandlerInput,
    nexus_result: Dict[str, Any],
    should_end_session: bool = False,
) -> Response:
    """Processa a resposta do NEXUS e constrói a resposta da Alexa via SDK."""
    status = nexus_result.get("status", "error")
    response_text = nexus_result.get("response", "")

    if status == "unavailable":
        return _respond(
            handler_input,
            speak_output=NEXUS_DOWN_SPEECH,
            reprompt_text=NEXUS_DOWN_REPROMPT,
            should_end_session=False,
        )

    if status == "unauthorized":
        return _respond(
            handler_input,
            speak_output=NEXUS_UNAUTHORIZED_SPEECH,
            should_end_session=False,
        )

    if status == "error":
        msg = response_text or "O NEXUS reportou um erro ao processar sua solicitação."
        return _respond(
            handler_input,
            speak_output=msg,
            reprompt_text="Tente reformular seu pedido.",
            should_end_session=False,
        )

    # status == "ok"
    requires_confirm = nexus_result.get("requires_confirmation", False)
    if requires_confirm:
        response_text = response_text or (
            "Operação registrada. Confirme no app do NEXUS para prosseguir."
        )

    reprompt = "" if should_end_session else "Posso ajudar com mais alguma coisa?"
    return _respond(
        handler_input,
        speak_output=response_text,
        reprompt_text=reprompt,
        should_end_session=should_end_session,
        card_title="NEXUS",
        card_text=response_text[:300] if response_text else "",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Handlers de requisições
# ──────────────────────────────────────────────────────────────────────────────


class LaunchRequestHandler(AbstractRequestHandler):
    """Handler para abertura da Skill (LaunchRequest)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        log_event("skill_launch", {"user_id": _get_user_id(handler_input)[:50]})
        return _respond(
            handler_input,
            speak_output=WELCOME_SPEECH,
            reprompt_text=WELCOME_REPROMPT,
            should_end_session=False,
        )


class ExecutarTarefaIntentHandler(AbstractRequestHandler):
    """Handler para ExecutarTarefaIntent — solicita tarefa ao NEXUS.

    Slot: tarefa (texto livre em português)
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("ExecutarTarefaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        user_id = _get_user_id(handler_input)
        session_id = _get_session_id(handler_input)
        task_text = _get_slot_value(handler_input, "tarefa")

        valid, error_msg = validate_task_text(task_text)
        if not valid:
            return _respond(
                handler_input,
                speak_output=error_msg,
                reprompt_text="Pode repetir sua solicitação?",
                should_end_session=False,
            )

        normalized = normalize_text(task_text)
        log_event("task_request", {"user_id": user_id[:50], "task_len": len(normalized)})

        authorized, auth_msg = check_authorization("INSPECIONAR", user_id)
        if not authorized:
            return _respond(
                handler_input,
                speak_output=auth_msg or NEXUS_UNAUTHORIZED_SPEECH,
                should_end_session=False,
            )

        nexus_result = send_to_nexus(
            task_text=normalized,
            action_hint="auto",
            user_id=user_id,
            session_id=session_id,
        )

        return _handle_nexus_response(handler_input, nexus_result)


class StatusNexusIntentHandler(AbstractRequestHandler):
    """Handler para StatusNexusIntent — consulta status do NEXUS."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("StatusNexusIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        user_id = _get_user_id(handler_input)

        authorized, auth_msg = check_authorization("STATUS", user_id)
        if not authorized:
            return _respond(
                handler_input,
                speak_output=auth_msg or NEXUS_UNAUTHORIZED_SPEECH,
                should_end_session=False,
            )

        nexus_result = send_to_nexus(
            task_text="verificar status do sistema",
            action_hint="STATUS",
            user_id=user_id,
            session_id=_get_session_id(handler_input),
        )

        return _handle_nexus_response(handler_input, nexus_result)


class ListarArquivosIntentHandler(AbstractRequestHandler):
    """Handler para ListarArquivosIntent — lista arquivos do workspace."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("ListarArquivosIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        user_id = _get_user_id(handler_input)

        authorized, auth_msg = check_authorization("LISTAR", user_id)
        if not authorized:
            return _respond(
                handler_input,
                speak_output=auth_msg or NEXUS_UNAUTHORIZED_SPEECH,
                should_end_session=False,
            )

        nexus_result = send_to_nexus(
            task_text="listar arquivos do workspace atual",
            action_hint="LISTAR",
            user_id=user_id,
            session_id=_get_session_id(handler_input),
        )

        return _handle_nexus_response(handler_input, nexus_result)


class DiagnosticarIntentHandler(AbstractRequestHandler):
    """Handler para DiagnosticarIntent — executa diagnóstico do ambiente."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("DiagnosticarIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        user_id = _get_user_id(handler_input)

        authorized, auth_msg = check_authorization("DIAGNOSTICO", user_id)
        if not authorized:
            return _respond(
                handler_input,
                speak_output=auth_msg or NEXUS_UNAUTHORIZED_SPEECH,
                should_end_session=False,
            )

        nexus_result = send_to_nexus(
            task_text="executar diagnóstico do ambiente",
            action_hint="DIAGNOSTICO",
            user_id=user_id,
            session_id=_get_session_id(handler_input),
        )

        return _handle_nexus_response(handler_input, nexus_result)


class CancelarTarefaIntentHandler(AbstractRequestHandler):
    """Handler para CancelarTarefaIntent — cancela tarefa em execução."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("CancelarTarefaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        user_id = _get_user_id(handler_input)
        log_event("task_cancel", {"user_id": user_id[:50]})

        nexus_result = send_to_nexus(
            task_text="cancelar tarefa atual",
            action_hint="CANCELAR",
            user_id=user_id,
            session_id=_get_session_id(handler_input),
        )

        return _handle_nexus_response(handler_input, nexus_result, should_end_session=True)


class HelpIntentHandler(AbstractRequestHandler):
    """Handler para AMAZON.HelpIntent."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return _respond(
            handler_input,
            speak_output=HELP_SPEECH,
            reprompt_text=HELP_REPROMPT,
            should_end_session=False,
        )


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Handler único para AMAZON.CancelIntent e AMAZON.StopIntent."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input)
            or ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        return _respond(
            handler_input,
            speak_output=GOODBYE_SPEECH,
            should_end_session=True,
        )


class FallbackIntentHandler(AbstractRequestHandler):
    """Handler para AMAZON.FallbackIntent — captura intenções não reconhecidas."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return _respond(
            handler_input,
            speak_output=FALLBACK_SPEECH,
            reprompt_text=FALLBACK_REPROMPT,
            should_end_session=False,
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler para SessionEndedRequest — limpeza de sessão."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        reason = ""
        try:
            reason = str(handler_input.request_envelope.request.reason)
        except (AttributeError, KeyError, TypeError):
            pass
        log_event("session_ended", {"reason": reason})
        return _respond(handler_input, speak_output="", should_end_session=True)


class IntentReflectorHandler(AbstractRequestHandler):
    """Refletor de intenções — usado para teste e debug do modelo de interação.

    Deve ser o último handler de intenção para não sobrescrever os customizados.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return ask_utils.is_request_type("IntentRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        intent_name = ask_utils.get_intent_name(handler_input)
        speak_output = f"Você acionou a intenção {intent_name}."
        return _respond(
            handler_input,
            speak_output=speak_output,
            should_end_session=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Handlers de exceção
# ──────────────────────────────────────────────────────────────────────────────


class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Trata erros não capturados — sintaxe, roteamento, etc."""

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        logger.error("Exceção não tratada: %s", type(exception).__name__, exc_info=True)
        log_event("unhandled_exception", {"exception_type": type(exception).__name__})
        return _respond(
            handler_input,
            speak_output=ERROR_SPEECH,
            reprompt_text="Tente novamente.",
            should_end_session=False,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Interceptor de log
# ──────────────────────────────────────────────────────────────────────────────


class LoggingInterceptor(AbstractRequestInterceptor):
    """Registra metadados da requisição antes do processamento."""

    def process(self, handler_input: HandlerInput) -> None:
        try:
            req_type = ask_utils.get_request_type(handler_input)
            intent_name = ""
            if req_type == "IntentRequest":
                intent_name = ask_utils.get_intent_name(handler_input)
            log_event("request_received", {
                "request_type": req_type,
                "intent": intent_name,
            })
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Skill Builder
# ──────────────────────────────────────────────────────────────────────────────

sb = SkillBuilder()

sb.add_global_request_interceptor(LoggingInterceptor())

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(ExecutarTarefaIntentHandler())
sb.add_request_handler(StatusNexusIntentHandler())
sb.add_request_handler(ListarArquivosIntentHandler())
sb.add_request_handler(DiagnosticarIntentHandler())
sb.add_request_handler(CancelarTarefaIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(IntentReflectorHandler())  # deve ser o último

sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
