"""ffprobe / ffmpeg helpers. Originals are only ever opened for reading."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 16000


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MediaError(f"'{tool}' not found on PATH; install FFmpeg first.")


def probe(path: Path) -> dict[str, Any]:
    """Return ffprobe's format and stream information as a dict."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed for {path}: {proc.stderr.strip()[:500]}")
    return json.loads(proc.stdout or "{}")


def all_tags(info: dict[str, Any]) -> dict[str, str]:
    """Flatten format and stream tags into one dict.

    Format-level tags keep their name; stream tags are prefixed with
    ``stream<N>:`` so nothing is silently merged.
    """
    tags: dict[str, str] = {}
    for k, v in (info.get("format", {}).get("tags") or {}).items():
        tags[k] = str(v)
    for stream in info.get("streams", []):
        idx = stream.get("index")
        for k, v in (stream.get("tags") or {}).items():
            tags[f"stream{idx}:{k}"] = str(v)
    return tags


def duration_seconds(info: dict[str, Any]) -> float | None:
    dur = info.get("format", {}).get("duration")
    try:
        return float(dur) if dur is not None else None
    except ValueError:
        return None


def has_audio(info: dict[str, Any]) -> bool:
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def extract_audio(path: Path, out_wav: Path) -> Path:
    """Decode the audio track to 16 kHz mono WAV in the cache directory."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_suffix(".partial.wav")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "wav",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise MediaError(f"ffmpeg audio extraction failed for {path}: {proc.stderr.strip()[:500]}")
    tmp.replace(out_wav)
    return out_wav


def load_wav(path: Path) -> np.ndarray:
    """Load a 16-bit PCM mono WAV written by :func:`extract_audio` as float32."""
    import wave

    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise MediaError(f"Unexpected WAV format in {path}")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
