"""CLI bridge for the YouTube playlist manager's download pipeline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from youtube_playlist_manager_v2 import DOWNLOAD_BASE, YTDLP_BASE, fmt_duration, parse_yt_dlp_json

DEFAULT_OUTPUT = Path.home() / "Music" / "YouTube"


class YouTubeDownloadError(Exception):
    """Raised when YouTube search or download cannot be completed."""


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def search_first_five(query: str) -> list[dict[str, Any]]:
    """Search YouTube and return up to five safe, direct video results."""
    command = YTDLP_BASE + [
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
    command = DOWNLOAD_BASE + ["-o", output_template]
    command.extend(str(result["url"]) for result in results)

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YouTubeDownloadError(f"Não foi possível iniciar o download: {exc}") from exc

    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            print(f"[BAIXAR] {line}", flush=True)

    code = process.wait()
    if code != 0:
        raise YouTubeDownloadError(f"O yt-dlp terminou com código {code}.")


def format_result(index: int, result: dict[str, Any]) -> str:
    duration = fmt_duration(result.get("duration"))
    channel = result.get("channel") or "canal não informado"
    return f"{index}. {result['title']} — {channel} — {duration}"
