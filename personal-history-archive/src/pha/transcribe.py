"""Local speech recognition (faster-whisper).

The raw output is kept verbatim: no punctuation clean-up, no removal of
fillers or false starts. Low-confidence segments are reported so they can be
queued for review rather than silently "fixed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import TranscriptionConfig
from .media import load_wav


@dataclass
class TranscriptResult:
    text: str
    language: str | None
    model: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    uncertain_segments: list[dict[str, Any]] = field(default_factory=list)


class Transcriber(Protocol):
    def transcribe(self, wav_path: Path) -> TranscriptResult: ...


class FasterWhisperTranscriber:
    def __init__(self, cfg: TranscriptionConfig) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "Transcription needs the 'transcribe' extra: pip install -e '.[transcribe]'"
            ) from exc
        self.cfg = cfg
        self.model = WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type)

    def transcribe(self, wav_path: Path) -> TranscriptResult:
        cfg = self.cfg
        # Pass samples, not a path: faster-whisper's own decoder fails with newer
        # PyAV releases (seen with 19), and the audio is already 16 kHz mono.
        segments_iter, info = self.model.transcribe(
            load_wav(wav_path),
            language=cfg.language or None,
            beam_size=cfg.beam_size,
            temperature=0.0,
            initial_prompt=cfg.initial_prompt or None,
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=cfg.vad_filter,
            vad_parameters={"min_silence_duration_ms": 1000, "speech_pad_ms": 400},
        )
        segments = []
        for seg in segments_iter:
            segments.append(
                {
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text,
                    "avg_logprob": round(seg.avg_logprob, 3),
                    "no_speech_prob": round(seg.no_speech_prob, 3),
                    "compression_ratio": round(seg.compression_ratio, 2),
                    "words": [
                        {"w": w.word, "s": round(w.start, 2), "e": round(w.end, 2), "p": round(w.probability, 3)}
                        for w in (seg.words or [])
                    ],
                }
            )
        return finish_result(cfg, segments, info.language, f"faster-whisper/{cfg.model}")


def finish_result(
    cfg: TranscriptionConfig, segments: list[dict[str, Any]], language: str | None, model: str
) -> TranscriptResult:
    text = " ".join(s["text"].strip() for s in segments if s["text"].strip())
    uncertain = [
        {
            "start": s["start"],
            "end": s["end"],
            "text": s["text"].strip(),
            "why": "low recognition confidence"
            if s["avg_logprob"] < cfg.low_confidence_logprob
            else "may be non-speech or hallucinated",
        }
        for s in segments
        if s["avg_logprob"] < cfg.low_confidence_logprob
        or s["no_speech_prob"] > cfg.high_no_speech_prob
        or s.get("compression_ratio", 0) > 2.4
    ]
    return TranscriptResult(text, language, model, segments, uncertain)


def make_transcriber(cfg: TranscriptionConfig) -> Transcriber:
    if cfg.backend == "faster-whisper":
        return FasterWhisperTranscriber(cfg)
    raise ValueError(f"Unknown transcription backend '{cfg.backend}'")
