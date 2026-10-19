"""Marco Polo video pipeline.

Per video: hash -> metadata -> ownership -> (mine only) timestamp + transcript.
Each source row is a checkpoint, so an interrupted run resumes where it
stopped, completed videos are never re-transcribed, and the same file seen
again (duplicate copy or repeat import) is recognised by its content hash.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..db import Database
from ..media import all_tags, duration_seconds, extract_audio, has_audio, load_wav, probe, require_ffmpeg
from ..runtime import Progress
from ..transcribe import Transcriber, make_transcriber
from ..voice import Embedder, VoiceDecision, VoiceProfiles, build_profiles, make_embedder, score
from . import timestamps
from .sidecar import SidecarIndex, sidecar_values

log = logging.getLogger("pha.mp")

SOURCE_TYPE = "marco_polo"
MAX_ATTEMPTS = 3
_SKIP_SUFFIXES = (".part", ".crdownload", ".download", ".tmp")


def discover(input_dir: Path, extensions: list[str]) -> list[Path]:
    exts = {e.lower() for e in extensions}
    found = []
    for p in input_dir.rglob("*"):
        if not p.is_file() or p.name.startswith((".", "._")):
            continue
        if p.name.lower().endswith(_SKIP_SUFFIXES):
            continue
        if p.suffix.lower() in exts:
            found.append(p)
    return sorted(found)


def filename_hints(path: Path, root: Path) -> dict[str, Any]:
    """Recorded as context only. Filenames never decide ownership."""
    rel = path.relative_to(root)
    return {"folders": list(rel.parts[:-1]), "stem": path.stem}


class MarcoPoloPipeline:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        transcriber_factory: Callable[[], Transcriber] | None = None,
        embedder_factory: Callable[[], Embedder] | None = None,
    ) -> None:
        self.cfg = cfg
        self.mp = cfg.marco_polo
        self.db = db
        self._transcriber_factory = transcriber_factory or (lambda: make_transcriber(cfg.transcription))
        self._embedder_factory = embedder_factory or (lambda: make_embedder(cfg.voice))
        self._transcriber: Transcriber | None = None
        self._embedder: Embedder | None = None
        self._profiles: VoiceProfiles | None = None
        self.root = cfg.path(self.mp.input_dir)
        self.audio_cache = cfg.cache_path / "audio"

    # ------------------------------------------------------------ lazy models
    @property
    def transcriber(self) -> Transcriber:
        if self._transcriber is None:
            log.info("Loading speech recognition model (%s)...", self.cfg.transcription.model)
            self._transcriber = self._transcriber_factory()
        return self._transcriber

    def profiles(self) -> VoiceProfiles | None:
        if not self.cfg.voice.enabled or not self.cfg.voice.owner_samples_dir:
            return None
        if self._profiles is None:
            self._embedder = self._embedder_factory()
            self._profiles = build_profiles(
                self.cfg.voice, Path(self.cfg.base_dir), self.cfg.cache_path, self._embedder
            )
            log.info(
                "Voice profile: %d owner samples, %d other profiles",
                self._profiles.owner_count,
                len(self._profiles.others),
            )
        return self._profiles

    # ------------------------------------------------------------------- run
    def run(
        self,
        retry_failed: bool = False,
        reclassify: bool = False,
        force_retranscribe: bool = False,
        limit: int | None = None,
    ) -> Progress:
        require_ffmpeg()
        if not self.mp.input_dir or not self.root.exists():
            raise RuntimeError(f"Marco Polo input folder not found: {self.root}")
        files = discover(self.root, self.mp.video_extensions)
        if limit:
            files = files[:limit]
        log.info("Found %d video files under %s", len(files), self.root)
        self.sidecars = SidecarIndex(self.root, self.mp.video_extensions)
        progress = Progress(len(files), "marco_polo")
        seen: dict[str, Path] = {}

        for path in files:
            try:
                sha = self.db.cached_sha256(path)
                source_id = f"mp-{sha[:16]}"
                self.db.upsert_source(
                    source_id, SOURCE_TYPE, path.name, str(path.resolve()), sha, path.stat().st_size
                )
                if source_id in seen:
                    progress.step(path.name, f"duplicate of {seen[source_id].name}")
                    continue
                seen[source_id] = path
                outcome = self._process(source_id, path, retry_failed, reclassify, force_retranscribe)
            except Exception as exc:  # log and keep going
                log.exception("Failed on %s", path)
                self.db.log_failure(None, "discover", f"{path}: {exc}")
                outcome = "failed"
            progress.step(path.name, outcome)

        self._flag_near_duplicates()
        log.info(progress.summary())
        return progress

    def _process(
        self, source_id: str, path: Path, retry_failed: bool, reclassify: bool, force: bool
    ) -> str:
        src = self.db.get_source(source_id)
        assert src is not None
        status = src["status"]
        manual = _is_manual(src)

        if status == "failed" and src["attempts"] >= MAX_ATTEMPTS and not retry_failed:
            return f"skipped (failed {src['attempts']}x; use --retry-failed)"
        if status == "excluded" and not (reclassify and not manual):
            return "excluded (not my video)"
        if status == "done" and not (reclassify or force):
            self._refresh_timestamp(source_id, path)
            return "already done"

        self.db.update_source(source_id, status="in_progress", attempts=src["attempts"] + 1)
        stage = "metadata"
        try:
            info = probe(path)
            tags = all_tags(info)
            sidecar = self.sidecars.lookup(path)
            meta = {
                "container_tags": tags,
                "sidecar": sidecar,
                "duration": duration_seconds(info),
                "has_audio": has_audio(info),
                "file_mtime_utc": _mtime(path).isoformat(),
                "filename_hints": filename_hints(path, self.root),
            }
            self.db.update_source(source_id, metadata_json=meta, stage=stage)

            stage = "ownership"
            src = self.db.get_source(source_id)
            if manual or (src["ownership"] in ("owner", "other") and not reclassify):
                decision = src["ownership"]
                detail = json.loads(src["ownership_detail"] or "{}")
            else:
                decision, detail = self._classify(source_id, path, tags, sidecar, meta)
                self.db.update_source(source_id, ownership=decision, ownership_detail=detail)

            if decision in ("owner", "other"):
                for item in self.db.review_items(status="open", kind="speaker"):
                    if item["source_id"] == source_id:
                        self.db.resolve_review(item["id"], f"resolved: {detail.get('reason')}")
            if decision == "other":
                self.db.delete_machine_records(source_id, keep=set())
                self.db.update_source(source_id, status="excluded", stage=stage, last_error=None)
                return "excluded (not my video)"
            if decision == "uncertain":
                self.db.add_review(
                    "speaker", detail.get("reason", "ownership uncertain"), source_id=source_id,
                    details=detail,
                )
                if not self.mp.transcribe_uncertain:
                    self.db.update_source(source_id, status="needs_review", stage=stage, last_error=None)
                    return f"needs review ({detail.get('reason')})"

            stage = "timestamp"
            record_id = f"mp-{src['sha256'][:16]}"
            ts = self._timestamp(path, tags, sidecar)
            self.db.upsert_machine_record(
                record_id,
                source_id=source_id,
                source_type=SOURCE_TYPE,
                machine_date=ts.date,
                machine_time=ts.time,
                machine_timezone=ts.timezone,
                machine_confidence=ts.confidence,
                timestamp_utc=ts.utc,
                timestamp_evidence=ts.evidence,
                source_filename=path.name,
                source_location=str(path.resolve()),
                duration=meta["duration"],
                speaker_verification=_speaker_label(decision, detail),
            )
            self._queue_date_review(record_id, ts)

            stage = "transcription"
            outcome = self._transcribe(record_id, source_id, path, meta, force)
            final = "done" if decision == "owner" else "needs_review"
            self.db.update_source(source_id, status=final, stage=stage, last_error=None)
            return outcome
        except Exception as exc:
            log.exception("Failed on %s at stage %s", path, stage)
            self.db.update_source(source_id, status="failed", stage=stage, last_error=str(exc)[:2000])
            self.db.log_failure(source_id, stage, str(exc))
            return f"failed at {stage}: {exc}"

    # --------------------------------------------------------------- stages
    def _audio(self, sha: str, path: Path) -> Path:
        wav = self.audio_cache / f"{sha[:24]}.wav"
        if not wav.exists():
            extract_audio(path, wav)
        return wav

    def _classify(
        self, source_id: str, path: Path, tags: dict[str, str], sidecar: list[dict], meta: dict
    ) -> tuple[str, dict[str, Any]]:
        detail: dict[str, Any] = {"filename_hints": meta["filename_hints"], "method": None}
        votes = []
        for rule in self.mp.ownership_rules:
            if rule.kind == "container_tag":
                values = [tags[rule.name]] if tags.get(rule.name) else []
            elif rule.kind == "sidecar":
                values = sidecar_values(sidecar, rule.name)
            else:
                raise ValueError(f"Unknown ownership rule kind '{rule.kind}'")
            owners = {v.strip().lower() for v in rule.owner_values}
            for v in values:
                votes.append(
                    {
                        "field": f"{rule.kind}:{rule.name}",
                        "value": v,
                        "decision": "owner" if v.strip().lower() in owners else "other",
                    }
                )
        detail["metadata_votes"] = votes

        voice: VoiceDecision | None = None
        profiles = self.profiles()
        if profiles is not None and meta["has_audio"]:
            src = self.db.get_source(source_id)
            wav = self._audio(src["sha256"], path)
            assert self._embedder is not None
            utt, windows, seconds = self._embedder.embed(load_wav(wav))
            voice = score(self.cfg.voice, profiles, utt, windows, seconds)
            detail["voice"] = {"decision": voice.decision, "reason": voice.reason, **voice.details}

        if votes:
            decisions = {v["decision"] for v in votes}
            if len(decisions) > 1:
                return "uncertain", {**detail, "reason": "sender metadata fields disagree"}
            decision = decisions.pop()
            if voice is not None and voice.decision in ("owner", "other") and voice.decision != decision:
                return "uncertain", {
                    **detail,
                    "reason": f"metadata says '{decision}' but voice check says '{voice.decision}'",
                }
            detail["method"] = "metadata"
            return decision, {**detail, "reason": "sender metadata"}

        if voice is not None:
            detail["method"] = "voice"
            return voice.decision, {**detail, "reason": voice.reason}

        why = "no sender metadata rule matched"
        if profiles is None:
            why += "; voice verification not configured (set voice.owner_samples_dir)"
        elif not meta["has_audio"]:
            why += "; video has no audio track"
        return "uncertain", {**detail, "reason": why}

    def _timestamp(self, path: Path, tags: dict[str, str], sidecar: list[dict]) -> timestamps.ResolvedTimestamp:
        return timestamps.resolve(self.mp, tags, sidecar, _mtime(path))

    def _queue_date_review(self, record_id: str, ts: timestamps.ResolvedTimestamp) -> None:
        if ts.review_reason:
            self.db.add_review(
                "date", ts.review_reason, record_id=record_id,
                details={"candidates": ts.evidence.get("candidates"), "rejected": ts.evidence.get("rejected")},
            )
        elif ts.confidence == "inferred":
            self.db.add_review(
                "date", "timezone assumed, not recorded", record_id=record_id, details=ts.evidence
            )

    def _refresh_timestamp(self, source_id: str, path: Path) -> None:
        """Re-evaluate dates on completed videos (cheap; no re-transcription).

        Lets newly confirmed ``timestamp_rules`` apply to earlier imports.
        """
        src = self.db.get_source(source_id)
        meta = json.loads(src["metadata_json"] or "{}")
        if not meta:
            return
        ts = timestamps.resolve(
            self.mp,
            meta.get("container_tags", {}),
            self.sidecars.lookup(path),
            datetime.fromisoformat(meta["file_mtime_utc"]),
        )
        for rec in self.db.records_for_source(source_id):
            self.db.upsert_machine_record(
                rec["record_id"],
                machine_date=ts.date,
                machine_time=ts.time,
                machine_timezone=ts.timezone,
                machine_confidence=ts.confidence,
                timestamp_utc=ts.utc,
                timestamp_evidence=ts.evidence,
            )
            if ts.date:
                self._close_reviews(rec["record_id"], "date", "resolved by confirmed metadata rule")
            self._queue_date_review(rec["record_id"], ts)

    def _close_reviews(self, record_id: str, kind: str, resolution: str) -> None:
        for item in self.db.review_items(status="open", kind=kind):
            if item["record_id"] == record_id and item["reason"] != "timezone assumed, not recorded":
                self.db.resolve_review(item["id"], resolution)

    def _transcribe(self, record_id: str, source_id: str, path: Path, meta: dict, force: bool) -> str:
        rec = self.db.get_record(record_id)
        if (
            rec["raw_transcript"] is not None
            and rec["transcription_status"] not in ("pending", "failed")
            and not force
        ):
            return "already transcribed"
        if not meta["has_audio"]:
            self.db.upsert_machine_record(
                record_id, raw_transcript="", transcription_status="no_audio",
                transcript_detail={"note": "video has no audio track"},
            )
            self.db.add_review("transcription", "video has no audio track", record_id=record_id)
            return "no audio"

        src = self.db.get_source(source_id)
        wav = self._audio(src["sha256"], path)
        started = time.monotonic()
        result = self.transcriber.transcribe(wav)
        self.db.upsert_machine_record(
            record_id,
            raw_transcript=result.text,
            transcription_status="machine",
            transcript_detail={
                "model": result.model,
                "language": result.language,
                "seconds_taken": round(time.monotonic() - started, 1),
                "segments": result.segments,
                "uncertain_segments": result.uncertain_segments,
            },
        )
        if not result.text.strip():
            self.db.add_review("transcription", "no speech recognised", record_id=record_id)
        if result.uncertain_segments:
            self.db.add_review(
                "transcription",
                f"{len(result.uncertain_segments)} low-confidence passage(s)",
                record_id=record_id,
                details={"segments": result.uncertain_segments},
            )
        wav.unlink(missing_ok=True)  # derived cache only; original untouched
        return f"transcribed ({len(result.text.split())} words)"

    def _flag_near_duplicates(self) -> None:
        """Different files with the same duration and recording time: likely re-encodes."""
        groups: dict[tuple, list[Any]] = {}
        for rec in self.db.all_records():
            if rec["source_type"] != SOURCE_TYPE or not rec["timestamp_utc"] or rec["duration"] is None:
                continue
            groups.setdefault((rec["timestamp_utc"], round(rec["duration"], 1)), []).append(rec)
        for (ts, dur), recs in groups.items():
            if len(recs) < 2:
                continue
            ids = sorted(r["record_id"] for r in recs)
            for r in recs:
                self.db.add_review(
                    "duplicate",
                    "possible duplicate recording (same time and duration, different file)",
                    record_id=r["record_id"],
                    details={"group": ids, "timestamp_utc": ts, "duration": dur},
                )


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _is_manual(src: Any) -> bool:
    try:
        return json.loads(src["ownership_detail"] or "{}").get("method") == "manual"
    except (TypeError, ValueError):
        return False


def _speaker_label(decision: str, detail: dict[str, Any]) -> str:
    method = detail.get("method")
    if decision != "owner":
        return f"unverified ({detail.get('reason', 'uncertain')})"
    if method == "manual":
        return "owner: confirmed in manual review"
    if method == "metadata":
        fields = ", ".join(f"{v['field']}={v['value']}" for v in detail.get("metadata_votes", []))
        label = f"owner: sender metadata ({fields})"
        voice = detail.get("voice")
        if voice and voice.get("decision") == "owner":
            label += f"; voice agrees (similarity {voice.get('similarity')})"
        return label
    if method == "voice":
        v = detail.get("voice", {})
        return (
            f"owner: voice match (similarity {v.get('similarity')}, "
            f"{round(100 * (v.get('owner_window_fraction') or 0))}% of speech windows)"
        )
    return "owner"


def set_manual_ownership(db: Database, source_id: str, decision: str, note: str = "") -> None:
    """Called from the review UI. Manual decisions are never overridden."""
    if decision not in ("owner", "other"):
        raise ValueError("decision must be 'owner' or 'other'")
    src = db.get_source(source_id)
    old = src["ownership"]
    detail = json.loads(src["ownership_detail"] or "{}")
    detail = {"method": "manual", "previous": detail, "note": note, "reason": "manual review"}
    db.update_source(source_id, ownership=decision, ownership_detail=detail, status="pending")
    with db.tx() as c:
        c.execute(
            "INSERT INTO corrections (source_id, field, old_value, new_value, note, at)"
            " VALUES (?,?,?,?,?,?)",
            (source_id, "ownership", old, decision, note, datetime.now(timezone.utc).isoformat()),
        )
    for item in db.review_items(status="open", kind="speaker"):
        if item["source_id"] == source_id:
            db.resolve_review(item["id"], f"manual: {decision}")
    if decision == "owner":
        for rec in db.records_for_source(source_id):
            db.upsert_machine_record(rec["record_id"], speaker_verification="owner: confirmed in manual review")

