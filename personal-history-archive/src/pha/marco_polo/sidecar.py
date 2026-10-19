"""Discover metadata that sits *next to* exported videos.

The structure of a Marco Polo export is not assumed. Instead, every JSON and
CSV file under the input folder is scanned for objects/rows that reference a
video filename, and same-stem sidecar files (``clip.mp4`` + ``clip.json``) are
attached directly. Fields are flattened to dotted keys (``sender.name``) so
``pha mp inspect`` can show them and the user can choose which to trust.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("pha.mp.sidecar")

MAX_MANIFEST_BYTES = 50 * 1024 * 1024


def flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten(v, key))
    elif isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            out[prefix] = ", ".join(str(v) for v in obj)
        else:
            for i, v in enumerate(obj):
                out.update(flatten(v, f"{prefix}[{i}]"))
    elif obj is not None:
        out[prefix] = str(obj)
    return out


def _basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


class SidecarIndex:
    """Index of metadata entries keyed by lower-cased video basename."""

    def __init__(self, root: Path, video_extensions: Iterable[str]) -> None:
        self.root = root
        self.exts = {e.lower() for e in video_extensions}
        self.entries: dict[str, list[dict[str, Any]]] = {}
        self.manifests: list[str] = []
        self.errors: list[str] = []
        self._build()

    def _looks_like_video(self, value: str) -> bool:
        name = _basename(value)
        return any(name.endswith(ext) for ext in self.exts)

    def _add(self, video_name: str, manifest: Path, fields: dict[str, str]) -> None:
        entry = {"manifest": str(manifest.relative_to(self.root)), "fields": fields}
        bucket = self.entries.setdefault(video_name, [])
        if entry not in bucket:
            bucket.append(entry)

    def _build(self) -> None:
        if not self.root.exists():
            return
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name.startswith("._"):
                continue
            suffix = path.suffix.lower()
            if suffix not in (".json", ".csv"):
                continue
            if path.stat().st_size > MAX_MANIFEST_BYTES:
                self.errors.append(f"{path}: skipped (larger than 50 MB)")
                continue
            try:
                if suffix == ".json":
                    self._index_json(path)
                else:
                    self._index_csv(path)
                self.manifests.append(str(path.relative_to(self.root)))
            except Exception as exc:  # malformed sidecars must not stop processing
                self.errors.append(f"{path}: {exc}")
                log.warning("Could not parse sidecar %s: %s", path, exc)

    def _same_stem_videos(self, path: Path) -> list[str]:
        return [
            p.name.lower()
            for p in path.parent.glob(path.stem + ".*")
            if p.suffix.lower() in self.exts
        ]

    def _index_json(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        stems = self._same_stem_videos(path)
        if stems and isinstance(data, dict):
            for name in stems:
                self._add(name, path, flatten(data))
        for obj in _walk_dicts(data):
            for value in obj.values():
                if isinstance(value, str) and self._looks_like_video(value):
                    self._add(_basename(value), path, flatten(obj))

    def _index_csv(self, path: Path) -> None:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                clean = {str(k): str(v) for k, v in row.items() if k is not None and v not in (None, "")}
                for value in clean.values():
                    if self._looks_like_video(value):
                        self._add(_basename(value), path, clean)

    def lookup(self, video: Path) -> list[dict[str, Any]]:
        return self.entries.get(video.name.lower(), [])


def _walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


def sidecar_values(entries: list[dict[str, Any]], field_name: str) -> list[str]:
    """All values of ``field_name`` across the sidecar entries for one video."""
    out = []
    for entry in entries:
        value = entry["fields"].get(field_name)
        if value not in (None, ""):
            out.append(value)
    return out
