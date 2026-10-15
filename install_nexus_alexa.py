
#!/usr/bin/env python3
"""Instalador seguro para preparar o pacote da NEXUS Alexa Skill."""

import argparse
import compileall
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SDK_VERSION = "1.19.0"


def run(command, cwd=None, check=True):
    print("\n>", " ".join(map(str, command)))
    return subprocess.run(
        list(map(str, command)),
        cwd=cwd,
        check=check,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Pasta raiz do projeto NEXUS",
    )
    args = parser.parse_args()

    root = Path(args.project).expanduser().resolve()
    lam = root if root.name == "lambda" else root / "lambda"

    if not lam.is_dir():
        print(f"ERRO: pasta lambda/ não encontrada em {root}")
        print("Informe a pasta correta do projeto.")
        return 1

    required = [
        lam / "lambda_function.py",
        lam / "utils.py",
        lam / "requirements.txt",
        lam / "nexus_bridge" / "nexus_bridge.py",
        lam / "tests" / "test_nexus_skill.py",
        lam / "models" / "interactionModel.json",
    ]

    missing = [p for p in required if not p.is_file()]
    if missing:
        print("ERRO: arquivos necessários não encontrados:")
        for p in missing:
            print(f" - {p}")
        return 1

    print(f"Projeto: {root}")
    print(f"Skill:   {lam}")

    # Ambiente isolado para não alterar o Python do sistema.
    venv = root / ".venv-nexus-alexa"
    if not (venv / "pyvenv.cfg").exists():
        run([sys.executable, "-m", "venv", venv])

    python = venv / "bin" / "python"
    pip = [str(python), "-m", "pip"]

    run([*pip, "install", "--upgrade", "pip"])

    # Dependências para executar os testes locais.
    run([*pip, "install", f"ask-sdk-core=={SDK_VERSION}"])

    # Verifica sintaxe antes de empacotar.
    if not compileall.compile_dir(str(lam), quiet=1):
        print("ERRO: falha na compilação de arquivos Python.")
        return 1

    # Executa os testes existentes, sem presumir que todos passarão.
    test = lam / "tests" / "test_nexus_skill.py"
    result = run([str(python), str(test)], cwd=root, check=False)

    if result.returncode != 0:
        print("\nATENÇÃO: os testes falharam.")
        print("O empacotamento não será considerado aprovado.")
        return result.returncode or 1

    # Recria somente a pasta de empacotamento gerada pelo instalador.
    package = lam / "package"
    if package.exists():
        shutil.rmtree(package)

    package.mkdir()
    run([
        *pip, "install",
        "--target", str(package),
        f"ask-sdk-core=={SDK_VERSION}",
    ])

    output = lam / "nexus_skill.zip"
    if output.exists():
        backup = lam / "nexus_skill.zip.bak"
        shutil.copy2(output, backup)
        print(f"Backup anterior: {backup}")

    # Coloca dependências e arquivos de entrada na raiz do ZIP.
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for file in package.rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                archive.write(file, file.relative_to(package))

        for name in ("lambda_function.py", "utils.py"):
            archive.write(lam / name, name)

    # Verificação básica do pacote.
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        expected = {
            "lambda_function.py",
            "utils.py",
            "ask_sdk_core/__init__.py",
        }
        absent = expected - names
        if absent:
            print("ERRO: pacote incompleto:", ", ".join(sorted(absent)))
            return 1

    print("\nPACOTE PREPARADO COM SUCESSO")
    print(f"Arquivo: {output}")
    print(f"Tamanho: {output.stat().st_size:,} bytes")
    print("\nHandler AWS: lambda_function.lambda_handler")
    print("Runtime recomendado: Python 3.12")
    print("\nPróximo passo: configurar e testar a AWS Lambda.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"\nERRO DE INSTALAÇÃO: {exc}", file=sys.stderr)
        raise SystemExit(1)
