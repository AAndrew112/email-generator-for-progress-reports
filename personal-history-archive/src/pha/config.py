"""Configuration loading.

All settings live in a single TOML file (default ``config.toml``). Every
setting has a conservative default so the archive never guesses: unknown
ownership goes to review, unverified dates stay undated, and cloud AI is off.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .marco_polo.filenames import DEFAULT_PATTERN as DEFAULT_FILENAME_PATTERN


@dataclass
class TimestampSourceRule:
    """A metadata field the user has confirmed carries the *recording* time.

    ``kind`` is one of:
      - ``container_tag``: an ffprobe format/stream tag (e.g. ``creation_time``)
      - ``sidecar``: a key inside a sidecar JSON/CSV manifest
      - ``filename``: a field parsed from the file name (``timestamp``)
    """

    kind: str
    name: str
    # Optional strftime format when the value is not ISO-8601.
    format: str | None = None


@dataclass
class OwnershipMetadataRule:
    """A metadata field that identifies the sender of a video.

    The video is mine when the field value (case-insensitive) is in
    ``owner_values``, and someone else's when it holds any other non-empty
    value. Only configure this after ``pha mp inspect`` has shown the field.

    A ``filename`` rule is not trusted on its own: until ``spot_checked`` is
    true (you watched a sample of videos and the names matched who was
    speaking), its answer only counts when voice verification agrees.
    """

    kind: str  # "container_tag", "sidecar" or "filename"
    name: str
    owner_values: list[str] = field(default_factory=list)
    spot_checked: bool = False


@dataclass
class MarcoPoloConfig:
    input_dir: str = ""
    # Regex with named groups (date, time, tz, sender) for metadata in file
    # names. The default matches Marco Polo's chat export naming.
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    video_extensions: list[str] = field(
        default_factory=lambda: [".mp4", ".mov", ".m4v", ".3gp", ".webm", ".mkv"]
    )
    # Metadata rules, filled in after inspecting the real export.
    ownership_rules: list[OwnershipMetadataRule] = field(default_factory=list)
    timestamp_rules: list[TimestampSourceRule] = field(default_factory=list)
    # Container timestamps such as ``creation_time`` are commonly rewritten
    # when a video is saved or exported, so no field is trusted until it is
    # listed in ``timestamp_rules``. Even then, a value lying within this many
    # hours of the file's modification time is treated as an export/download
    # time, not a recording time, and sent to review.
    contamination_window_hours: float = 36.0
    # IANA zone used to *display* UTC-only timestamps; such dates are marked
    # "inferred". Leave empty to keep them in UTC.
    assume_timezone: str = ""
    # Whether to transcribe videos whose ownership is uncertain before review.
    transcribe_uncertain: bool = False
    # PERMANENTLY delete original video files once they are finished with:
    # other people's once excluded, yours once the transcript is approved.
    # Uncertain, failed or unapproved videos are never deleted. Off by default.
    delete_after_processing: bool = False


@dataclass
class VoiceConfig:
    enabled: bool = True
    backend: str = "resemblyzer"
    # Folders of recordings the user has explicitly labelled.
    owner_samples_dir: str = ""
    other_samples_dir: str = ""
    # Similarity thresholds (cosine). Run ``pha mp calibrate`` to tune them.
    accept_threshold: float = 0.80
    reject_threshold: float = 0.65
    # Required margin over the best non-owner profile, when one exists.
    min_margin: float = 0.05
    # Fraction of speech windows that must match the owner to accept.
    min_owner_window_fraction: float = 0.8
    min_enrollment_samples: int = 3


@dataclass
class TranscriptionConfig:
    backend: str = "faster-whisper"
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "default"
    language: str = ""
    beam_size: int = 5
    # Priming text that nudges Whisper to keep fillers ("um", "uh") and
    # false starts rather than silently cleaning them up.
    initial_prompt: str = (
        "Um, so, uh, I was- I was thinking, like, hmm. Okay. Yeah, so, "
        "um, anyway- what was I- oh right."
    )
    vad_filter: bool = True
    # Segments below this average log-probability are queued for review.
    low_confidence_logprob: float = -1.0
    high_no_speech_prob: float = 0.6


@dataclass
class JournalConfig:
    # Google Drive folder name holding the journal archive.
    drive_folder_name: str = "1 journals"
    drive_folder_id: str = ""
    client_secret_file: str = "client_secret.json"
    token_file: str = ""
    # Alternatively process a local folder of PDFs (e.g. Drive for desktop).
    local_pdf_dir: str = ""
    render_dpi: int = 200
    # Order of numeric dates such as 3/4/05: "MDY" or "DMY".
    date_order: str = "MDY"
    # Perceptual-hash Hamming distance at or below which two pages are
    # considered the same scan.
    duplicate_page_distance: int = 6


@dataclass
class VisionConfig:
    # "ollama" (local), "manual" (no AI; transcribe in the review UI) or
    # "anthropic" (cloud; refused unless cloud_ai_authorized is true).
    backend: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5vl:7b"
    # Context window per page. A full-page scan uses thousands of tokens of
    # image data; Ollama's small default makes long pages stop part-way.
    ollama_num_ctx: int = 16384
    ollama_num_predict: int = 8192
    # Required when backend = "anthropic"; set it to the model you choose.
    anthropic_model: str = ""
    timeout_seconds: int = 600


@dataclass
class Config:
    data_dir: str = "archive_data"
    owner_name: str = ""
    # Explicit authorization for sending content to a cloud AI service.
    cloud_ai_authorized: bool = False
    marco_polo: MarcoPoloConfig = field(default_factory=MarcoPoloConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    journals: JournalConfig = field(default_factory=JournalConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    # Directory the config file lives in; relative paths resolve against it.
    base_dir: str = "."

    def path(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else Path(self.base_dir) / p

    @property
    def data_path(self) -> Path:
        return self.path(self.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_path / "archive.sqlite"

    @property
    def cache_path(self) -> Path:
        return self.data_path / "cache"

    @property
    def export_path(self) -> Path:
        return self.data_path / "export"

    @property
    def log_path(self) -> Path:
        return self.data_path / "logs"


def _build(cls: type, raw: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    known = {f.name: f for f in fields(cls)}
    for key, value in raw.items():
        if key not in known:
            raise ValueError(f"Unknown setting '{key}' in [{cls.__name__}]")
        f = known[key]
        default = f.default_factory() if callable(f.default_factory) else f.default  # type: ignore[misc]
        if is_dataclass(default) and isinstance(value, dict):
            value = _build(type(default), value)
        elif key == "ownership_rules":
            value = [OwnershipMetadataRule(**v) for v in value]
        elif key == "timestamp_rules":
            value = [TimestampSourceRule(**v) for v in value]
        kwargs[key] = value
    return cls(**kwargs)


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    path = Path(path).expanduser().resolve()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    cfg = _build(Config, raw)
    cfg.base_dir = str(path.parent)
    return cfg
