"""CLI bridge for the YouTube playlist manager's download pipeline."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from youtube_playlist_manager_v2 import DOWNLOAD_BASE, YTDLP_BASE, fmt_duration, parse_yt_dlp_json

DEFAULT_OUTPUT = Path.home() / "Music" / "YouTube"


class YouTubeDownloadError(Exception):
    """Raised when YouTube search or download cannot be completed."""


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def ensure_yt_dlp() -> tuple[bool, str]:
    """Find yt-dlp or install it for the current Python user."""
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if executable:
        return True, executable
    if importlib.util.find_spec("yt_dlp") is not None:
        return True, f"{sys.executable} -m yt_dlp"

    try:
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "yt-dlp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "pip falhou").strip()[-2000:]
        return False, detail

    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if executable:
        return True, executable
    if importlib.util.find_spec("yt_dlp") is not None:
        return True, f"{sys.executable} -m yt_dlp"
    return False, "A instalação terminou, mas o comando não ficou disponível."


def _without_browser_cookies(command: list[str]) -> list[str]:
    """Remove the optional Chrome cookie source from an yt-dlp command."""
    filtered: list[str] = []
    skip_next = False
    for item in command:
        if skip_next:
            skip_next = False
            continue
        if item == "--cookies-from-browser":
            skip_next = True
            continue
        filtered.append(item)
    return filtered


def _yt_dlp_command(base: list[str], use_browser_cookies: bool = True) -> list[str]:
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if executable:
        command = [executable, *base[1:]]
    elif importlib.util.find_spec("yt_dlp") is not None:
        command = [sys.executable, "-m", "yt_dlp", *base[1:]]
    else:
        raise YouTubeDownloadError("yt-dlp não está instalado.")
    if not use_browser_cookies:
        command = _without_browser_cookies(command)
    return command


def _cookie_error(output: str) -> bool:
    lowered = output.casefold()
    return "secretstorage" in lowered or "cookies-from-browser" in lowered and "not installed" in lowered


def search_first_five(query: str) -> list[dict[str, Any]]:
    """Search YouTube and return up to five safe, direct video results."""
    command = _yt_dlp_command(YTDLP_BASE) + [
        "--flat-playlist",
        "--dump-single-json",
        "--skip-download",
        "ytsearch5:" + query,
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if process.returncode != 0 and _cookie_error(process.stderr or process.stdout):
            process = subprocess.run(
                _yt_dlp_command(YTDLP_BASE, use_browser_cookies=False) + [
                    "--flat-playlist",
                    "--dump-single-json",
                    "--skip-download",
                    "ytsearch5:" + query,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise YouTubeDownloadError(f"Não foi possível executar o yt-dlp: {exc}") from exc

    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "sem detalhes").strip()[-2500:]
        raise YouTubeDownloadError(f"A pesquisa do YouTube falhou:\n{detail}")

    try:
        data = parse_yt_dlp_json(process.stdout)
    except (ValueError, json.JSONDecodeError) as exc:
        raise YouTubeDownloadError(f"A resposta da pesquisa não pôde ser lida: {exc}") from exc

    entries = data.get("entries", []) if isinstance(data, dict) else []
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "").strip()
        if not video_id or len(video_id) < 6 or " " in video_id:
            continue
        url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if not url or not ("youtube.com" in url or "youtu.be" in url):
            url = f"https://www.youtube.com/watch?v={video_id}"
        results.append(
            {
                "id": video_id,
                "title": str(entry.get("title") or "Vídeo sem título").strip(),
                "channel": str(entry.get("channel") or entry.get("uploader") or "").strip(),
                "duration": entry.get("duration") or 0,
                "url": url,
            }
        )
        if len(results) == 5:
            break
    return results


def download_results(results: list[dict[str, Any]], output_dir: Path = DEFAULT_OUTPUT) -> None:
    """Download the confirmed results using the attached manager settings."""
    if not results:
        raise YouTubeDownloadError("Não há resultados confirmados para baixar.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title)s.%(ext)s")
    command = _yt_dlp_command(DOWNLOAD_BASE) + ["-o", output_template]
    command.extend(str(result["url"]) for result in results)

    def run_download(download_command: list[str]) -> tuple[int, list[str]]:
        try:
            process = subprocess.Popen(
                download_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise YouTubeDownloadError(f"Não foi possível iniciar o download: {exc}") from exc

        output: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if line:
                output.append(line)
                print(f"[BAIXAR] {line}", flush=True)
        return process.wait(), output

    code, output = run_download(command)
    if code != 0 and _cookie_error("\n".join(output)):
        print("[BAIXAR] Cookies do Chrome indisponíveis; tentando sem cookies...", flush=True)
        fallback = _yt_dlp_command(DOWNLOAD_BASE, use_browser_cookies=False) + ["-o", output_template]
        fallback.extend(str(result["url"]) for result in results)
        code, output = run_download(fallback)
    if code != 0:
        raise YouTubeDownloadError(f"O yt-dlp terminou com código {code}.")


def format_result(index: int, result: dict[str, Any]) -> str:
    duration = fmt_duration(result.get("duration"))
    channel = result.get("channel") or "canal não informado"
    return f"{index}. {result['title']} — {channel} — {duration}"
