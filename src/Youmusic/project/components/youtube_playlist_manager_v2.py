import os
import re
import sys
import json
import queue
import shutil
import threading
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ============================================================
# CONFIGURAÇÃO
# ============================================================

APP_TITLE = "YouTube Playlist Manager"

DEFAULT_OUTPUT = os.path.expanduser(
    "~/Music/YouTube"
)

YTDLP_BASE = [
    "yt-dlp",

    "--cookies-from-browser",
    "chrome",

    "--js-runtimes",
    "deno",

    "--remote-components",
    "ejs:npm",
]


DOWNLOAD_BASE = YTDLP_BASE + [
    "-f",
    "bestaudio/best",

    "-x",

    "--audio-format",
    "mp3",

    "--audio-quality",
    "320K",

    "--embed-thumbnail",

    "--add-metadata",

    "--newline",
]


CACHE_DIR = (
    Path.home()
    / ".cache"
    / "youtube-playlist-manager"
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# EVENT QUEUE
# ============================================================

events = queue.Queue()


# ============================================================
# UTILITÁRIOS
# ============================================================

def command_exists(command):
    return shutil.which(command) is not None


def safe_int(value, default=0):
    try:
        if value is None:
            return default

        return int(value)

    except Exception:
        return default


def fmt_duration(seconds):

    seconds = safe_int(seconds)

    if not seconds:
        return "--:--"

    h, rem = divmod(
        seconds,
        3600
    )

    m, s = divmod(
        rem,
        60
    )

    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


def shorten(text, length=80):

    text = str(
        text or ""
    ).strip()

    if len(text) <= length:
        return text

    return (
        text[:length - 1]
        + "…"
    )


def safe_filename(text):

    text = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        str(text)
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def open_folder(path):

    try:

        if sys.platform.startswith("linux"):

            subprocess.Popen(
                ["xdg-open", path]
            )

        elif sys.platform == "darwin":

            subprocess.Popen(
                ["open", path]
            )

        elif os.name == "nt":

            os.startfile(path)

    except Exception:
        pass


def is_playlist_url(url):

    if not url:
        return False

    try:

        parsed = urllib.parse.urlparse(
            url
        )

        host = (
            parsed.netloc
            or ""
        ).lower()

        query = urllib.parse.parse_qs(
            parsed.query
        )

        return (
            (
                "youtube.com" in host
                or "youtu.be" in host
            )
            and "list" in query
            and bool(
                query.get("list", [""])[0]
            )
        )

    except Exception:

        return False


def extract_playlist_id(url):

    if not url:
        return ""

    try:

        parsed = urllib.parse.urlparse(
            url
        )

        query = urllib.parse.parse_qs(
            parsed.query
        )

        values = query.get(
            "list",
            []
        )

        if values:
            return str(
                values[0]
            ).strip()

    except Exception:
        pass

    return ""


def valid_playlist_id(value):

    if not value:
        return False

    value = str(
        value
    ).strip()

    if not value:
        return False

    # O ID real de playlist não deve ser
    # simplesmente o termo pesquisado.
    #
    # Exemplos reais:
    # PLxxxxxxxxxxxxxxxx
    # UUxxxxxxxxxxxxxxxx
    # LLxxxxxxxxxxxxxxxx
    # OLxxxxxxxxxxxxxxxx
    # RDxxxxxxxxxxxxxxxx
    #
    # Também aceitamos IDs que não sigam
    # exatamente esse prefixo, desde que
    # tenham tamanho plausível.

    if len(value) < 10:
        return False

    if " " in value:
        return False

    return True


# ============================================================
# JSON ROBUSTO
# ============================================================

def parse_yt_dlp_json(stdout):

    """
    Tenta interpretar a saída do yt-dlp.

    Normalmente --dump-single-json deveria
    produzir JSON puro.

    Entretanto, versões diferentes do yt-dlp,
    extractors e alterações do YouTube podem
    introduzir conteúdo inesperado.

    Fazemos algumas tentativas seguras.
    """

    if not stdout:
        raise ValueError(
            "yt-dlp não retornou dados em stdout."
        )

    text = stdout.strip()

    # --------------------------------------------------------
    # PRIMEIRA TENTATIVA
    # --------------------------------------------------------

    try:

        return json.loads(
            text
        )

    except json.JSONDecodeError:
        pass

    # --------------------------------------------------------
    # SEGUNDA TENTATIVA
    #
    # Procura o primeiro objeto JSON completo.
    # --------------------------------------------------------

    decoder = json.JSONDecoder()

    for match in re.finditer(
        r"[\{\[]",
        text
    ):

        start = match.start()

        try:

            data, end = decoder.raw_decode(
                text[start:]
            )

            if isinstance(
                data,
                (dict, list)
            ):

                return data

        except json.JSONDecodeError:
            continue

    # --------------------------------------------------------
    # ERRO
    # --------------------------------------------------------

    preview = text[-5000:]

    raise ValueError(
        "O yt-dlp não retornou JSON válido.\n\n"
        "Últimos dados recebidos:\n\n"
        + preview
    )


# ============================================================
# APLICAÇÃO
# ============================================================

class App(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title(
            APP_TITLE
        )

        self.geometry(
            "1180x820"
        )

        self.minsize(
            950,
            650
        )

        self.configure(
            bg="#111318"
        )

        self.output_dir = (
            DEFAULT_OUTPUT
        )

        self.search_results = []

        self.playlists = {}

        self.video_results = []

        self.thumb_refs = {}

        self.download_jobs = {}

        self.job_counter = 0

        self._build_style()

        self._build_ui()

        self.after(
            100,
            self._process_events
        )

        self._startup_check()

    # ========================================================
    # ESTILO
    # ========================================================

    def _build_style(self):

        style = ttk.Style(
            self
        )

        try:
            style.theme_use(
                "clam"
            )
        except Exception:
            pass

        style.configure(
            "TFrame",
            background="#111318"
        )

        style.configure(
            "Card.TFrame",
            background="#1b1e24"
        )

        style.configure(
            "TLabel",
            background="#111318",
            foreground="#e7e9ee",
            font=(
                "DejaVu Sans",
                10
            )
        )

        style.configure(
            "Title.TLabel",
            background="#111318",
            foreground="#ffffff",
            font=(
                "DejaVu Sans",
                22,
                "bold"
            )
        )

        style.configure(
            "Muted.TLabel",
            background="#111318",
            foreground="#8d94a3",
            font=(
                "DejaVu Sans",
                9
            )
        )

        style.configure(
            "Section.TLabel",
            background="#111318",
            foreground="#ffffff",
            font=(
                "DejaVu Sans",
                12,
                "bold"
            )
        )

        style.configure(
            "TButton",
            font=(
                "DejaVu Sans",
                9,
                "bold"
            ),
            padding=(
                10,
                7
            )
        )

        style.configure(
            "Accent.TButton",
            font=(
                "DejaVu Sans",
                9,
                "bold"
            ),
            padding=(
                12,
                8
            )
        )

        style.configure(
            "TEntry",
            padding=8
        )

        style.configure(
            "Horizontal.TProgressbar",
            thickness=7
        )

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self):

        header = ttk.Frame(
            self
        )

        header.pack(
            fill="x",
            padx=24,
            pady=(
                20,
                8
            )
        )

        ttk.Label(
            header,
            text="YouTube Playlist Manager",
            style="Title.TLabel"
        ).pack(
            anchor="w"
        )

        ttk.Label(
            header,
            text=(
                "Pesquise artistas, bandas, músicas ou "
                "álbuns e baixe playlists em MP3 320K"
            ),
            style="Muted.TLabel"
        ).pack(
            anchor="w",
            pady=(3, 0)
        )

        # ----------------------------------------------------
        # PESQUISA
        # ----------------------------------------------------

        search = ttk.Frame(
            self
        )

        search.pack(
            fill="x",
            padx=24,
            pady=12
        )

        self.search_var = (
            tk.StringVar()
        )

        self.search_entry = ttk.Entry(
            search,
            textvariable=self.search_var,
            font=(
                "DejaVu Sans",
                13
            )
        )

        self.search_entry.pack(
            side="left",
            fill="x",
            expand=True
        )

        self.search_entry.bind(
            "<Return>",
            lambda e: self.search()
        )

        self.search_btn = ttk.Button(
            search,
            text="🔎 Pesquisar",
            style="Accent.TButton",
            command=self.search
        )

        self.search_btn.pack(
            side="left",
            padx=(8, 0)
        )

        # ----------------------------------------------------
        # PASTA
        # ----------------------------------------------------

        folder = ttk.Frame(
            self
        )

        folder.pack(
            fill="x",
            padx=24,
            pady=(0, 10)
        )

        ttk.Label(
            folder,
            text="Destino:"
        ).pack(
            side="left"
        )

        self.output_var = (
            tk.StringVar(
                value=self.output_dir
            )
        )

        ttk.Entry(
            folder,
            textvariable=self.output_var
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=8
        )

        ttk.Button(
            folder,
            text="Escolher",
            command=self.choose_folder
        ).pack(
            side="left"
        )

        ttk.Button(
            folder,
            text="Abrir pasta",
            command=lambda:
                open_folder(
                    self.output_var.get()
                )
        ).pack(
            side="left",
            padx=(6, 0)
        )

        # ----------------------------------------------------
        # NOTEBOOK
        # ----------------------------------------------------

        notebook = ttk.Notebook(
            self
        )

        notebook.pack(
            fill="both",
            expand=True,
            padx=24,
            pady=(0, 10)
        )

        self.results_tab = ttk.Frame(
            notebook
        )

        self.queue_tab = ttk.Frame(
            notebook
        )

        self.log_tab = ttk.Frame(
            notebook
        )

        notebook.add(
            self.results_tab,
            text="  Resultados  "
        )

        notebook.add(
            self.queue_tab,
            text="  Downloads  "
        )

        notebook.add(
            self.log_tab,
            text="  Log  "
        )

        self._build_results_tab()

        self._build_queue_tab()

        self._build_log_tab()

        # ----------------------------------------------------
        # BARRA INFERIOR
        # ----------------------------------------------------

        bottom = ttk.Frame(
            self
        )

        bottom.pack(
            fill="x",
            padx=24,
            pady=(0, 18)
        )

        self.status_var = (
            tk.StringVar(
                value="Pronto."
            )
        )

        ttk.Label(
            bottom,
            textvariable=self.status_var,
            style="Muted.TLabel"
        ).pack(
            side="left"
        )

        self.total_progress = (
            ttk.Progressbar(
                bottom,
                mode="determinate",
                maximum=100
            )
        )

        self.total_progress.pack(
            side="right",
            fill="x",
            expand=True,
            padx=(20, 0)
        )

    # ========================================================
    # RESULTADOS
    # ========================================================

    def _build_results_tab(self):

        top = ttk.Frame(
            self.results_tab
        )

        top.pack(
            fill="x",
            padx=10,
            pady=10
        )

        self.result_count_var = (
            tk.StringVar(
                value=(
                    "Faça uma pesquisa "
                    "para começar."
                )
            )
        )

        ttk.Label(
            top,
            textvariable=self.result_count_var,
            style="Muted.TLabel"
        ).pack(
            side="left"
        )

        ttk.Button(
            top,
            text="Limpar",
            command=self.clear_results
        ).pack(
            side="right"
        )

        container = ttk.Frame(
            self.results_tab
        )

        container.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=(0, 10)
        )

        self.results_canvas = tk.Canvas(
            container,
            bg="#111318",
            highlightthickness=0
        )

        self.results_scroll = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.results_canvas.yview
        )

        self.results_inner = tk.Frame(
            self.results_canvas,
            bg="#111318"
        )

        self.results_inner.bind(
            "<Configure>",
            lambda e:
                self.results_canvas.configure(
                    scrollregion=
                    self.results_canvas.bbox("all")
                )
        )

        self.results_window = (
            self.results_canvas.create_window(
                (0, 0),
                window=self.results_inner,
                anchor="nw"
            )
        )

        self.results_canvas.configure(
            yscrollcommand=
            self.results_scroll.set
        )

        self.results_canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        self.results_scroll.pack(
            side="right",
            fill="y"
        )

        self.results_canvas.bind(
            "<Configure>",
            lambda e:
                self.results_canvas.itemconfigure(
                    self.results_window,
                    width=e.width
                )
        )

    # ========================================================
    # DOWNLOAD QUEUE
    # ========================================================

    def _build_queue_tab(self):

        top = ttk.Frame(
            self.queue_tab
        )

        top.pack(
            fill="x",
            padx=10,
            pady=10
        )

        ttk.Label(
            top,
            text="Fila de downloads",
            style="Section.TLabel"
        ).pack(
            side="left"
        )

        ttk.Button(
            top,
            text="Limpar concluídos",
            command=self.clear_finished_jobs
        ).pack(
            side="right"
        )

        container = ttk.Frame(
            self.queue_tab
        )

        container.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=(0, 10)
        )

        self.queue_canvas = tk.Canvas(
            container,
            bg="#111318",
            highlightthickness=0
        )

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.queue_canvas.yview
        )

        self.queue_inner = tk.Frame(
            self.queue_canvas,
            bg="#111318"
        )

        self.queue_inner.bind(
            "<Configure>",
            lambda e:
                self.queue_canvas.configure(
                    scrollregion=
                    self.queue_canvas.bbox("all")
                )
        )

        window = (
            self.queue_canvas.create_window(
                (0, 0),
                window=self.queue_inner,
                anchor="nw"
            )
        )

        self.queue_canvas.configure(
            yscrollcommand=
            scrollbar.set
        )

        self.queue_canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.queue_canvas.bind(
            "<Configure>",
            lambda e:
                self.queue_canvas.itemconfigure(
                    window,
                    width=e.width
                )
        )

    # ========================================================
    # LOG
    # ========================================================

    def _build_log_tab(self):

        frame = ttk.Frame(
            self.log_tab
        )

        frame.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=10
        )

        self.log_text = tk.Text(
            frame,
            bg="#080a0d",
            fg="#d7dbe3",
            insertbackground="#ffffff",
            font=(
                "DejaVu Sans Mono",
                9
            ),
            relief="flat",
            wrap="word"
        )

        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.log_text.yview
        )

        self.log_text.configure(
            yscrollcommand=
            scroll.set
        )

        self.log_text.pack(
            side="left",
            fill="both",
            expand=True
        )

        scroll.pack(
            side="right",
            fill="y"
        )

        ttk.Button(
            self.log_tab,
            text="Limpar log",
            command=lambda:
                self.log_text.delete(
                    "1.0",
                    "end"
                )
        ).pack(
            anchor="e",
            padx=10,
            pady=(0, 10)
        )

    # ========================================================
    # LOG
    # ========================================================

    def log(self, text):

        self.log_text.insert(
            "end",
            str(text)
            + "\n"
        )

        self.log_text.see(
            "end"
        )

    # ========================================================
    # STARTUP
    # ========================================================

    def _startup_check(self):

        self.log(
            "=== YouTube Playlist Manager v2 ==="
        )

        self.log(
            "Sistema iniciado."
        )

        self.log(
            f"Destino: {self.output_dir}"
        )

        if command_exists("yt-dlp"):

            self.log(
                "✓ yt-dlp encontrado."
            )

        else:

            self.log(
                "✗ yt-dlp NÃO encontrado."
            )

        if command_exists("ffmpeg"):

            self.log(
                "✓ ffmpeg encontrado."
            )

        else:

            self.log(
                "⚠ ffmpeg não encontrado."
            )

        if command_exists("deno"):

            self.log(
                "✓ Deno encontrado."
            )

        else:

            self.log(
                "⚠ Deno não encontrado no PATH."
            )

        if not command_exists(
            "yt-dlp"
        ):

            self.status_var.set(
                "Instale o yt-dlp para começar."
            )

    # ========================================================
    # PASTA
    # ========================================================

    def choose_folder(self):

        folder = filedialog.askdirectory(
            initialdir=
            self.output_var.get()
        )

        if folder:

            self.output_var.set(
                folder
            )

            self.log(
                "Pasta de destino alterada: "
                + folder
            )

    # ========================================================
    # PESQUISA
    # ========================================================

    def search(self):

        query = (
            self.search_var
            .get()
            .strip()
        )

        if not query:

            messagebox.showwarning(
                "Pesquisa",
                (
                    "Digite o nome de uma banda, "
                    "artista, música ou álbum."
                )
            )

            return

        if not command_exists(
            "yt-dlp"
        ):

            messagebox.showerror(
                "yt-dlp não encontrado",
                (
                    "O programa precisa do "
                    "yt-dlp instalado."
                )
            )

            return

        self.search_btn.configure(
            state="disabled"
        )

        self.result_count_var.set(
            "Pesquisando…"
        )

        self.status_var.set(
            f"Pesquisando: {query}"
        )

        self.clear_results(
            log=False
        )

        self.log("")

        self.log(
            "=" * 70
        )

        self.log(
            f"PESQUISA: {query}"
        )

        threading.Thread(
            target=self._search_worker,
            args=(query,),
            daemon=True
        ).start()

    def _search_worker(self, query):

        # ----------------------------------------------------
        # Pesquisa SOMENTE por playlists.
        #
        # O filtro:
        # EgIQAw%253D%253D
        #
        # corresponde ao filtro de playlists do YouTube.
        # ----------------------------------------------------

        search_url = (
            "https://www.youtube.com/results"
            "?search_query="
            + urllib.parse.quote_plus(query)
            + "&sp=EgIQAw%253D%253D"
        )

        command = YTDLP_BASE + [
            "--flat-playlist",
            "--dump-single-json",
            "--skip-download",
            "--playlist-end",
            "30",
            search_url
        ]

        stdout = ""
        stderr = ""

        try:

            self.log(
                "[DEBUG] Executando pesquisa do yt-dlp..."
            )

            process = subprocess.Popen(

                command,

                stdout=subprocess.PIPE,

                stderr=subprocess.PIPE,

                text=True,

                encoding="utf-8",

                errors="replace",

                bufsize=1
            )

            stdout, stderr = (
                process.communicate()
            )

            code = (
                process.returncode
            )

            # ------------------------------------------------
            # LOG TÉCNICO
            # ------------------------------------------------

            if stderr.strip():

                events.put(
                    (
                        "search_stderr",
                        stderr[-8000:]
                    )
                )

            if code != 0:

                events.put(
                    (
                        "search_error",
                        (
                            "yt-dlp terminou com "
                            f"código {code}.\n\n"
                            + stderr[-6000:]
                        )
                    )
                )

                return

            # ------------------------------------------------
            # PARSER
            # ------------------------------------------------

            try:

                data = parse_yt_dlp_json(
                    stdout
                )

            except Exception as parse_error:

                events.put(
                    (
                        "search_error",
                        str(parse_error)
                        + "\n\nSTDERR:\n"
                        + stderr[-3000:]
                    )
                )

                return

            # ------------------------------------------------
            # ENTRIES
            # ------------------------------------------------

            entries = (
                data.get(
                    "entries",
                    []
                )
                if isinstance(
                    data,
                    dict
                )
                else []
            )

            results = []

            for entry in entries:

                if not isinstance(
                    entry,
                    dict
                ):
                    continue

                # --------------------------------------------
                # TÍTULO
                # --------------------------------------------

                title = (
                    entry.get("title")
                    or entry.get(
                        "playlist_title"
                    )
                    or "Playlist sem título"
                )

                # --------------------------------------------
                # URL
                # --------------------------------------------

                url = (
                    entry.get(
                        "webpage_url"
                    )
                    or ""
                )

                # Alguns extractors retornam
                # a URL em "url".

                if not is_playlist_url(
                    url
                ):

                    candidate = (
                        entry.get("url")
                        or ""
                    )

                    if is_playlist_url(
                        candidate
                    ):

                        url = candidate

                # --------------------------------------------
                # ID
                # --------------------------------------------

                playlist_id = (
                    extract_playlist_id(
                        url
                    )
                )

                if not playlist_id:

                    playlist_id = str(
                        entry.get("id")
                        or ""
                    ).strip()

                # --------------------------------------------
                # SEGURANÇA
                # --------------------------------------------

                if not valid_playlist_id(
                    playlist_id
                ):
                    continue

                # --------------------------------------------
                # Se a URL ainda não existir,
                # só construímos a URL usando o
                # ID retornado pelo yt-dlp.
                #
                # NUNCA usamos "query".
                # --------------------------------------------

                if not url:

                    url = (
                        "https://www.youtube.com/"
                        "playlist?list="
                        + playlist_id
                    )

                if not is_playlist_url(
                    url
                ):
                    continue

                # --------------------------------------------
                # THUMBNAIL
                # --------------------------------------------

                thumbnail = (
                    entry.get(
                        "thumbnail"
                    )
                    or ""
                )

                # --------------------------------------------
                # CHANNEL
                # --------------------------------------------

                channel = (
                    entry.get(
                        "channel"
                    )
                    or entry.get(
                        "uploader"
                    )
                    or ""
                )

                results.append(
                    {
                        "id": playlist_id,
                        "title": title,
                        "url": url,
                        "webpage_url": url,
                        "type": "playlist",
                        "ie_key": (
                            entry.get(
                                "ie_key"
                            )
                            or "YoutubeTab"
                        ),
                        "playlist_id": playlist_id,
                        "playlist_title": title,
                        "duration": 0,
                        "thumbnail": thumbnail,
                        "channel": channel
                    }
                )

            # ------------------------------------------------
            # REMOVER DUPLICATAS
            # ------------------------------------------------

            unique = {}

            for item in results:

                key = item[
                    "playlist_id"
                ]

                if key not in unique:

                    unique[key] = item

            results = list(
                unique.values()
            )

            events.put(
                (
                    "search_done",
                    results
                )
            )

        except Exception as e:

            events.put(
                (
                    "search_error",
                    (
                        str(e)
                        + "\n\nSTDERR:\n"
                        + stderr[-5000:]
                        + "\n\nSTDOUT:\n"
                        + stdout[-3000:]
                    )
                )
            )

    # ========================================================
    # RESULTADOS
    # ========================================================

    def display_results(
        self,
        results
    ):

        self.search_results = (
            results
        )

        self.playlists.clear()

        self.video_results.clear()

        for result in results:

            playlist_id = (
                result.get(
                    "playlist_id"
                )
                or result.get(
                    "id"
                )
            )

            if not playlist_id:
                continue

            url = (
                result.get(
                    "url"
                )
                or ""
            )

            if not is_playlist_url(
                url
            ):

                continue

            self.playlists[
                playlist_id
            ] = {

                "id": playlist_id,

                "title": (
                    result.get(
                        "playlist_title"
                    )
                    or result.get(
                        "title"
                    )
                    or "Playlist sem título"
                ),

                "url": url,

                "thumbnail": (
                    result.get(
                        "thumbnail",
                        ""
                    )
                ),

                "channel": (
                    result.get(
                        "channel",
                        ""
                    )
                ),

                "count": None
            }

        # ----------------------------------------------------
        # METADADOS
        # ----------------------------------------------------

        for playlist in (
            self.playlists.values()
        ):

            threading.Thread(
                target=
                self._playlist_metadata_worker,
                args=(
                    playlist["id"],
                    playlist["url"]
                ),
                daemon=True
            ).start()

        self.result_count_var.set(
            f"{len(self.playlists)} playlist(s) • "
            f"{len(self.video_results)} vídeo(s)"
        )

        if (
            not self.playlists
            and not self.video_results
        ):

            tk.Label(
                self.results_inner,
                text=(
                    "Nenhuma playlist encontrada."
                ),
                bg="#111318",
                fg="#8d94a3",
                font=(
                    "DejaVu Sans",
                    12
                )
            ).pack(
                pady=60
            )

            self.status_var.set(
                "Nenhuma playlist encontrada."
            )

            self.log(
                "Nenhuma playlist válida encontrada."
            )

            return

        if self.playlists:

            self._section_label(
                self.results_inner,
                (
                    f"PLAYLISTS "
                    f"({len(self.playlists)})"
                )
            )

            for playlist in (
                self.playlists.values()
            ):

                self._create_playlist_card(
                    playlist
                )

        self.status_var.set(
            "Pesquisa concluída."
        )

        self.log(
            f"Resultados: "
            f"{len(self.playlists)} playlists / "
            f"{len(self.video_results)} vídeos"
        )

    def _section_label(
        self,
        parent,
        text
    ):

        tk.Label(
            parent,
            text=text,
            bg="#111318",
            fg="#ffffff",
            font=(
                "DejaVu Sans",
                11,
                "bold"
            )
        ).pack(
            anchor="w",
            padx=8,
            pady=(12, 7)
        )

    # ========================================================
    # CARD PLAYLIST
    # ========================================================

    def _create_playlist_card(
        self,
        playlist
    ):

        card = tk.Frame(
            self.results_inner,
            bg="#1b1e24",
            padx=12,
            pady=12
        )

        card.pack(
            fill="x",
            padx=5,
            pady=5
        )

        thumb = tk.Label(
            card,
            text="▶",
            bg="#252932",
            fg="#ffffff",
            width=16,
            height=7,
            font=(
                "DejaVu Sans",
                22,
                "bold"
            )
        )

        thumb.pack(
            side="left",
            padx=(0, 12)
        )

        info = tk.Frame(
            card,
            bg="#1b1e24"
        )

        info.pack(
            side="left",
            fill="both",
            expand=True
        )

        tk.Label(
            info,
            text="📁 PLAYLIST",
            bg="#1b1e24",
            fg="#8d94a3",
            font=(
                "DejaVu Sans",
                8,
                "bold"
            )
        ).pack(
            anchor="w"
        )

        tk.Label(
            info,
            text=shorten(
                playlist["title"],
                100
            ),
            bg="#1b1e24",
            fg="#ffffff",
            font=(
                "DejaVu Sans",
                12,
                "bold"
            ),
            wraplength=650,
            justify="left"
        ).pack(
            anchor="w",
            pady=(4, 3)
        )

        count = (
            playlist.get("count")
        )

        if count:
            metadata = (
                f"{count} vídeo(s)"
            )

        else:
            metadata = (
                "Playlist encontrada • "
                "carregando informações…"
            )

        if playlist.get(
            "channel"
        ):

            metadata += (
                " • "
                + playlist["channel"]
            )

        metadata_label = tk.Label(
            info,
            text=metadata,
            bg="#1b1e24",
            fg="#8d94a3",
            font=(
                "DejaVu Sans",
                9
            )
        )

        metadata_label.pack(
            anchor="w"
        )

        actions = tk.Frame(
            card,
            bg="#1b1e24"
        )

        actions.pack(
            side="right",
            padx=(10, 0)
        )

        ttk.Button(
            actions,
            text="⬇ Baixar playlist",
            command=lambda p=playlist:
                self.add_playlist_download(p)
        ).pack(
            pady=3
        )

        ttk.Button(
            actions,
            text="Copiar URL",
            command=lambda u=playlist["url"]:
                self.copy_to_clipboard(u)
        ).pack(
            pady=3
        )

        playlist["_card"] = card

        playlist["_thumb"] = thumb

        playlist["_metadata_label"] = (
            metadata_label
        )

        # Miniatura
        if playlist.get(
            "thumbnail"
        ):

            threading.Thread(
                target=self._thumbnail_worker,
                args=(
                    playlist["thumbnail"],
                    thumb
                ),
                daemon=True
            ).start()

    def _refresh_playlist_card(
        self,
        playlist_id
    ):

        playlist = (
            self.playlists.get(
                playlist_id
            )
        )

        if not playlist:
            return

        label = (
            playlist.get(
                "_metadata_label"
            )
        )

        if label:

            count = (
                playlist.get(
                    "count"
                )
            )

            if count:

                text = (
                    f"{count} vídeo(s)"
                )

            else:

                text = (
                    "Playlist encontrada"
                )

            if playlist.get(
                "channel"
            ):

                text += (
                    " • "
                    + playlist["channel"]
                )

            label.configure(
                text=text
            )

        thumbnail = (
            playlist.get(
                "thumbnail"
            )
        )

        thumb = (
            playlist.get(
                "_thumb"
            )
        )

        if thumbnail and thumb:

            threading.Thread(
                target=self._thumbnail_worker,
                args=(
                    thumbnail,
                    thumb
                ),
                daemon=True
            ).start()

    # ========================================================
    # METADADOS DA PLAYLIST
    # ========================================================

    def _playlist_metadata_worker(
        self,
        playlist_id,
        url
    ):

        command = YTDLP_BASE + [

            "--flat-playlist",

            "--dump-single-json",

            "--skip-download",

            url
        ]

        stdout = ""
        stderr = ""

        try:

            process = subprocess.Popen(

                command,

                stdout=subprocess.PIPE,

                stderr=subprocess.PIPE,

                text=True,

                encoding="utf-8",

                errors="replace"
            )

            stdout, stderr = (
                process.communicate()
            )

            if process.returncode != 0:
                return

            data = parse_yt_dlp_json(
                stdout
            )

            count = (
                data.get(
                    "playlist_count"
                )
            )

            thumbnail = (
                data.get(
                    "thumbnail",
                    ""
                )
            )

            channel = (
                data.get(
                    "channel"
                )
                or data.get(
                    "uploader"
                )
                or data.get(
                    "playlist_uploader"
                )
                or ""
            )

            if count is not None:

                count = safe_int(
                    count,
                    0
                )

            events.put(
                (
                    "playlist_metadata",
                    playlist_id,
                    count,
                    thumbnail,
                    channel
                )
            )

        except Exception:
            pass

    # ========================================================
    # MINIATURAS
    # ========================================================

    def _thumbnail_worker(
        self,
        url,
        label
    ):

        if not url or not label:
            return

        try:

            filename = (
                str(
                    abs(
                        hash(url)
                    )
                )
                + ".jpg"
            )

            path = (
                CACHE_DIR
                / filename
            )

            if not path.exists():

                request = (
                    urllib.request.Request(
                        url,
                        headers={
                            "User-Agent":
                            "Mozilla/5.0"
                        }
                    )
                )

                with urllib.request.urlopen(
                    request,
                    timeout=10
                ) as response:

                    data = (
                        response.read()
                    )

                path.write_bytes(
                    data
                )

            events.put(
                (
                    "thumbnail",
                    str(path),
                    label
                )
            )

        except Exception:
            pass

    def _set_thumbnail(
        self,
        path,
        label
    ):

        try:

            from PIL import (
                Image,
                ImageTk
            )

            image = Image.open(
                path
            )

            image.thumbnail(
                (180, 100)
            )

            photo = ImageTk.PhotoImage(
                image
            )

            label.configure(
                image=photo,
                text=""
            )

            self.thumb_refs[
                id(label)
            ] = photo

        except ImportError:

            pass

        except Exception:

            pass

    # ========================================================
    # DOWNLOAD
    # ========================================================

    def add_playlist_download(
        self,
        playlist
    ):

        output = (
            self.output_var
            .get()
            .strip()
        )

        if not output:

            messagebox.showwarning(
                "Destino",
                "Escolha uma pasta de destino."
            )

            return

        if not is_playlist_url(
            playlist.get("url")
        ):

            messagebox.showerror(
                "URL inválida",
                (
                    "A URL da playlist não "
                    "foi validada pelo programa."
                )
            )

            return

        os.makedirs(
            output,
            exist_ok=True
        )

        self.job_counter += 1

        job_id = (
            self.job_counter
        )

        job = {

            "id": job_id,

            "title": playlist[
                "title"
            ],

            "url": playlist[
                "url"
            ],

            "status": "Na fila",

            "progress": 0,

            "process": None,

            "widget": None
        }

        self.download_jobs[
            job_id
        ] = job

        self._create_job_widget(
            job
        )

        self.log(
            f"[FILA #{job_id}] "
            f"{playlist['title']}"
        )

        self.status_var.set(
            "Playlist adicionada à fila: "
            + playlist["title"]
        )

        threading.Thread(
            target=self._download_worker,
            args=(job,),
            daemon=True
        ).start()

    def add_video_download(
        self,
        video
    ):

        output = (
            self.output_var
            .get()
            .strip()
        )

        if not output:

            messagebox.showwarning(
                "Destino",
                "Escolha uma pasta de destino."
            )

            return

        os.makedirs(
            output,
            exist_ok=True
        )

        self.job_counter += 1

        job_id = (
            self.job_counter
        )

        job = {

            "id": job_id,

            "title": video.get(
                "title",
                "Vídeo"
            ),

            "url": (
                video.get(
                    "webpage_url"
                )
                or video.get(
                    "url"
                )
            ),

            "status": "Na fila",

            "progress": 0,

            "process": None,

            "widget": None
        }

        self.download_jobs[
            job_id
        ] = job

        self._create_job_widget(
            job
        )

        threading.Thread(
            target=self._download_worker,
            args=(job,),
            daemon=True
        ).start()

    # ========================================================
    # JOB WIDGET
    # ========================================================

    def _create_job_widget(
        self,
        job
    ):

        card = tk.Frame(
            self.queue_inner,
            bg="#1b1e24",
            padx=12,
            pady=10
        )

        card.pack(
            fill="x",
            padx=5,
            pady=5
        )

        tk.Label(
            card,
            text=f"#{job['id']}",
            bg="#1b1e24",
            fg="#8d94a3",
            font=(
                "DejaVu Sans Mono",
                9,
                "bold"
            )
        ).pack(
            anchor="w"
        )

        title = tk.Label(
            card,
            text=shorten(
                job["title"],
                100
            ),
            bg="#1b1e24",
            fg="#ffffff",
            font=(
                "DejaVu Sans",
                10,
                "bold"
            ),
            anchor="w"
        )

        title.pack(
            fill="x",
            pady=(3, 5)
        )

        progress = ttk.Progressbar(
            card,
            mode="determinate",
            maximum=100
        )

        progress.pack(
            fill="x"
        )

        status = tk.Label(
            card,
            text="Na fila",
            bg="#1b1e24",
            fg="#8d94a3",
            font=(
                "DejaVu Sans",
                8
            )
        )

        status.pack(
            anchor="w",
            pady=(4, 0)
        )

        job["widget"] = {

            "card": card,

            "progress": progress,

            "status": status
        }

    # ========================================================
    # DOWNLOAD WORKER
    # ========================================================

    def _download_worker(
        self,
        job
    ):

        output = (
            self.output_var
            .get()
            .strip()
        )

        os.makedirs(
            output,
            exist_ok=True
        )

        # ----------------------------------------------------
        # IMPORTANTE:
        #
        # O nome do arquivo será o nome original do vídeo.
        #
        # Estrutura:
        #
        # ~/Music/YouTube/
        #     Playlist/
        #         Música.mp3
        #
        # Não adicionamos "001 -".
        # ----------------------------------------------------

        output_template = os.path.join(
            output,
            "%(playlist)s",
            "%(title)s.%(ext)s"
        )

        command = DOWNLOAD_BASE + [

            "-o",

            output_template,

            job["url"]
        ]

        events.put(
            (
                "job_status",
                job["id"],
                "Baixando…",
                0
            )
        )

        self.log(
            f"[DOWNLOAD #{job['id']}] "
            f"{job['url']}"
        )

        process = None

        try:

            process = subprocess.Popen(

                command,

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT,

                text=True,

                encoding="utf-8",

                errors="replace",

                bufsize=1
            )

            job["process"] = process

            for line in process.stdout:

                line = line.rstrip()

                if not line:
                    continue

                match = re.search(

                    r"\[download\]\s+"
                    r"(\d+(?:\.\d+)?)%",

                    line
                )

                if match:

                    percent = float(
                        match.group(1)
                    )

                    events.put(
                        (
                            "job_status",
                            job["id"],
                            line,
                            percent
                        )
                    )

                else:

                    events.put(
                        (
                            "job_log",
                            job["id"],
                            line
                        )
                    )

            code = (
                process.wait()
            )

            if code == 0:

                events.put(
                    (
                        "job_status",
                        job["id"],
                        "✓ Concluído",
                        100
                    )
                )

                events.put(
                    (
                        "job_done",
                        job["id"],
                        True
                    )
                )

            else:

                events.put(
                    (
                        "job_status",
                        job["id"],
                        (
                            f"⚠ Erro "
                            f"(código {code})"
                        ),
                        0
                    )
                )

                events.put(
                    (
                        "job_done",
                        job["id"],
                        False
                    )
                )

        except Exception as e:

            events.put(
                (
                    "job_status",
                    job["id"],
                    f"Erro: {e}",
                    0
                )
            )

            events.put(
                (
                    "job_done",
                    job["id"],
                    False
                )
            )

    # ========================================================
    # EVENTOS
    # ========================================================

    def _process_events(self):

        try:

            while True:

                event = (
                    events.get_nowait()
                )

                kind = event[0]

                # --------------------------------------------
                # PESQUISA OK
                # --------------------------------------------

                if kind == "search_done":

                    self.search_btn.configure(
                        state="normal"
                    )

                    self.display_results(
                        event[1]
                    )

                # --------------------------------------------
                # STDERR DA PESQUISA
                # --------------------------------------------

                elif kind == "search_stderr":

                    self.log(
                        "[yt-dlp STDERR]"
                    )

                    self.log(
                        event[1]
                    )

                # --------------------------------------------
                # ERRO PESQUISA
                # --------------------------------------------

                elif kind == "search_error":

                    self.search_btn.configure(
                        state="normal"
                    )

                    self.result_count_var.set(
                        "Erro na pesquisa."
                    )

                    self.status_var.set(
                        "Erro na pesquisa."
                    )

                    self.log(
                        "[ERRO PESQUISA]"
                    )

                    self.log(
                        event[1]
                    )

                    messagebox.showerror(

                        "Erro na pesquisa",

                        (
                            "O yt-dlp não conseguiu "
                            "realizar a pesquisa.\n\n"
                            + event[1][-1500:]
                        )
                    )

                # --------------------------------------------
                # METADADOS
                # --------------------------------------------

                elif kind == "playlist_metadata":

                    playlist_id = (
                        event[1]
                    )

                    playlist = (
                        self.playlists.get(
                            playlist_id
                        )
                    )

                    if playlist:

                        playlist["count"] = (
                            event[2]
                        )

                        playlist["thumbnail"] = (
                            event[3]
                            or playlist.get(
                                "thumbnail",
                                ""
                            )
                        )

                        playlist["channel"] = (
                            event[4]
                            or playlist.get(
                                "channel",
                                ""
                            )
                        )

                        self._refresh_playlist_card(
                            playlist_id
                        )

                # --------------------------------------------
                # THUMBNAIL
                # --------------------------------------------

                elif kind == "thumbnail":

                    self._set_thumbnail(
                        event[1],
                        event[2]
                    )

                # --------------------------------------------
                # JOB STATUS
                # --------------------------------------------

                elif kind == "job_status":

                    job_id = event[1]

                    status = event[2]

                    progress = event[3]

                    job = (
                        self.download_jobs.get(
                            job_id
                        )
                    )

                    if job:

                        job["status"] = (
                            status
                        )

                        job["progress"] = (
                            progress
                        )

                        widget = (
                            job["widget"]
                        )

                        widget[
                            "progress"
                        ]["value"] = (
                            progress
                        )

                        widget[
                            "status"
                        ].configure(
                            text=status
                        )

                    self._update_total_progress()

                # --------------------------------------------
                # JOB LOG
                # --------------------------------------------

                elif kind == "job_log":

                    self.log(
                        f"[#{event[1]}] "
                        f"{event[2]}"
                    )

                # --------------------------------------------
                # JOB CONCLUÍDO
                # --------------------------------------------

                elif kind == "job_done":

                    job_id = event[1]

                    success = event[2]

                    job = (
                        self.download_jobs.get(
                            job_id
                        )
                    )

                    if job:

                        if success:

                            job["status"] = (
                                "✓ Concluído"
                            )

                            job["progress"] = (
                                100
                            )

                        else:

                            job["status"] = (
                                "✗ Falhou"
                            )

                        self.log(
                            f"[DOWNLOAD #{job_id}] "
                            + (
                                "CONCLUÍDO"
                                if success
                                else "FALHOU"
                            )
                        )

                    self._update_total_progress()

                    if success:

                        self.status_var.set(
                            "Download concluído."
                        )

                    else:

                        self.status_var.set(
                            "Um download terminou com erro."
                        )

        except queue.Empty:
            pass

        self.after(
            100,
            self._process_events
        )

    # ========================================================
    # PROGRESSO
    # ========================================================

    def _update_total_progress(self):

        jobs = list(
            self.download_jobs.values()
        )

        if not jobs:

            self.total_progress[
                "value"
            ] = 0

            return

        total = sum(

            float(
                job.get(
                    "progress",
                    0
                )
            )

            for job in jobs
        )

        self.total_progress[
            "value"
        ] = (
            total / len(jobs)
        )

    # ========================================================
    # LIMPAR RESULTADOS
    # ========================================================

    def clear_results(
        self,
        log=True
    ):

        for widget in (
            self.results_inner
            .winfo_children()
        ):

            widget.destroy()

        self.search_results.clear()

        self.playlists.clear()

        self.video_results.clear()

        self.result_count_var.set(
            "Nenhum resultado."
        )

        if log:

            self.log(
                "Resultados limpos."
            )

    # ========================================================
    # LIMPAR DOWNLOADS
    # ========================================================

    def clear_finished_jobs(self):

        remove = []

        for job_id, job in (
            self.download_jobs.items()
        ):

            status = str(
                job.get(
                    "status",
                    ""
                )
            )

            if (
                "Concluído" in status
                or "Falhou" in status
            ):

                remove.append(
                    job_id
                )

        for job_id in remove:

            job = (
                self.download_jobs.pop(
                    job_id
                )
            )

            try:

                job[
                    "widget"
                ][
                    "card"
                ].destroy()

            except Exception:
                pass

        self._update_total_progress()

    # ========================================================
    # CLIPBOARD
    # ========================================================

    def copy_to_clipboard(
        self,
        text
    ):

        self.clipboard_clear()

        self.clipboard_append(
            text
        )

        self.update()

        self.status_var.set(
            "URL copiada para a área de transferência."
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        app = App()

        app.mainloop()

    except KeyboardInterrupt:

        pass

