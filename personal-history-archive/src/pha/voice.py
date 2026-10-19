"""Local voice verification against recordings the user labelled as theirs.

The question asked is "does the speech in this video match *my* enrolled
voice?", not "who is loudest?". Every speech window is compared with the
owner profile, so a video that mixes voices is detected and sent to review
instead of being attributed to whoever dominates the audio.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .config import VoiceConfig
from .media import extract_audio, load_wav
from .runtime import sha256_file

log = logging.getLogger("pha.voice")

AUDIO_EXTENSIONS = {".wav", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".opus"}
MIN_SPEECH_SECONDS = 2.0


class Embedder(Protocol):
    def embed(self, wav: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], float]:
        """Return (utterance embedding, per-window embeddings, seconds of speech)."""


class ResemblyzerEmbedder:
    """GE2E speaker encoder; pretrained weights ship inside the pip package."""

    def __init__(self) -> None:
        try:
            from resemblyzer import VoiceEncoder, preprocess_wav
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Voice verification needs the 'voice' extra: pip install -e '.[voice]'"
            ) from exc
        self._preprocess = preprocess_wav
        self._encoder = VoiceEncoder(device="cpu", verbose=False)

    def embed(self, wav: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], float]:
        speech = self._preprocess(wav, source_sr=16000)  # trims silence (VAD)
        seconds = len(speech) / 16000
        if seconds < MIN_SPEECH_SECONDS:
            return np.zeros(256), [], seconds
        # One 1.6 s partial embedding per second of speech.
        utt, partials, _ = self._encoder.embed_utterance(speech, return_partials=True, rate=1.0)
        return utt, list(partials), seconds


def make_embedder(cfg: VoiceConfig) -> Embedder:
    if cfg.backend == "resemblyzer":
        return ResemblyzerEmbedder()
    raise ValueError(f"Unknown voice backend '{cfg.backend}'")


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(_unit(a), _unit(b)))


@dataclass
class VoiceProfiles:
    owner: np.ndarray | None
    owner_count: int
    others: dict[str, np.ndarray] = field(default_factory=dict)
    sample_embeddings: dict[str, list[tuple[str, np.ndarray]]] = field(default_factory=dict)


def _sample_files(folder: Path) -> list[Path]:
    from .config import MarcoPoloConfig

    exts = AUDIO_EXTENSIONS | set(MarcoPoloConfig().video_extensions)
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def embed_file(path: Path, embedder: Embedder, cache_dir: Path) -> tuple[np.ndarray, list[np.ndarray], float]:
    digest = sha256_file(path)
    wav_path = cache_dir / "audio" / f"{digest[:24]}.wav"
    if not wav_path.exists():
        extract_audio(path, wav_path)
    return embedder.embed(load_wav(wav_path))


def build_profiles(cfg: VoiceConfig, base: Path, cache_dir: Path, embedder: Embedder) -> VoiceProfiles:
    """Embed the labelled samples. Cached by file hash in ``voice_profiles.npz``."""
    cache_file = cache_dir / "voice_profiles.npz"
    index_file = cache_dir / "voice_profiles.json"
    owner_dir = (base / cfg.owner_samples_dir) if cfg.owner_samples_dir else None
    other_dir = (base / cfg.other_samples_dir) if cfg.other_samples_dir else None

    groups: dict[str, list[Path]] = {}
    if owner_dir and owner_dir.exists():
        groups["__owner__"] = _sample_files(owner_dir)
    if other_dir and other_dir.exists():
        for p in _sample_files(other_dir):
            rel = p.relative_to(other_dir)
            label = rel.parts[0] if len(rel.parts) > 1 else "others"
            groups.setdefault(label, []).append(p)

    signature = {
        label: [f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in paths]
        for label, paths in groups.items()
    }
    cached: dict[str, np.ndarray] = {}
    if cache_file.exists() and index_file.exists():
        if json.loads(index_file.read_text()) == {"signature": signature}:
            with np.load(cache_file) as data:
                cached = {k: data[k] for k in data.files}

    sample_embeddings: dict[str, list[tuple[str, np.ndarray]]] = {}
    arrays: dict[str, np.ndarray] = {}
    for label, paths in groups.items():
        for i, p in enumerate(paths):
            key = f"{label}|{i}"
            if key in cached:
                emb = cached[key]
            else:
                utt, _, seconds = embed_file(p, embedder, cache_dir)
                if seconds < MIN_SPEECH_SECONDS:
                    log.warning("Voice sample %s has only %.1fs of speech; skipped", p, seconds)
                    continue
                emb = utt
            arrays[key] = emb
            sample_embeddings.setdefault(label, []).append((str(p), emb))

    cache_dir.mkdir(parents=True, exist_ok=True)
    if arrays:
        np.savez(cache_file, **arrays)
    index_file.write_text(json.dumps({"signature": signature}))

    owner_embs = [e for _, e in sample_embeddings.get("__owner__", [])]
    owner = _unit(np.mean(owner_embs, axis=0)) if owner_embs else None
    others = {
        label: _unit(np.mean([e for _, e in embs], axis=0))
        for label, embs in sample_embeddings.items()
        if label != "__owner__" and embs
    }
    return VoiceProfiles(owner, len(owner_embs), others, sample_embeddings)


@dataclass
class VoiceDecision:
    decision: str  # owner | other | uncertain
    reason: str
    details: dict[str, Any]


def score(
    cfg: VoiceConfig,
    profiles: VoiceProfiles,
    utterance: np.ndarray,
    windows: list[np.ndarray],
    speech_seconds: float,
) -> VoiceDecision:
    if profiles.owner is None or profiles.owner_count < cfg.min_enrollment_samples:
        return VoiceDecision(
            "uncertain",
            f"voice profile needs at least {cfg.min_enrollment_samples} labelled samples "
            f"(have {profiles.owner_count})",
            {},
        )
    if speech_seconds < MIN_SPEECH_SECONDS or not windows:
        return VoiceDecision(
            "uncertain", f"too little speech to verify ({speech_seconds:.1f}s)", {"speech_seconds": speech_seconds}
        )

    sim = cosine(utterance, profiles.owner)
    window_sims = [cosine(w, profiles.owner) for w in windows]
    owner_windows = sum(s >= cfg.accept_threshold for s in window_sims)
    other_windows = sum(s <= cfg.reject_threshold for s in window_sims)
    frac_owner = owner_windows / len(window_sims)
    frac_other = other_windows / len(window_sims)
    best_other_label, best_other = None, None
    for label, prof in profiles.others.items():
        s = cosine(utterance, prof)
        if best_other is None or s > best_other:
            best_other_label, best_other = label, s

    details = {
        "similarity": round(sim, 4),
        "owner_window_fraction": round(frac_owner, 3),
        "non_owner_window_fraction": round(frac_other, 3),
        "windows": len(window_sims),
        "speech_seconds": round(speech_seconds, 1),
        "best_other_profile": best_other_label,
        "best_other_similarity": round(best_other, 4) if best_other is not None else None,
        "thresholds": {"accept": cfg.accept_threshold, "reject": cfg.reject_threshold},
    }

    # Both the owner and someone clearly different speak in this video.
    if frac_owner >= 0.2 and frac_other >= 0.2:
        return VoiceDecision("uncertain", "multiple speakers detected", details)
    margin_ok = best_other is None or sim - best_other >= cfg.min_margin
    if sim >= cfg.accept_threshold and frac_owner >= cfg.min_owner_window_fraction and margin_ok:
        return VoiceDecision("owner", "voice matches enrolled owner profile", details)
    if sim <= cfg.reject_threshold and frac_owner < 0.2:
        return VoiceDecision("other", "voice does not match owner profile", details)
    if not margin_ok:
        return VoiceDecision("uncertain", "voice is close to a non-owner profile", details)
    return VoiceDecision("uncertain", "voice similarity between thresholds", details)


def calibrate(profiles: VoiceProfiles) -> dict[str, Any]:
    """Leave-one-out check of the labelled samples, to set thresholds honestly."""
    owner = profiles.sample_embeddings.get("__owner__", [])
    others = [
        (label, path, emb)
        for label, embs in profiles.sample_embeddings.items()
        if label != "__owner__"
        for path, emb in embs
    ]
    if len(owner) < 2:
        return {"error": "need at least 2 owner samples (3+ recommended)"}

    owner_scores = []
    for i, (path, emb) in enumerate(owner):
        rest = [e for j, (_, e) in enumerate(owner) if j != i]
        owner_scores.append({"path": path, "similarity": round(cosine(emb, np.mean(rest, axis=0)), 4)})
    centroid = np.mean([e for _, e in owner], axis=0)
    other_scores = [
        {"label": label, "path": path, "similarity": round(cosine(emb, centroid), 4)}
        for label, path, emb in others
    ]
    o_min = min(s["similarity"] for s in owner_scores)
    result: dict[str, Any] = {
        "owner_samples": len(owner),
        "other_samples": len(others),
        "owner_leave_one_out": owner_scores,
        "other_vs_owner": other_scores,
        "owner_min": o_min,
    }
    if other_scores:
        x_max = max(s["similarity"] for s in other_scores)
        result["other_max"] = x_max
        result["separable"] = o_min > x_max
        if o_min > x_max:
            gap = o_min - x_max
            result["suggested_accept_threshold"] = round(o_min - gap * 0.25, 3)
            result["suggested_reject_threshold"] = round(x_max + gap * 0.25, 3)
        else:
            result["warning"] = (
                "Owner and non-owner samples overlap; voice verification is not "
                "reliable with these samples. Add cleaner samples or rely on review."
            )
    else:
        result["warning"] = (
            "No non-owner samples labelled; thresholds cannot be validated. "
            "Label a few other participants' videos in other_samples_dir."
        )
    return result
