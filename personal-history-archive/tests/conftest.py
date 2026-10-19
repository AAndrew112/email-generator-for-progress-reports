"""Synthetic fixtures. These test the pipeline logic, not recognition quality:
videos are tones with chosen metadata, and the "voices" are tone frequencies.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from pha.config import Config
from pha.db import Database
from pha.journals.vision import PageTranscription
from pha.transcribe import TranscriptResult

OWNER_HZ = 220
OTHER_HZ = 660


def make_video(
    path: Path,
    seconds: float = 4,
    tags: dict[str, str] | None = None,
    freqs: tuple[int, ...] = (OWNER_HZ,),
    audio: bool = True,
    mtime: datetime | None = None,
) -> Path:
    """A tiny MP4. Several ``freqs`` are played one after another (a 'conversation')."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=blue:s=64x64:d={seconds}"]
    if audio:
        part = seconds / len(freqs)
        expr = "+".join(
            f"sin(2*PI*{f}*t)*between(t,{i * part},{(i + 1) * part})" for i, f in enumerate(freqs)
        )
        cmd += ["-f", "lavfi", "-i", f"aevalsrc=exprs='0.5*({expr})':s=16000:d={seconds}"]
    cmd += ["-c:v", "mpeg4"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += ["-movflags", "use_metadata_tags"]
    for k, v in (tags or {}).items():
        cmd += ["-metadata", f"{k}={v}"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    if mtime:
        ts = mtime.timestamp()
        os.utime(path, (ts, ts))
    return path


def make_speech_video(path: Path, parts: list[tuple[str, str]], mtime: datetime | None = None) -> Path:
    """An MP4 whose audio is synthetic speech (ffmpeg's flite voices: slt, rms, awb, kal16).

    ``parts`` is a list of (voice, text) spoken one after another.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    for voice, text in parts:
        safe = text.replace("'", "").replace(":", " ").replace(",", " ")
        cmd += ["-f", "lavfi", "-i", f"flite=text='{safe}':voice={voice}"]
    n = len(parts)
    chain = "".join(f"[{i}:a]aresample=16000[a{i}];" for i in range(n))
    chain += "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    cmd += ["-f", "lavfi", "-i", "color=c=green:s=64x64:r=10",
            "-filter_complex", chain, "-map", f"{n}:v", "-map", "[aout]",
            "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    if mtime:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    return path


class FakeTranscriber:
    """Returns the dominant tone as 'speech', with fillers kept verbatim."""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.fail_on: set[str] = set()
        self.interrupt_on: set[str] = set()

    def transcribe(self, wav_path: Path) -> TranscriptResult:
        self.calls.append(wav_path)
        if wav_path.stem[:6] in self.fail_on:
            raise RuntimeError("decoder exploded")
        if wav_path.stem[:6] in self.interrupt_on:
            raise KeyboardInterrupt
        segments = [
            {"start": 0.0, "end": 1.5, "text": " Um, so I- I was thinking", "avg_logprob": -0.2,
             "no_speech_prob": 0.01, "compression_ratio": 1.1, "words": []},
            {"start": 1.5, "end": 3.0, "text": " uh, mumble mumble", "avg_logprob": -1.4,
             "no_speech_prob": 0.05, "compression_ratio": 1.0, "words": []},
        ]
        from pha.config import TranscriptionConfig
        from pha.transcribe import finish_result

        return finish_result(TranscriptionConfig(), segments, "en", "fake-whisper")


def _peak_hz(chunk: np.ndarray) -> float:
    spec = np.abs(np.fft.rfft(chunk))
    return float(np.argmax(spec) * 16000 / len(chunk))


class FakeEmbedder:
    """Maps the dominant frequency of each 1 s window to a 'voice' vector."""

    def _vec(self, hz: float) -> np.ndarray:
        v = np.zeros(8)
        v[0 if abs(hz - OWNER_HZ) < 60 else 1 if abs(hz - OTHER_HZ) < 60 else 2] = 1.0
        v[3:] = 0.05
        return v

    def embed(self, wav: np.ndarray):
        win = 16000
        windows = [self._vec(_peak_hz(wav[i:i + win])) for i in range(0, len(wav) - win + 1, win)
                   if np.abs(wav[i:i + win]).mean() > 0.01]
        if not windows:
            return np.zeros(8), [], 0.0
        return np.mean(windows, axis=0), windows, float(len(windows))


class FakeVision:
    """Returns scripted text per page, keyed by '<source_id>/p0001'."""

    name = "fake-vision"

    def __init__(self, script: dict[str, str]) -> None:
        self.script = script
        self.calls: list[Path] = []

    def transcribe(self, image_path: Path) -> PageTranscription:
        self.calls.append(image_path)
        key = f"{image_path.parent.name}/{image_path.stem}"
        text = self.script.get(key) or self.script.get(image_path.stem, "")
        return PageTranscription(text, "fake-vision", "test")


def make_pdf(path: Path, pages: list[str], scale: float = 1.0) -> Path:
    """A PDF whose pages carry visibly different drawn text (for hashing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for i, text in enumerate(pages):
        w, h = int(850 * scale), int(1100 * scale)
        im = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(im)
        for row, line in enumerate(text.splitlines()):
            d.text((int(60 * scale), int((80 + row * 40) * scale)), line, fill="black")
        # A distinct blob per page so pages do not hash alike.
        d.rectangle([int((100 + 90 * i) * scale), int(700 * scale), int((300 + 90 * i) * scale),
                     int(900 * scale)], fill="black")
        images.append(im)
    images[0].save(path, save_all=True, append_images=images[1:], format="PDF", resolution=100)
    return path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config()
    c.base_dir = str(tmp_path)
    c.data_dir = "data"
    c.marco_polo.input_dir = "exports"
    c.voice.enabled = False
    c.journals.local_pdf_dir = "journals"
    c.journals.render_dpi = 50
    return c


@pytest.fixture
def db(cfg: Config) -> Database:
    d = Database(cfg.db_path)
    yield d
    d.close()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


OLD = datetime(2026, 9, 1, tzinfo=timezone.utc)
