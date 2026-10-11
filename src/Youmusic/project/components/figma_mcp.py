"""NEXUS TERMINAL — Figma MCP Integration Layer.

Camada desacoplada para o Figma MCP Server oficial. Permite que o NEXUS
detecte disponibilidade, descubra ferramentas, execute chamadas JSON-RPC
e devolva resultados estruturados ao fluxo principal do agente.

O NEXUS continua funcionando normalmente quando o Figma MCP não está
instalado, configurado ou disponível; a capacidade é marcada como
indisponível e o agente prossegue sem quebrar.

Ferramentas suportadas (documentadas oficialmente):
  Read: get_design_context, get_metadata, get_screenshot, download_assets,
        get_variable_defs, get_motion_context, search_design_system,
        get_code_connect_map, get_code_connect_suggestions,
        get_context_for_code_connect, get_libraries, get_figjam,
        get_generative_plugin
  Write: use_figma, generate_figma_design, generate_diagram,
         generate_image, create_new_file
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


FIGMA_MCP_PACKAGE = "figma-developer-mcp"
FIGMA_MCP_SERVER_CMD = "figma-developer-mcp"
FIGMA_MCP_REMOTE_URL = "https://mcp.figma.com/mcp"

FIGMA_READ_TOOLS: dict[str, dict[str, Any]] = {
    "get_design_context": {
        "description": "Contexto de design de uma camada ou seleção (layout, tipografia, componentes)",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId", "depth", "includeVariables", "recursive"],
    },
    "get_metadata": {
        "description": "Estrutura XML esparsa de uma seleção (navegação leve)",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId"],
    },
    "get_screenshot": {
        "description": "Captura de tela PNG de um node ou seleção",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId", "scale", "format"],
    },
    "download_assets": {
        "description": "Baixa exports e imagens originais de um arquivo Figma",
        "group": "design_to_code",
        "remote_only": True,
        "required_params": ["fileKey"],
        "optional_params": ["nodeIds", "formats", "scales", "includeOriginalSource"],
    },
    "get_variable_defs": {
        "description": "Variáveis e estilos usados na seleção (cores, espaçamento, tipografia)",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId"],
    },
    "get_motion_context": {
        "description": "Dados de animação keyframe para um node animado",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey", "nodeId"],
        "optional_params": ["recursive"],
    },
    "search_design_system": {
        "description": "Busca componentes e estilos no design system do usuário",
        "group": "design_systems",
        "remote_only": False,
        "required_params": ["query"],
        "optional_params": ["fileKey", "libraryKey", "cursor"],
    },
    "get_code_connect_map": {
        "description": "Mapeamento node ID → componente de código (Code Connect)",
        "group": "design_systems",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId"],
    },
    "get_code_connect_suggestions": {
        "description": "Sugestões de mapeamento Code Connect (Figma-prompted)",
        "group": "design_systems",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId"],
    },
    "get_context_for_code_connect": {
        "description": "Metadados de componente para templates Code Connect",
        "group": "design_systems",
        "remote_only": True,
        "required_params": ["fileKey", "nodeId"],
        "optional_params": [],
    },
    "get_libraries": {
        "description": "Lista bibliotecas inscritas e disponíveis",
        "group": "design_systems",
        "remote_only": True,
        "required_params": [],
        "optional_params": [],
    },
    "get_figjam": {
        "description": "Converte diagramas FigJam para XML",
        "group": "design_to_code",
        "remote_only": False,
        "required_params": ["fileKey"],
        "optional_params": ["nodeId"],
    },
    "get_generative_plugin": {
        "description": "Lê o manifest de um plugin generativo",
        "group": "generative",
        "remote_only": True,
        "required_params": ["fileKey", "nodeId"],
        "optional_params": [],
    },
}

FIGMA_WRITE_TOOLS: dict[str, dict[str, Any]] = {
    "use_figma": {
        "description": "Cria ou modifica conteúdo no canvas do Figma (escrita)",
        "group": "write",
        "remote_only": True,
        "required_params": ["fileKey"],
        "optional_params": ["prompt", "nodeId", "operations"],
    },
    "generate_figma_design": {
        "description": "Gera um design no Figma a partir de um prompt",
        "group": "generative",
        "remote_only": True,
        "required_params": ["prompt"],
        "optional_params": ["fileKey", "nodeId"],
    },
    "generate_diagram": {
        "description": "Gera um diagrama no FigJam a partir de um prompt",
        "group": "generative",
        "remote_only": True,
        "required_params": ["prompt"],
        "optional_params": ["fileKey"],
    },
    "generate_image": {
        "description": "Gera uma imagem a partir de um prompt",
        "group": "generative",
        "remote_only": True,
        "required_params": ["prompt"],
        "optional_params": ["fileKey", "nodeId"],
    },
    "create_new_file": {
        "description": "Cria um novo arquivo Figma",
        "group": "write",
        "remote_only": True,
        "required_params": ["name"],
        "optional_params": ["parentId"],
    },
}

ALL_FIGMA_TOOLS = {**FIGMA_READ_TOOLS, **FIGMA_WRITE_TOOLS}

FIGMA_DESIGN_KEYWORDS = [
    "figma", "design", "ui", "interface", "layout", "mockup", "wireframe",
    "prototype", "component visual", "design system", "tela", "componente visual",
    "design do figma", "figma file", "figma design", "frame", "figjam",
    "get_screenshot", "get_design_context", "design context",
]

FIGMA_URL_PATTERN = "figma.com"


def figma_url_to_file_key(url: str) -> Optional[str]:
    """Extrai fileKey de uma URL do Figma."""
    if not url:
        return None
    parts = url.split("/")
    for i, part in enumerate(parts):
        if part in ("design", "file", "proto", "board", "figjam"):
            if i + 1 < len(parts):
                candidate = parts[i + 1].split("?")[0].split("-")[0]
                if candidate and len(candidate) >= 10:
                    return candidate
    return None


def figma_url_to_node_id(url: str) -> Optional[str]:
    """Extrai nodeId de uma URL do Figma (parâmetro node-id)."""
    if not url or "node-id=" not in url:
        return None
    after = url.split("node-id=")[1].split("&")[0].split("#")[0]
    return after.replace("-", ":") if after else None


class FigmaMCPError(Exception):
    """Erro específico da integração Figma MCP."""


class FigmaMCPTimeout(FigmaMCPError):
    """Timeout durante chamada ao Figma MCP."""


class FigmaMCPNotAvailable(FigmaMCPError):
    """Figma MCP não instalado, configurado ou disponível."""


class FigmaMCPAuthError(FigmaMCPError):
    """Autenticação expirada ou inválida."""


class FigmaMCPClient:
    """Cliente desacoplado para o Figma MCP Server.

    Detecta disponibilidade via npx/CLI local ou URL remota. Executa
    chamadas JSON-RPC 2.0 sobre stdio (modo local) ou HTTP (modo remoto).
    """

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._available: Optional[bool] = None
        self._mode: str = "unknown"
        self._server_process: Optional[subprocess.Popen] = None
        self._initialized: bool = False
        self._request_id: int = 0
        self._tools_cache: Optional[list[dict[str, Any]]] = None
        self._timeout_seconds: float = float(
            os.environ.get("NEXUS_FIGMA_TIMEOUT", "30")
        )

    def _get_env_token(self) -> Optional[str]:
        token = os.environ.get("FIGMA_API_KEY") or os.environ.get("FIGMA_ACCESS_TOKEN")
        if token:
            return token.strip()
        return None

    def _get_remote_url(self) -> Optional[str]:
        url = os.environ.get("NEXUS_FIGMA_MCP_URL", "").strip()
        return url if url else None

    def _is_cli_installed(self) -> bool:
        if shutil.which(FIGMA_MCP_SERVER_CMD):
            return True
        npx = shutil.which("npx")
        if not npx:
            return False
        try:
            result = subprocess.run(
                [npx, "--yes", FIGMA_MCP_PACKAGE, "--help"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            return result.returncode == 0 or "figma" in (result.stdout or "").lower()
        except (OSError, subprocess.SubprocessError):
            return False

    def detect(self) -> dict[str, Any]:
        """Verifica disponibilidade do Figma MCP e retorna diagnóstico estruturado."""
        cli_installed = self._is_cli_installed()
        remote_url = self._get_remote_url()
        token = self._get_env_token()
        npx_available = shutil.which("npx") is not None
        available = cli_installed or (remote_url is not None) or npx_available
        if remote_url:
            self._mode = "remote"
        elif cli_installed:
            self._mode = "cli"
        elif npx_available:
            self._mode = "npx"
        else:
            self._mode = "unavailable"
        self._available = available
        return {
            "available": available,
            "mode": self._mode,
            "cli_installed": cli_installed,
            "npx_available": npx_available,
            "remote_url": remote_url or "",
            "has_token": token is not None,
            "package": FIGMA_MCP_PACKAGE,
            "timeout_seconds": self._timeout_seconds,
        }

    def is_available(self) -> bool:
        if self._available is None:
            self.detect()
        return self._available or False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if not self.is_available():
            raise FigmaMCPNotAvailable(
                "Figma MCP não está disponível. Execute /figma status para diagnóstico."
            )
        self._initialized = True

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _build_cli_command(self) -> list[str]:
        npx = shutil.which("npx")
        if npx and self._mode in ("npx", "cli"):
            cmd = [npx, "--yes", FIGMA_MCP_PACKAGE]
            token = self._get_env_token()
            if token:
                cmd.extend(["--figma-api-key", token])
            return cmd
        local = shutil.which(FIGMA_MCP_SERVER_CMD)
        if local:
            return [local]
        raise FigmaMCPNotAvailable("Nem npx nem CLI local do Figma MCP encontrados.")

    def _call_stdio(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Executa uma chamada JSON-RPC sobre stdio para o servidor MCP local."""
        cmd = self._build_cli_command()
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            request["params"] = params
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FigmaMCPNotAvailable(f"Falha ao iniciar servidor MCP: {exc}") from exc
        self._server_process = proc
        try:
            init_req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "nexus-terminal", "version": "8.0"},
                },
            }
            init_line = json.dumps(init_req) + "\n"
            req_line = json.dumps(request) + "\n"
            full_input = init_line + req_line
            stdout, stderr = proc.communicate(
                input=full_input, timeout=self._timeout_seconds
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            raise FigmaMCPTimeout(
                f"Timeout após {self._timeout_seconds}s aguardando Figma MCP."
            ) from None
        except (OSError, subprocess.SubprocessError) as exc:
            proc.kill()
            raise FigmaMCPError(f"Erro de comunicação: {exc}") from exc
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == request["id"]:
                if "error" in msg:
                    err = msg["error"]
                    err_msg = str(err.get("message", "erro desconhecido"))
                    if "auth" in err_msg.lower() or "token" in err_msg.lower():
                        raise FigmaMCPAuthError(err_msg)
                    raise FigmaMCPError(err_msg)
                return msg.get("result")
        raise FigmaMCPError(
            f"Sem resposta para request {request['id']}. stderr: {(stderr or '')[:500]}"
        )

    def _call_remote(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Executa uma chamada HTTP para o servidor MCP remoto."""
        import urllib.request
        import urllib.error
        url = self._get_remote_url() or FIGMA_MCP_REMOTE_URL
        request_body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            request["params"] = params
        data = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
            method="POST",
        )
        token = self._get_env_token()
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise FigmaMCPAuthError("Autenticação expirada ou inválida (401).") from exc
            raise FigmaMCPError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise FigmaMCPNotAvailable(f"Servidor MCP remoto indisponível: {exc}") from exc
        except OSError as exc:
            raise FigmaMCPError(f"Erro de rede: {exc}") from exc
        try:
            msg = json.loads(body)
        except json.JSONDecodeError as exc:
            raise FigmaMCPError(f"Resposta JSON malformada: {exc}") from exc
        if "error" in msg:
            err = msg["error"]
            err_msg = str(err.get("message", "erro desconhecido"))
            if "auth" in err_msg.lower() or "token" in err_msg.lower():
                raise FigmaMCPAuthError(err_msg)
            raise FigmaMCPError(err_msg)
        return msg.get("result")

    def call_tool(self, tool_name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Executa uma ferramenta do Figma MCP pelo nome.

        Retorna um dict estruturado com: tool, status, result, error, elapsed.
        """
        if tool_name not in ALL_FIGMA_TOOLS:
            raise FigmaMCPError(
                f"Ferramenta '{tool_name}' não existe. Disponíveis: "
                + ", ".join(sorted(ALL_FIGMA_TOOLS.keys()))
            )
        self._ensure_initialized()
        tool_info = ALL_FIGMA_TOOLS[tool_name]
        for req_param in tool_info["required_params"]:
            if not arguments or req_param not in arguments:
                raise FigmaMCPError(
                    f"Parâmetro obrigatório '{req_param}' ausente para {tool_name}."
                )
        params = {
            "name": tool_name,
            "arguments": arguments or {},
        }
        start = time.monotonic()
        try:
            if self._mode == "remote":
                result = self._call_remote("tools/call", params)
            else:
                result = self._call_stdio("tools/call", params)
            elapsed = time.monotonic() - start
            return {
                "tool": tool_name,
                "status": "OK",
                "result": result,
                "error": None,
                "elapsed_seconds": round(elapsed, 3),
            }
        except FigmaMCPTimeout as exc:
            return {
                "tool": tool_name, "status": "TIMEOUT", "result": None,
                "error": str(exc), "elapsed_seconds": round(time.monotonic() - start, 3),
            }
        except FigmaMCPAuthError as exc:
            return {
                "tool": tool_name, "status": "AUTH_ERROR", "result": None,
                "error": str(exc), "elapsed_seconds": round(time.monotonic() - start, 3),
            }
        except FigmaMCPNotAvailable as exc:
            return {
                "tool": tool_name, "status": "UNAVAILABLE", "result": None,
                "error": str(exc), "elapsed_seconds": round(time.monotonic() - start, 3),
            }
        except FigmaMCPError as exc:
            return {
                "tool": tool_name, "status": "ERROR", "result": None,
                "error": str(exc), "elapsed_seconds": round(time.monotonic() - start, 3),
            }

    def list_tools(self) -> list[dict[str, str]]:
        """Retorna lista de ferramentas disponíveis com metadados."""
        tools = []
        for name, info in ALL_FIGMA_TOOLS.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "group": info["group"],
                "remote_only": str(info["remote_only"]),
                "required_params": ", ".join(info["required_params"]) or "(nenhum)",
                "optional_params": ", ".join(info["optional_params"]) or "(nenhum)",
            })
        return tools

    def discover_tools(self) -> Optional[list[dict[str, Any]]]:
        """Tenta descobrir ferramentas via initialize/tools/list do MCP."""
        if not self.is_available():
            return None
        try:
            if self._mode == "remote":
                result = self._call_remote("tools/list")
            else:
                result = self._call_stdio("tools/list")
            if isinstance(result, dict) and "tools" in result:
                self._tools_cache = result["tools"]
                return result["tools"]
        except Exception:
            pass
        return None

    def close(self) -> None:
        if self._server_process is not None:
            try:
                self._server_process.kill()
            except Exception:
                pass
            self._server_process = None
        self._initialized = False


def detect_figma_need(user_request: str) -> dict[str, Any]:
    """Analisa se uma solicitação do usuário envolve Figma/design.

    Retorna dict com: needs_figma (bool), keywords_matched (list),
    figma_url (str|None), file_key (str|None), node_id (str|None),
    suggested_tools (list).
    """
    text = (user_request or "").lower()
    matched = [kw for kw in FIGMA_DESIGN_KEYWORDS if kw in text]
    figma_url = None
    file_key = None
    node_id = None
    if "figma.com" in text or "figma.com" in (user_request or ""):
        for word in (user_request or "").split():
            if "figma.com" in word:
                figma_url = word.strip("<>()\"',")
                break
        if not figma_url:
            for word in (user_request or "").split():
                if word.startswith("http") and "figma" in word.lower():
                    figma_url = word.strip("<>()\"',")
                    break
    if figma_url:
        file_key = figma_url_to_file_key(figma_url)
        node_id = figma_url_to_node_id(figma_url)
    suggested: list[str] = []
    if file_key:
        suggested.append("get_design_context")
        suggested.append("get_metadata")
        suggested.append("get_screenshot")
        suggested.append("get_variable_defs")
    if any(kw in text for kw in ["design system", "component library", "code connect"]):
        suggested.append("search_design_system")
        suggested.append("get_code_connect_map")
    if any(kw in text for kw in ["anim", "motion", "keyframe", "transição"]):
        suggested.append("get_motion_context")
    if any(kw in text for kw in ["asset", "export", "download", "imagem", "ícone", "icon"]):
        suggested.append("download_assets")
    if any(kw in text for kw in ["diagram", "figjam", "fluxograma"]):
        suggested.append("get_figjam")
        suggested.append("generate_diagram")
    if any(kw in text for kw in ["criar", "gerar", "create", "generate"]) and any(
        kw in text for kw in ["design", "figma", "tela", "interface"]
    ):
        suggested.append("generate_figma_design")
    needs_figma = bool(matched) or figma_url is not None
    return {
        "needs_figma": needs_figma,
        "keywords_matched": matched,
        "figma_url": figma_url,
        "file_key": file_key,
        "node_id": node_id,
        "suggested_tools": list(dict.fromkeys(suggested)),
    }


def validate_figma_response(response: dict[str, Any], tool_name: str) -> tuple[bool, str]:
    """Valida que a resposta do Figma MCP é completa e não contém placeholders.

    Retorna (ok, reason). Rejeita respostas com "...", placeholders, ou
    conteúdo vazio.
    """
    if not isinstance(response, dict):
        return False, "Resposta não é um dict."
    status = response.get("status", "")
    if status in ("ERROR", "TIMEOUT", "AUTH_ERROR", "UNAVAILABLE"):
        err = response.get("error", "erro desconhecido")
        return False, f"Ferramenta {tool_name} falhou ({status}): {err}"
    result = response.get("result")
    if result is None:
        return False, f"Ferramenta {tool_name} retornou result=None."
    result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    placeholder_indicators = ["...", "TODO", "FIXME", "<placeholder>", "lorem ipsum"]
    for indicator in placeholder_indicators:
        if indicator in result_str:
            return False, f"Resposta contém placeholder '{indicator}'."
    if not result_str.strip():
        return False, f"Resposta da ferramenta {tool_name} está vazia."
    return True, "OK"


def figma_context_for_planning(
    client: FigmaMCPClient,
    detection: dict[str, Any],
    max_tools: int = 5,
) -> dict[str, Any]:
    """Executa ferramentas Figma sugeridas e retorna contexto estruturado para o planejador.

    Não executa ferramentas de escrita (use_figma, generate_*) — somente leitura.
    Cada chamada é rastreada com tool, objective, status, error.
    """
    if not client.is_available():
        return {
            "figma_available": False,
            "figma_context": None,
            "figma_error": "Figma MCP indisponível",
            "figma_operations": [],
        }
    file_key = detection.get("file_key")
    node_id = detection.get("node_id")
    suggested = detection.get("suggested_tools", [])[:max_tools]
    operations: list[dict[str, str]] = []
    context_data: dict[str, Any] = {}
    for tool_name in suggested:
        if tool_name not in FIGMA_READ_TOOLS:
            operations.append({
                "tool": tool_name,
                "objective": f" {ALL_FIGMA_TOOLS[tool_name]['description']}",
                "status": "SKIPPED",
                "error": "Ferramenta de escrita não executada em planejamento",
            })
            continue
        arguments: dict[str, Any] = {}
        if file_key and "fileKey" in ALL_FIGMA_TOOLS[tool_name]["required_params"]:
            arguments["fileKey"] = file_key
        if node_id and "nodeId" in ALL_FIGMA_TOOLS[tool_name].get("optional_params", []):
            arguments["nodeId"] = node_id
        if not arguments.get("fileKey") and "fileKey" in ALL_FIGMA_TOOLS[tool_name]["required_params"]:
            operations.append({
                "tool": tool_name,
                "objective": ALL_FIGMA_TOOLS[tool_name]["description"],
                "status": "SKIPPED",
                "error": "fileKey ausente",
            })
            continue
        objective = ALL_FIGMA_TOOLS[tool_name]["description"]
        print(f"  [FIGMA] Executando {tool_name} → {objective}")
        response = client.call_tool(tool_name, arguments)
        ok, reason = validate_figma_response(response, tool_name)
        status = response.get("status", "UNKNOWN")
        error = response.get("error", "") if not ok else ""
        operations.append({
            "tool": tool_name,
            "objective": objective,
            "status": status if ok else "REJECTED",
            "error": error,
        })
        if ok and response.get("result"):
            context_data[tool_name] = response["result"]
    return {
        "figma_available": True,
        "figma_context": context_data if context_data else None,
        "figma_error": None,
        "figma_operations": operations,
        "figma_file_key": file_key,
        "figma_node_id": node_id,
    }


COMPONENT_METADATA = {
    "id": "figma_mcp",
    "name": "Figma MCP Integration",
    "path": "components/figma_mcp.py",
    "type": "integration",
    "version": "1.0.0",
    "description": "Integração com Figma MCP Server oficial — leitura de designs, assets, variáveis e escrita no canvas",
    "entrypoint": "FigmaMCPClient",
    "dependencies": ["figma-developer-mcp"],
    "compatibility": ">=8.0",
}
