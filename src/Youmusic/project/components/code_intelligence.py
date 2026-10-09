"""Code Intelligence Engine — componente do NEXUS TERMINAL.

Diagnóstico local em camadas: AST, Ruff, Pyright, Jedi e prompt_toolkit.
Nenhuma ferramenta externa é obrigatória; o componente funciona com
fallback puro AST quando Ruff/Pyright não estão instalados.

Este componente pode ser carregado dinamicamente pelo ComponentManager
do NEXUS a partir do repositório GitHub oficial, ou executado standalone.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _bootstrap_python_package(package: str) -> tuple[bool, str]:
    """Instala uma dependência no Python atual, sem sudo."""
    command = [sys.executable, "-m", "pip", "install"]
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        command.append("--user")
    command.append(package)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode == 0:
        try:
            import site
            user_bin = str(Path(site.getuserbase()) / "bin")
            if user_bin not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = user_bin + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass
        return True, (result.stdout or "instalado").strip()[-500:]
    return False, (result.stderr or result.stdout or "pip falhou").strip()[-1000:]


try:
    import jedi as _jedi
except ImportError:
    _jedi = None

try:
    from prompt_toolkit.completion import Completer as _PTCompleter
except ImportError:
    _PTCompleter = None


@dataclass
class CodeDiagnostic:
    tool: str
    severity: str
    message: str
    line: int = 0
    column: int = 0
    code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool, "severity": self.severity, "message": self.message,
            "line": self.line, "column": self.column, "code": self.code,
        }


class CodeIntelligenceEngine:
    """Diagnóstico local em camadas, sem tornar ferramentas externas obrigatórias."""
    TOOL_COMMANDS = {"ruff": "ruff", "pyright": "pyright"}

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}

    def capabilities(self) -> dict[str, bool]:
        return {
            "ast": True,
            "ruff": shutil.which(self.TOOL_COMMANDS["ruff"]) is not None,
            "pyright": shutil.which(self.TOOL_COMMANDS["pyright"]) is not None,
            "jedi": _jedi is not None,
            "prompt_toolkit": _PTCompleter is not None,
        }

    def bootstrap_dependencies(self) -> list[dict[str, str]]:
        """Instala o que faltar e retorna status explícito de cada componente."""
        global _jedi, _PTCompleter
        statuses: list[dict[str, str]] = []
        python_packages = [("jedi", "jedi"), ("prompt_toolkit", "prompt_toolkit")]
        for label, module_name in python_packages:
            try:
                __import__(module_name)
                statuses.append({"name": label, "status": "ATIVO", "detail": "biblioteca carregada"})
                continue
            except ImportError:
                pass
            print(f"[NEXUS] Instalando biblioteca {label}...")
            installed, detail = _bootstrap_python_package(label)
            if installed:
                try:
                    if label == "jedi":
                        import jedi as _loaded_jedi
                        _jedi = _loaded_jedi
                    else:
                        import prompt_toolkit.completion as _loaded_pt
                        _PTCompleter = _loaded_pt.Completer
                    statuses.append({"name": label, "status": "INSTALADO", "detail": "carregado com sucesso"})
                except ImportError as exc:
                    statuses.append({"name": label, "status": "ERRO", "detail": str(exc)})
            else:
                statuses.append({"name": label, "status": "ERRO", "detail": detail})

        if shutil.which("ruff"):
            statuses.append({"name": "ruff", "status": "ATIVO", "detail": shutil.which("ruff") or ""})
        else:
            print("[NEXUS] Instalando ferramenta Ruff...")
            installed, detail = _bootstrap_python_package("ruff")
            statuses.append({"name": "ruff", "status": "INSTALADO" if installed else "ERRO", "detail": detail})

        if shutil.which("pyright"):
            statuses.append({"name": "pyright", "status": "ATIVO", "detail": shutil.which("pyright") or ""})
        else:
            npm = shutil.which("npm")
            if npm:
                print("[NEXUS] Instalando ferramenta Pyright via npm (local)...")
                try:
                    local_bin = Path.home() / ".local" / "bin"
                    local_bin.mkdir(parents=True, exist_ok=True)
                    env = os.environ.copy()
                    env["npm_config_prefix"] = str(Path.home() / ".npm-global")
                    result = subprocess.run([npm, "install", "--prefix", str(Path.home() / ".npm-global"), "pyright"], capture_output=True, text=True, timeout=180, check=False)
                    pyright_bin = Path.home() / ".npm-global" / "node_modules" / ".bin" / "pyright"
                    ok = result.returncode == 0 and (shutil.which("pyright") is not None or pyright_bin.exists())
                    if pyright_bin.exists() and str(pyright_bin.parent) not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = str(pyright_bin.parent) + os.pathsep + os.environ.get("PATH", "")
                    detail = (result.stderr or result.stdout or "npm falhou").strip()[-1000:]
                    if ok:
                        detail = str(shutil.which("pyright") or str(pyright_bin))
                    statuses.append({"name": "pyright", "status": "INSTALADO" if ok else "ERRO", "detail": detail})
                except (OSError, subprocess.SubprocessError) as exc:
                    statuses.append({"name": "pyright", "status": "ERRO", "detail": str(exc)})
            else:
                statuses.append({"name": "pyright", "status": "PENDENTE", "detail": "npm não encontrado"})
        return statuses

    def _ast_diagnostics(self, source: str, filename: str) -> list[CodeDiagnostic]:
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            return [CodeDiagnostic("ast", "error", exc.msg, int(exc.lineno or 0), int(exc.offset or 0), "syntax")]
        diagnostics: list[CodeDiagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                diagnostics.append(CodeDiagnostic("ast", "warning", "except genérico pode ocultar erros; prefira uma exceção específica", node.lineno, node.col_offset + 1, "bare-except"))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node) is None:
                diagnostics.append(CodeDiagnostic("ast", "info", f"função {node.name!r} sem docstring", node.lineno, node.col_offset + 1, "missing-docstring"))
        return diagnostics

    def _external_diagnostics(self, tool: str, source: str, filename: str) -> list[CodeDiagnostic]:
        executable = shutil.which(self.TOOL_COMMANDS[tool])
        if not executable:
            return []
        with tempfile.TemporaryDirectory(prefix="nexus-intel-") as temp_dir:
            path = Path(temp_dir) / Path(filename).name
            path.write_text(source, encoding="utf-8")
            if tool == "ruff":
                command = [executable, "check", "--output-format", "json", str(path)]
            else:
                command = [executable, "--outputjson", str(path)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
            except (OSError, subprocess.SubprocessError):
                return []
            output = (result.stdout or result.stderr or "").strip()
            if not output:
                return []
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                return [CodeDiagnostic(tool, "warning", output[:500], 0, 0, "tool-output")]
            diagnostics: list[CodeDiagnostic] = []
            items = payload if tool == "ruff" and isinstance(payload, list) else payload.get("generalDiagnostics", []) if isinstance(payload, dict) else []
            for item in items:
                if tool == "ruff":
                    location = item.get("location", {})
                    diagnostics.append(CodeDiagnostic(tool, "error" if item.get("code", "").startswith(("E", "F")) else "warning", str(item.get("message", "")), int(location.get("row", 0)), int(location.get("column", 0)), str(item.get("code", ""))))
                else:
                    severity = str(item.get("severity", "error")).lower() or "error"
                    rng = item.get("range", {})
                    start = rng.get("start", {})
                    diagnostics.append(CodeDiagnostic(tool, severity, str(item.get("message", "")), int(start.get("line", 0)) + 1, int(start.get("character", 0)) + 1, str(item.get("rule", ""))))
            return diagnostics[:100]

    def analyze(self, source: str, filename: str = "<nexus-generated>") -> dict[str, Any]:
        diagnostics = self._ast_diagnostics(source, filename)
        if not any(item.severity == "error" for item in diagnostics):
            diagnostics.extend(self._external_diagnostics("ruff", source, filename))
            diagnostics.extend(self._external_diagnostics("pyright", source, filename))
        errors = [item for item in diagnostics if item.severity == "error"]
        return {"filename": filename, "capabilities": self.capabilities(), "diagnostics": [item.as_dict() for item in diagnostics], "errors": len(errors), "warnings": sum(item.severity == "warning" for item in diagnostics), "ok": not errors}

    def complete(self, source: str, line: int, column: int, filename: str = "<nexus>") -> list[dict[str, str]]:
        if _jedi is None:
            return []
        try:
            script = _jedi.Script(code=source, path=filename)
            return [{"name": item.name, "type": item.type, "description": item.description} for item in script.complete(line=line, column=column)[:50]]
        except Exception:
            return []

    def format_report(self, report: dict[str, Any]) -> str:
        lines = [f"Code Intelligence: {'OK' if report['ok'] else 'ERROS'} | ferramentas: " + ", ".join(name for name, enabled in report["capabilities"].items() if enabled)]
        for item in report["diagnostics"]:
            location = f"{item['line']}:{item['column']}" if item["line"] else "-"
            lines.append(f"[{item['severity'].upper()}] {item['tool']} {location} {item['code']}: {item['message']}")
        return "\n".join(lines)


COMPONENT_METADATA = {
    "id": "code_intelligence",
    "name": "Code Intelligence Engine",
    "path": "components/code_intelligence.py",
    "type": "analyzer",
    "version": "1.0.0",
    "description": "Diagnóstico de código Python em camadas: AST, Ruff, Pyright, Jedi",
    "entrypoint": "CodeIntelligenceEngine",
    "dependencies": [],
    "compatibility": ">=8.0",
}
