"""NEXUS Image Generator — generates images via ChatGPT and downloads them.

Sends a prompt to https://chatgpt.com/images, waits for image generation,
extracts the generated image link(s), downloads the image(s), and reports
their local location.
"""

from __future__ import annotations

import base64
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

IMAGE_CHATGPT_URL = "https://chatgpt.com/images"

IMAGE_DOWNLOAD_DIR = Path.home() / "Imagens-NEXUS"


class ImageGenerationError(Exception):
    """Raised when image generation or download fails."""


class ImageGenerator:
    """Generates images by sending prompts to ChatGPT /images via browser.

    Flow:
    1. Open https://chatgpt.com/images in a browser
    2. Submit the user's image prompt
    3. Poll the page for new image elements / links (generated images)
    4. Extract the image URL from <img src>, <a href>, or download buttons
    5. Download each image to ~/Imagens-NEXUS/
    6. Return the list of downloaded file paths
    """

    # URL patterns that indicate a generated image (DALL-E / ChatGPT output)
    GENERATED_PATTERNS = [
        "oaiusercontent", "files.oai", "user-content",
        "imagegen", "dalle", "generated",
        "prod-files", "oaiusercontent.com",
    ]

    # Patterns that indicate a UI element (icon, avatar, logo)
    UI_PATTERNS = [
        "avatar", "logo", "icon", "favicon", "emoji",
        "static", "assets", "sprite", "ui-",
    ]

    def __init__(self, browser: Any) -> None:
        self.browser = browser

    def generate(self, prompt: str, timeout: int = 180) -> list[dict[str, str]]:
        """Generate one or more images from a prompt.

        Args:
            prompt: The image generation prompt (e.g. "um sorvete colorido")
            timeout: Maximum seconds to wait for image generation

        Returns:
            List of dicts with keys: path, filename, size_bytes, url
        """
        page = self.browser.page
        if page is None:
            raise ImageGenerationError("Página do navegador não disponível.")

        self._print("ENVIANDO", f"Navegando para {IMAGE_CHATGPT_URL} ...")
        try:
            page.goto(IMAGE_CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            raise ImageGenerationError(f"Falha ao abrir URL de imagens: {exc}") from exc

        time.sleep(3)
        self._print("ENVIANDO", f"Prompt: {prompt[:80]}")

        # Snapshot existing image URLs before sending the prompt
        existing_srcs = self._get_image_srcs()
        self._print("AGUARDANDO", f"Imagens existentes na página: {len(existing_srcs)}")

        self._submit_prompt(prompt)

        self._print("AGUARDANDO", "Aguardando geração da imagem...")
        new_srcs = self._wait_for_new_images(existing_srcs, timeout=timeout)

        if not new_srcs:
            raise ImageGenerationError(
                "Nenhuma imagem foi gerada dentro do tempo limite. "
                "Verifique se a página /images está carregada e se o ChatGPT pode gerar imagens."
            )

        self._print("GERADA", f"{len(new_srcs)} imagem(ns) detectada(s).")

        IMAGE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        results: list[dict[str, str]] = []

        for i, src in enumerate(new_srcs):
            self._print("BAIXANDO", f"Imagem {i + 1}/{len(new_srcs)}: {src[:80]}...")
            try:
                downloaded = self._download_image(src, timestamp, i + 1)
                if downloaded:
                    results.append(downloaded)
                    self._print("CONCLUIDO", f"Salvo: {downloaded['path']}")
            except Exception as exc:
                self._print("ERRO", f"Falha ao baixar imagem {i + 1}: {exc}")

        if not results:
            raise ImageGenerationError("As imagens foram geradas mas não foi possível baixá-las.")

        return results

    # ------------------------------------------------------------------
    # Submit prompt
    # ------------------------------------------------------------------

    def _submit_prompt(self, prompt: str) -> None:
        """Type and submit the prompt into the ChatGPT /images input box."""
        page = self.browser.page

        input_selectors = [
            '#prompt-textarea',
            'div[contenteditable="true"]',
            "textarea",
            'div[role="textbox"]',
            'div[contenteditable="plaintext-only"]',
        ]

        input_box = None
        for selector in input_selectors:
            try:
                loc = page.locator(selector).last
                if loc.is_visible(timeout=5000):
                    input_box = loc
                    break
            except Exception:
                continue

        if input_box is None:
            raise ImageGenerationError(
                "Não foi possível encontrar a caixa de texto do ChatGPT /images. "
                "A página pode não estar carregada corretamente."
            )

        try:
            input_box.click()
        except Exception:
            pass

        try:
            input_box.fill("")
        except Exception:
            pass

        try:
            input_box.press("ControlOrMeta+A")
            input_box.press("Backspace")
        except Exception:
            pass

        try:
            input_box.type(prompt, delay=2)
        except Exception as exc:
            raise ImageGenerationError(f"Não foi possível digitar o prompt: {exc}") from exc

        time.sleep(0.5)

        # Press Enter to submit
        try:
            input_box.press("Enter")
            self._print("ENVIADO", "Prompt enviado ao ChatGPT /images.")
            return
        except Exception:
            pass

        # Fallback: find a send button
        buttons = page.locator("button")
        count = buttons.count()
        for idx in range(count):
            btn = buttons.nth(idx)
            try:
                if not btn.is_visible():
                    continue
                aria = btn.get_attribute("aria-label") or ""
                text = btn.inner_text()
            except Exception:
                continue
            if re.search(r"send|enviar|submit|criar|gerar|create", aria + " " + text, re.I):
                btn.click()
                self._print("ENVIADO", "Prompt enviado via botão.")
                return

        raise ImageGenerationError("Não foi possível enviar o prompt — Enter e botão falharam.")

    # ------------------------------------------------------------------
    # Image detection — extract URLs from <img src>, <a href>, download buttons
    # ------------------------------------------------------------------

    def _get_image_srcs(self) -> list[str]:
        """Collect all generated-image URLs currently visible on the page.

        Looks at:
        - <img> src / data-src attributes
        - <a> href attributes pointing to image URLs
        - download buttons with data-url or href
        """
        page = self.browser.page
        srcs: list[str] = []
        seen: set[str] = set()

        # 1) <img> elements
        try:
            img_elements = page.locator("img")
            count = img_elements.count()
            for i in range(count):
                try:
                    img = img_elements.nth(i)
                    src = img.get_attribute("src") or ""
                    if not src:
                        src = img.get_attribute("data-src") or ""
                    if not src:
                        continue
                    if self._is_ui_image(src, img):
                        continue
                    if src not in seen:
                        seen.add(src)
                        srcs.append(src)
                except Exception:
                    continue
        except Exception:
            pass

        # 2) <a> elements with href pointing to generated images
        try:
            anchors = page.locator("a[href]")
            acount = anchors.count()
            for i in range(acount):
                try:
                    a = anchors.nth(i)
                    href = a.get_attribute("href") or ""
                    if not href or not self._looks_like_generated_url(href):
                        continue
                    # Normalize — might be relative
                    if href.startswith("/"):
                        href = "https://chatgpt.com" + href
                    if href not in seen:
                        seen.add(href)
                        srcs.append(href)
                except Exception:
                    continue
        except Exception:
            pass

        # 3) Elements with data-url or data-image-url pointing to images
        try:
            data_elements = page.locator("[data-url], [data-image-url], [data-download-url]")
            dcount = data_elements.count()
            for i in range(dcount):
                try:
                    el = data_elements.nth(i)
                    for attr in ("data-url", "data-image-url", "data-download-url"):
                        url = el.get_attribute(attr) or ""
                        if url and self._looks_like_generated_url(url):
                            if url.startswith("/"):
                                url = "https://chatgpt.com" + url
                            if url not in seen:
                                seen.add(url)
                                srcs.append(url)
                except Exception:
                    continue
        except Exception:
            pass

        return srcs

    @classmethod
    def _looks_like_generated_url(cls, url: str) -> bool:
        """Check if a URL looks like a generated-image URL."""
        url_lower = url.lower()
        return any(p in url_lower for p in cls.GENERATED_PATTERNS)

    @classmethod
    def _is_ui_image(cls, src: str, img_element: Any) -> bool:
        """Check if an image is a UI element (icon, avatar, logo) not generated content."""
        src_lower = src.lower()

        if src_lower.startswith("data:image/svg"):
            return True

        if any(p in src_lower for p in cls.UI_PATTERNS):
            return True

        # Check dimensions — generated images are typically > 200px
        try:
            width = img_element.evaluate("el => el.naturalWidth || el.width || 0")
            height = img_element.evaluate("el => el.naturalHeight || el.height || 0")
            if width < 200 or height < 200:
                return True
        except Exception:
            pass

        # Generated images match known URL patterns
        if cls._looks_like_generated_url(src):
            return False

        return False

    # ------------------------------------------------------------------
    # Wait for new images to appear
    # ------------------------------------------------------------------

    def _wait_for_new_images(
        self, existing_srcs: list[str], timeout: int = 180
    ) -> list[str]:
        """Poll the page until new image URLs appear after submitting the prompt."""
        existing_set = set(existing_srcs)
        deadline = time.monotonic() + timeout
        poll_interval = 3
        elapsed = 0

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            elapsed += poll_interval

            current_srcs = self._get_image_srcs()
            new_srcs = [s for s in current_srcs if s not in existing_set]

            if new_srcs:
                # Wait a bit more for all images to fully render
                time.sleep(4)
                final_srcs = self._get_image_srcs()
                new_srcs = [s for s in final_srcs if s not in existing_set]
                if new_srcs:
                    return new_srcs

            remaining = int(deadline - time.monotonic())
            if elapsed % 15 == 0:
                self._print("AGUARDANDO", f"Ainda aguardando... {remaining}s restantes")

        return []

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _download_image(self, src: str, timestamp: str, index: int) -> Optional[dict[str, str]]:
        """Download an image from a URL or data URI to the local filesystem.

        Tries multiple methods:
        1. Data URI → decode directly
        2. Browser fetch (via page.evaluate) — carries auth cookies
        3. urllib fallback
        4. Screenshot of the <img> element as last resort
        """
        if not src:
            return None

        ext = self._detect_extension(src)
        filename = f"imagem_{timestamp}_{index}{ext}"
        filepath = IMAGE_DOWNLOAD_DIR / filename

        # Method 1: data URI
        if src.startswith("data:image"):
            return self._download_data_uri(src, filepath, filename)

        # Method 2: browser fetch (carries cookies/auth)
        result = self._download_via_browser(src, filepath, filename)
        if result:
            return result

        # Method 3: urllib fallback
        result = self._download_via_urllib(src, filepath, filename)
        if result:
            return result

        # Method 4: screenshot the <img> element directly
        result = self._download_via_screenshot(src, filepath, filename)
        if result:
            return result

        return None

    @staticmethod
    def _detect_extension(src: str) -> str:
        src_lower = src.lower()
        if ".jpg" in src_lower or ".jpeg" in src_lower:
            return ".jpg"
        if ".webp" in src_lower:
            return ".webp"
        if ".gif" in src_lower:
            return ".gif"
        return ".png"

    @staticmethod
    def _download_data_uri(src: str, filepath: Path, filename: str) -> Optional[dict[str, str]]:
        try:
            header, data = src.split(",", 1)
            if "base64" in header.lower():
                binary = base64.b64decode(data)
            else:
                binary = urllib.parse.unquote_to_bytes(data)
            filepath.write_bytes(binary)
            return {
                "path": str(filepath),
                "filename": filename,
                "size_bytes": str(filepath.stat().st_size),
                "url": "data-uri",
            }
        except Exception:
            return None

    def _download_via_browser(self, src: str, filepath: Path, filename: str) -> Optional[dict[str, str]]:
        """Fetch the image through the browser's page context (carries auth cookies)."""
        page = self.browser.page
        try:
            result = page.evaluate(
                """async (url) => {
                    try {
                        const resp = await fetch(url, {credentials: 'include'});
                        if (!resp.ok) return null;
                        const blob = await resp.blob();
                        return new Promise((resolve) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result);
                            reader.onerror = () => resolve(null);
                            reader.readAsDataURL(blob);
                        });
                    } catch(e) { return null; }
                }""",
                src,
            )
            if result and isinstance(result, str) and result.startswith("data:"):
                header, data = result.split(",", 1)
                if "base64" in header.lower():
                    binary = base64.b64decode(data)
                    filepath.write_bytes(binary)
                    return {
                        "path": str(filepath),
                        "filename": filename,
                        "size_bytes": str(filepath.stat().st_size),
                        "url": src[:200],
                    }
        except Exception:
            pass
        return None

    @staticmethod
    def _download_via_urllib(src: str, filepath: Path, filename: str) -> Optional[dict[str, str]]:
        try:
            req = urllib.request.Request(
                src,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NEXUS/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                binary = response.read()
                filepath.write_bytes(binary)
            return {
                "path": str(filepath),
                "filename": filename,
                "size_bytes": str(filepath.stat().st_size),
                "url": src[:200],
            }
        except Exception:
            return None

    def _download_via_screenshot(self, src: str, filepath: Path, filename: str) -> Optional[dict[str, str]]:
        """Last resort: find the <img> element on the page and screenshot it."""
        page = self.browser.page
        try:
            img_loc = page.locator(f'img[src="{src}"]').first
            if not img_loc.is_visible(timeout=3000):
                return None
            filepath_str = str(filepath).replace(".png", "_screenshot.png")
            filepath = Path(filepath_str)
            img_loc.screenshot(path=str(filepath))
            if filepath.exists() and filepath.stat().st_size > 0:
                return {
                    "path": str(filepath),
                    "filename": filepath.name,
                    "size_bytes": str(filepath.stat().st_size),
                    "url": src[:200],
                }
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    @staticmethod
    def _print(phase: str, message: str) -> None:
        colors = {
            "ENVIANDO": "\033[1;34m",
            "ENVIADO": "\033[1;34m",
            "AGUARDANDO": "\033[1;33m",
            "GERADA": "\033[1;32m",
            "BAIXANDO": "\033[1;36m",
            "ERRO": "\033[1;31m",
            "CONCLUIDO": "\033[1;32m",
        }
        color = colors.get(phase, "\033[0m")
        reset = "\033[0m"
        print(f"{color}[IMAGEM:{phase}] {message}{reset}", flush=True)
