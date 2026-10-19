"""``pha mp inspect``: describe an export before trusting any of its metadata.

Writes a Markdown and a JSON report covering folder layout, file types,
sidecar manifests and their fields, container tags, filename patterns and,
for every date-like field, whether its values look like recording times or
like export/download times. Nothing is modified and nothing is transcribed.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..media import all_tags, duration_seconds, has_audio, probe, require_ffmpeg
from .filenames import parse_filename
from .pipeline import discover, icloud_placeholders
from .sidecar import SidecarIndex
from .timestamps import find_candidates

SENDER_HINTS = re.compile(r"sender|from|author|creator|owner|user|name|artist|speaker|by", re.I)


def _pattern(name: str) -> str:
    return re.sub(r"[A-Za-z]+", "a", re.sub(r"\d+", lambda m: "9" * len(m.group()), name))


def _even_sample(items: list[Path], n: int | None) -> list[Path]:
    if not n or len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def inspect_export(cfg: Config, sample: int | None = 200) -> dict[str, Any]:
    require_ffmpeg()
    root = cfg.path(cfg.marco_polo.input_dir)
    if not root.exists():
        raise RuntimeError(f"Marco Polo input folder not found: {root}")

    all_files = [p for p in root.rglob("*") if p.is_file()]
    videos = discover(root, cfg.marco_polo.video_extensions)
    ext_counts = Counter(p.suffix.lower() or "(none)" for p in all_files)
    dirs = Counter(str(p.parent.relative_to(root)) for p in videos)
    sidecars = SidecarIndex(root, cfg.marco_polo.video_extensions)

    tag_coverage: Counter[str] = Counter()
    tag_examples: dict[str, list[str]] = defaultdict(list)
    sidecar_coverage: Counter[str] = Counter()
    sidecar_examples: dict[str, Counter[str]] = defaultdict(Counter)
    date_fields: dict[str, list[dict[str, Any]]] = defaultdict(list)
    durations, no_audio, probe_errors = [], 0, []
    patterns = Counter(_pattern(p.name) for p in videos)
    with_sidecar = 0

    sampled = _even_sample(videos, sample)
    for path in sampled:
        try:
            info = probe(path)
        except Exception as exc:
            probe_errors.append(f"{path.name}: {exc}")
            continue
        tags = all_tags(info)
        if not has_audio(info):
            no_audio += 1
        d = duration_seconds(info)
        if d is not None:
            durations.append(d)
        for k, v in tags.items():
            tag_coverage[k] += 1
            if len(tag_examples[k]) < 3 and v not in tag_examples[k]:
                tag_examples[k].append(v[:120])
        entries = sidecars.lookup(path)
        if entries:
            with_sidecar += 1
        for entry in entries:
            for k, v in entry["fields"].items():
                sidecar_coverage[k] += 1
                sidecar_examples[k][v[:120]] += 1
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        fn = parse_filename(path.stem, cfg.marco_polo.filename_pattern)
        for c in find_candidates(tags, entries, mtime, cfg.marco_polo.contamination_window_hours, fn):
            date_fields[f"{c['kind']}:{c['name']}"].append(c)

    date_analysis = {}
    for name, cands in date_fields.items():
        parsed = sorted(c["parsed"] for c in cands)
        near = sum(c["near_file_mtime"] for c in cands)
        implausible = sum(bool(c["implausible"]) for c in cands)
        distinct_days = len({p[:10] for p in parsed})
        verdict = "possible recording time; verify against videos you remember"
        if near / len(cands) > 0.5:
            verdict = "LIKELY EXPORT/DOWNLOAD TIME (matches file modification time); do not trust"
        elif distinct_days == 1 and len(cands) > 3:
            verdict = "SUSPICIOUS: every video has the same day; probably export time"
        elif implausible / len(cands) > 0.5:
            verdict = "mostly placeholder/implausible values"
        date_analysis[name] = {
            "videos_with_value": len(cands),
            "has_timezone": sum(c["has_timezone"] for c in cands),
            "earliest": parsed[0],
            "latest": parsed[-1],
            "distinct_days": distinct_days,
            "near_file_mtime": near,
            "implausible": implausible,
            "examples": [c["value"] for c in cands[:3]],
            "verdict": verdict,
        }

    sender_fields = {
        k: dict(v.most_common(8))
        for k, v in sidecar_examples.items()
        if SENDER_HINTS.search(k.split(".")[-1]) and len(v) <= 50
    }
    sender_tags = {
        k: tag_examples[k] for k in tag_coverage if SENDER_HINTS.search(k.split(":")[-1])
    }

    video_set = set(videos)
    # File-name metadata is cheap to read, so cover every video, not a sample.
    senders: Counter[str] = Counter()
    sender_examples: dict[str, list[str]] = defaultdict(list)
    tz_abbrevs: Counter[str] = Counter()
    fn_dates: list[str] = []
    for path in videos:
        fn = parse_filename(path.stem, cfg.marco_polo.filename_pattern)
        if not fn:
            continue
        if "sender" in fn:
            senders[fn["sender"]] += 1
            if len(sender_examples[fn["sender"]]) < 3:
                sender_examples[fn["sender"]].append(str(path.relative_to(root)))
        if "tz_abbreviation" in fn:
            tz_abbrevs[fn["tz_abbreviation"]] += 1
        if "timestamp" in fn:
            fn_dates.append(fn["timestamp"][:10])
    filename_metadata = {
        "pattern": cfg.marco_polo.filename_pattern,
        "videos_matching": sum(senders.values()) if senders else len(fn_dates),
        "senders": dict(senders.most_common()),
        "spot_check_examples": dict(sender_examples),
        "timezone_abbreviations": dict(tz_abbrevs.most_common()),
        "earliest_date": min(fn_dates) if fn_dates else None,
        "latest_date": max(fn_dates) if fn_dates else None,
    }
    return {
        "input_dir": str(root),
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "total_files": len(all_files),
        "video_files": len(videos),
        "icloud_not_downloaded": [
            str(p.relative_to(root)) for p in icloud_placeholders(root, cfg.marco_polo.video_extensions)
        ],
        "videos_probed": len(sampled),
        "extensions": dict(ext_counts.most_common()),
        "folders_with_videos": dict(dirs.most_common(30)),
        "filename_patterns": dict(patterns.most_common(15)),
        "filename_metadata": filename_metadata,
        "non_video_files": sorted(
            str(p.relative_to(root)) for p in all_files if p not in video_set
        )[:100],
        "sidecar_manifests": sidecars.manifests,
        "sidecar_errors": sidecars.errors,
        "videos_with_sidecar_metadata": with_sidecar,
        "sidecar_fields": {k: {"coverage": c, "examples": list(sidecar_examples[k])[:3]} for k, c in sidecar_coverage.most_common()},
        "container_tags": {k: {"coverage": c, "examples": tag_examples[k]} for k, c in tag_coverage.most_common()},
        "possible_sender_fields": {"sidecar": sender_fields, "container_tags": sender_tags},
        "date_fields": date_analysis,
        "videos_without_audio": no_audio,
        "duration_seconds": {
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
            "mean": sum(durations) / len(durations) if durations else None,
        },
        "probe_errors": probe_errors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    L = [
        "# Marco Polo export inspection",
        "",
        f"- Folder: `{report['input_dir']}`",
        f"- Files: {report['total_files']} total, {report['video_files']} videos "
        f"({report['videos_probed']} probed)",
        f"- Videos with sidecar metadata: {report['videos_with_sidecar_metadata']}",
        f"- Videos without audio: {report['videos_without_audio']}",
        "",
    ]
    if report["icloud_not_downloaded"]:
        L += [
            f"**{len(report['icloud_not_downloaded'])} video(s) are in iCloud only and were not "
            "inspected.** In Finder, right-click the folder and choose Download Now, then run "
            "this again.",
            "",
        ]
    L += [
        "## File types",
        *[f"- `{k}`: {v}" for k, v in report["extensions"].items()],
        "",
        "## Filename patterns (9 = digit, a = letters)",
        *[f"- `{k}`: {v}" for k, v in report["filename_patterns"].items()],
        "",
        "## Metadata in file names",
        *_filename_section(report["filename_metadata"], report["video_files"]),
        "",
        "## Sidecar manifests",
        *([f"- `{m}`" for m in report["sidecar_manifests"]] or ["- none found"]),
        "",
        "## Possible sender fields",
    ]
    ps = report["possible_sender_fields"]
    if not ps["sidecar"] and not ps["container_tags"]:
        L.append("- none found: ownership will need voice verification or manual review")
    for k, v in ps["sidecar"].items():
        L.append(f"- sidecar `{k}`: {v}")
    for k, v in ps["container_tags"].items():
        L.append(f"- container tag `{k}`: {v}")
    L += ["", "## Date-like fields", ""]
    if not report["date_fields"]:
        L.append("No date-like metadata found. Videos will stay undated unless dated in review.")
    for name, a in report["date_fields"].items():
        L += [
            f"### `{name}`",
            f"- videos: {a['videos_with_value']}, with timezone: {a['has_timezone']}",
            f"- range: {a['earliest']} .. {a['latest']} ({a['distinct_days']} distinct days)",
            f"- near file modification time: {a['near_file_mtime']}; implausible: {a['implausible']}",
            f"- examples: {a['examples']}",
            f"- **verdict: {a['verdict']}**",
            "",
        ]
    L += [
        "## Container tags",
        *[f"- `{k}` ({v['coverage']}): {v['examples']}" for k, v in report["container_tags"].items()],
        "",
        "## Next steps",
        "1. Pick a few videos whose recording date and sender you know.",
        "2. Check the fields above against them.",
        "3. Add only verified fields to `[[marco_polo.timestamp_rules]]` and "
        "`[[marco_polo.ownership_rules]]` in config.toml.",
        "4. If there is no reliable sender field, set `voice.owner_samples_dir` and run "
        "`pha mp calibrate`.",
        "",
    ]
    return "\n".join(L)


def _filename_section(fm: dict[str, Any], total: int) -> list[str]:
    if not fm["videos_matching"]:
        return ["- no file names match `marco_polo.filename_pattern`"]
    lines = [
        f"- {fm['videos_matching']} of {total} videos match the pattern",
        f"- dates in names: {fm['earliest_date']} .. {fm['latest_date']}",
        f"- timezone abbreviations: {fm['timezone_abbreviations']}",
        "- senders (videos each) and files to spot-check:",
    ]
    for sender, n in fm["senders"].items():
        lines.append(f"  - **{sender}**: {n}")
        lines += [f"    - `{e}`" for e in fm["spot_check_examples"].get(sender, [])]
    lines.append(
        "- Watch the examples: if each sender name matches who is speaking and the dates "
        "look right, add the filename rules to config.toml (see README)."
    )
    return lines


def write_report(cfg: Config, report: dict[str, Any]) -> tuple[Path, Path]:
    out = cfg.data_path / "inspect"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    j = out / f"marco_polo_{stamp}.json"
    m = out / f"marco_polo_{stamp}.md"
    j.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    m.write_text(render_markdown(report), encoding="utf-8")
    return m, j
