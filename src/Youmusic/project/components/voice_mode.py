"""Voice mode for NEXUS: transparent bubble, speech recognition, and TTS."""

from __future__ import annotations

import importlib.util
import queue
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional


class VoiceModeError(Exception):
    """Raised when voice mode cannot start or use the microphone."""


class VoiceBubble:
    """Small always-on-top transparent bubble with a listening animation."""

    def __init__(self) -> None:
        self._commands: queue.Queue[str] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._root = None
        self._canvas = None
        self._pulse = 0
        self._status = "ouvindo"
        self._closed = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._closed.clear()
        self._status = "ouvindo"
        self._thread = threading.Thread(target=self._run, name="nexus-voice-bubble", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._closed.set()
        self._commands.put("close")

    def set_status(self, status: str) -> None:
        self._commands.put(status)

    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            return

        try:
            root = tk.Tk()
            self._root = root
            root.title("NEXUS Voice")
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.82)
            root.configure(bg="#07142e")

            width, height = 180, 180
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.geometry(f"{width}x{height}+{screen_width - width - 32}+{screen_height - height - 88}")

            canvas = tk.Canvas(root, width=width, height=height, bg="#07142e", highlightthickness=0)
            canvas.pack()
            self._canvas = canvas
            self._draw(canvas, "ouvindo")
            root.after(120, self._tick)
            root.mainloop()
        except Exception:
            self._root = None

    def _tick(self) -> None:
        root = self._root
        canvas = self._canvas
        if root is None or canvas is None or self._closed.is_set():
            if root is not None:
                root.destroy()
            return

        try:
            while True:
                command = self._commands.get_nowait()
                if command == "close":
                    root.destroy()
                    return
                self._status = command
        except queue.Empty:
            pass

        self._pulse = (self._pulse + 1) % 24
        self._draw(canvas, self._status)
        root.after(120, self._tick)

    def _draw(self, canvas: object, status: str) -> None:
        try:
            canvas.delete("all")
            pulse = abs(12 - self._pulse) * 1.25
            center = 90
            for radius, color in ((68 + pulse, "#173a72"), (54 + pulse / 2, "#075985"), (38, "#0e7490")):
                canvas.create_oval(
                    center - radius, center - radius, center + radius, center + radius,
                    outline=color, width=2,
                )
            canvas.create_oval(55, 55, 125, 125, fill="#062447", outline="#22d3ee", width=2)
            canvas.create_text(center, 84, text="NEXUS", fill="#e0f2fe", font=("Arial", 11, "bold"))
            canvas.create_text(center, 105, text=status.upper(), fill="#67e8f9", font=("Arial", 8, "bold"))
        except Exception:
            pass


class VoiceSession:
    """Continuously recognizes speech, asks ChatGPT, and speaks answers."""

    def __init__(
        self,
        ask: Callable[[str], str],
        browser_factory: Callable[[], object],
        on_log: Callable[[str], None],
    ) -> None:
        self.ask = ask
        self.browser_factory = browser_factory
        self.on_log = on_log
        self.stop_event = threading.Event()
        self.bubble = VoiceBubble()
        self._thread: Optional[threading.Thread] = None
        self._recognizer = None
        self._microphone = None
        self._tts_lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("speech_recognition") is not None

    def start(self) -> None:
        if not self.available():
            raise VoiceModeError(
                "Reconhecimento de voz indisponível. Instale o pacote Python SpeechRecognition "
                "e o suporte de áudio do sistema antes de usar /voice-on."
            )
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self.bubble.start()
        self._thread = threading.Thread(target=self._run, name="nexus-voice-session", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.bubble.stop()
        self.on_log("Modo de voz desativado.")

    def _run(self) -> None:
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._microphone = sr.Microphone()
            with self._microphone as source:
                self.on_log("Ajustando o microfone...")
                self._recognizer.adjust_for_ambient_noise(source, duration=1)

            browser = self.browser_factory()
            try:
                self.on_log("Abrindo ChatGPT para o modo de voz...")
                browser.start()
                browser.ensure_ready()
                self.on_log("NEXUS ouvindo. Fale uma frase.")
                while not self.stop_event.is_set():
                    self.bubble.set_status("ouvindo")
                    with self._microphone as source:
                        try:
                            audio = self._recognizer.listen(source, timeout=2, phrase_time_limit=20)
                        except sr.WaitTimeoutError:
                            continue

                    if self.stop_event.is_set():
                        break
                    self.bubble.set_status("entendi")
                    try:
                        text = self._recognizer.recognize_google(audio, language="pt-BR").strip()
                    except sr.UnknownValueError:
                        self.on_log("Não consegui entender. Tente novamente.")
                        continue
                    except sr.RequestError as exc:
                        self.on_log(f"Serviço de reconhecimento indisponível: {exc}")
                        break

                    if not text:
                        continue
                    self.on_log(f"Você: {text}")
                    if text.casefold() in {"parar", "encerrar voz", "desligar voz", "voice off"}:
                        break

                    self.bubble.set_status("pensando")
                    try:
                        answer = self.ask(text)
                    except Exception as exc:
                        self.on_log(f"NEXUS não conseguiu responder: {exc}")
                        continue

                    if answer:
                        self.on_log(f"NEXUS: {answer}")
                        self.bubble.set_status("falando")
                        self.speak(answer)
            finally:
                browser.close()
        except Exception as exc:
            self.on_log(f"Modo de voz indisponível: {exc}")
        finally:
            self.bubble.stop()
            self.on_log("Modo de voz encerrado.")

    def speak(self, text: str) -> None:
        """Read text aloud using pyttsx3 or an installed system TTS command."""
        clean = " ".join(text.split())
        if not clean:
            return
        with self._tts_lock:
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 165)
                engine.say(clean)
                engine.runAndWait()
                engine.stop()
                return
            except Exception:
                pass

            command = shutil.which("espeak-ng") or shutil.which("espeak")
            if command:
                subprocess.run(
                    [command, "-v", "pt", "-s", "155", clean[:4000]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return

            if shutil.which("say"):
                subprocess.run(["say", clean[:4000]], check=False)
                return

            self.on_log("Resposta exibida, mas nenhum mecanismo de voz foi encontrado.")
