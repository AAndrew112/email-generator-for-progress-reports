"""Handwriting recognition with vision-language models.

Backends:
  * ``ollama``    - a vision model served locally by Ollama (default; no data
                    leaves the machine).
  * ``manual``    - no AI; pages are queued for typing in the review UI.
  * ``anthropic`` - cloud. Refused unless ``cloud_ai_authorized = true``.

All backends share one prompt that asks for a verbatim transcription with
explicit markers instead of guesses.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

from ..config import Config

ENTRY_MARKER = "=== ENTRY ==="

PROMPT = f"""This image is one scanned page of a handwritten personal journal, possibly written as a child.
Transcribe it exactly as written.

Rules:
- Copy the original spelling, grammar, capitalisation, punctuation and wording exactly, including mistakes. Never correct, modernise, complete, summarise or explain anything.
- Keep the original line breaks.
- If a word cannot be read, write [illegible]. If several words cannot be read, write [illegible: several words].
- If you are unsure of a word, write your best reading as [?word?].
- Crossed-out text: write [crossed out: text] if readable, otherwise [crossed out].
- Drawings or stickers: write a short note such as [drawing: house].
- Copy dates and times exactly as they appear on the page.
- When a new journal entry starts on this page (usually a new date heading), put a line containing only {ENTRY_MARKER} immediately before it.
- If the page is blank, output only [blank page].

Output only the transcription, with no introduction or commentary."""

_MARKER_RE = re.compile(r"\[(illegible[^\]]*|\?[^\]]*\?|crossed out[^\]]*)\]")


@dataclass
class PageTranscription:
    text: str
    backend: str
    model: str
    # True when the model hit its output/context limit, so the page may be cut off.
    truncated: bool = False


class VisionBackend(Protocol):
    name: str

    def transcribe(self, image_path: Path) -> PageTranscription | None:
        """Return the transcription, or None when a human must transcribe."""


class CloudNotAuthorized(RuntimeError):
    pass


class OllamaBackend:
    name = "ollama"

    def __init__(self, cfg: Config) -> None:
        self.url = cfg.vision.ollama_url.rstrip("/")
        self.model = cfg.vision.ollama_model
        self.timeout = cfg.vision.timeout_seconds
        self.options = {
            "temperature": 0,
            "num_ctx": cfg.vision.ollama_num_ctx,
            "num_predict": cfg.vision.ollama_num_predict,
        }
        host = self.url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if host not in ("127.0.0.1", "localhost", "::1", "[::1]") and not cfg.cloud_ai_authorized:
            raise CloudNotAuthorized(
                f"Ollama URL {self.url} is not on this machine. Sending pages to another host "
                "needs cloud_ai_authorized = true."
            )

    def transcribe(self, image_path: Path) -> PageTranscription:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        resp = requests.post(
            f"{self.url}/api/generate",
            json={
                "model": self.model,
                "prompt": PROMPT,
                "images": [b64],
                "stream": False,
                "options": self.options,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        return PageTranscription(
            strip_wrapping(body.get("response", "")),
            self.name,
            self.model,
            truncated=body.get("done_reason") == "length",
        )


class ManualBackend:
    name = "manual"

    def transcribe(self, image_path: Path) -> None:
        return None


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, cfg: Config) -> None:
        if not cfg.cloud_ai_authorized:
            raise CloudNotAuthorized(
                "The 'anthropic' vision backend sends page images to a cloud service. "
                "Set cloud_ai_authorized = true in config.toml only if you approve that."
            )
        if not cfg.vision.anthropic_model:
            raise ValueError("Set vision.anthropic_model to the Claude model ID you want to use.")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError("Cloud recognition needs the 'cloud' extra: pip install -e '.[cloud]'") from exc
        self.client = anthropic.Anthropic()
        self.model = cfg.vision.anthropic_model

    def transcribe(self, image_path: Path) -> PageTranscription:
        data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Model declined to transcribe {image_path.name}")
        text = "".join(b.text for b in response.content if b.type == "text")
        return PageTranscription(
            strip_wrapping(text), self.name, self.model, truncated=response.stop_reason == "max_tokens"
        )


def make_backend(cfg: Config) -> VisionBackend:
    name = cfg.vision.backend
    if name == "ollama":
        return OllamaBackend(cfg)
    if name == "manual":
        return ManualBackend()
    if name == "anthropic":
        return AnthropicBackend(cfg)
    raise ValueError(f"Unknown vision backend '{name}'")


def strip_wrapping(text: str) -> str:
    """Remove a Markdown code fence some models wrap around their answer."""
    lines = text.strip("\n").splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines)


def uncertainty_markers(text: str) -> list[str]:
    return [m.group(0) for m in _MARKER_RE.finditer(text)]
