"""Command-line interface: ``pha <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from .config import Config, load_config
from .db import Database
from .runtime import run_lock, setup_logging

log = logging.getLogger("pha")


def _load(args: argparse.Namespace) -> Config:
    path = Path(args.config)
    if not path.exists():
        sys.exit(f"Config file {path} not found. Run 'pha init' first.")
    cfg = load_config(path)
    setup_logging(cfg.log_path, args.verbose)
    return cfg


def cmd_init(args: argparse.Namespace) -> None:
    target = Path(args.config)
    if target.exists():
        sys.exit(f"{target} already exists; not overwriting.")
    example = Path(__file__).resolve().parent / "config.example.toml"
    shutil.copy(example, target)
    print(f"Wrote {target}. Edit the paths in it, then run 'pha mp inspect'.")


def cmd_status(args: argparse.Namespace) -> None:
    cfg = _load(args)
    db = Database(cfg.db_path)
    for row in db.conn.execute(
        "SELECT source_type, status, COUNT(*) n FROM sources GROUP BY 1, 2 ORDER BY 1, 2"
    ):
        print(f"{row['source_type']:<12} {row['status']:<14} {row['n']}")
    n = db.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    print(f"records: {n}")
    for row in db.conn.execute(
        "SELECT kind, COUNT(*) n FROM review_items WHERE status = 'open' GROUP BY kind"
    ):
        print(f"open review ({row['kind']}): {row['n']}")


def cmd_mp_inspect(args: argparse.Namespace) -> None:
    from .marco_polo.inspect import inspect_export, write_report

    cfg = _load(args)
    report = inspect_export(cfg, sample=args.sample)
    md, js = write_report(cfg, report)
    print(md.read_text())
    print(f"\nReport saved to {md} and {js}")


def cmd_mp_calibrate(args: argparse.Namespace) -> None:
    from .voice import build_profiles, calibrate, make_embedder

    cfg = _load(args)
    profiles = build_profiles(cfg.voice, Path(cfg.base_dir), cfg.cache_path, make_embedder(cfg.voice))
    print(json.dumps(calibrate(profiles), indent=2))


def cmd_mp_process(args: argparse.Namespace) -> None:
    from .marco_polo.pipeline import MarcoPoloPipeline

    cfg = _load(args)
    with run_lock(cfg.data_path):
        db = Database(cfg.db_path)
        MarcoPoloPipeline(cfg, db).run(
            retry_failed=args.retry_failed,
            reclassify=args.reclassify,
            force_retranscribe=args.force_retranscribe,
            limit=args.limit,
            allow_delete=not args.keep_files,
        )


def cmd_journals_auth(args: argparse.Namespace) -> None:
    from .journals.drive import get_service

    cfg = _load(args)
    jc = cfg.journals
    token = cfg.path(jc.token_file) if jc.token_file else cfg.data_path / "google_token.json"
    get_service(cfg.path(jc.client_secret_file), token)
    print(f"Authenticated with read-only Drive access. Token stored at {token}")


def cmd_journals_list(args: argparse.Namespace) -> None:
    from .journals import drive as gdrive
    from .journals.entries import year_hints

    cfg = _load(args)
    jc = cfg.journals
    token = cfg.path(jc.token_file) if jc.token_file else cfg.data_path / "google_token.json"
    service = gdrive.get_service(cfg.path(jc.client_secret_file), token)
    roots = (
        [{"id": jc.drive_folder_id, "name": jc.drive_folder_name}]
        if jc.drive_folder_id
        else gdrive.find_folders(service, jc.drive_folder_name)
    )
    if not roots:
        sys.exit(f"No Drive folder named '{jc.drive_folder_name}'")
    for root in roots:
        print(f"# {root['name']} ({root['id']})")
        files = sorted(gdrive.walk_pdfs(service, root["id"], [root["name"]]), key=lambda f: f.display_path)
        for f in files:
            hints = year_hints(*f.folder_path, f.name)
            print(f"{f.display_path}\tyears in path: {hints or '-'}\t{(f.size or 0) / 1e6:.1f} MB")
        print(f"{len(files)} PDFs")


def cmd_journals_process(args: argparse.Namespace) -> None:
    from .journals.pipeline import JournalPipeline

    cfg = _load(args)
    with run_lock(cfg.data_path):
        db = Database(cfg.db_path)
        JournalPipeline(cfg, db).run(
            source=args.source, retry_failed=args.retry_failed, force=args.force, limit=args.limit
        )


def cmd_journals_evaluate(args: argparse.Namespace) -> None:
    from .journals.evaluate import evaluate

    cfg = _load(args)
    result = evaluate(Database(cfg.db_path), Path(args.truth))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_review(args: argparse.Namespace) -> None:
    from .review.app import serve

    cfg = _load(args)
    serve(cfg, port=args.port)


def cmd_export(args: argparse.Namespace) -> None:
    from .export import export_archive

    cfg = _load(args)
    summary = export_archive(Database(cfg.db_path), cfg.export_path)
    print(json.dumps(summary, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pha", description="Personal history archive")
    p.add_argument("--config", default="config.toml", help="path to config.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create config.toml from the example").set_defaults(func=cmd_init)
    sub.add_parser("status", help="show processing status").set_defaults(func=cmd_status)

    mp = sub.add_parser("mp", help="Marco Polo videos").add_subparsers(dest="mp_command", required=True)
    s = mp.add_parser("inspect", help="report export structure and metadata (changes nothing)")
    s.add_argument("--sample", type=int, default=200, help="number of videos to probe (0 = all)")
    s.set_defaults(func=cmd_mp_inspect)
    mp.add_parser("calibrate", help="check voice samples and suggest thresholds").set_defaults(func=cmd_mp_calibrate)
    s = mp.add_parser("process", help="classify, date and transcribe videos")
    s.add_argument("--retry-failed", action="store_true")
    s.add_argument("--reclassify", action="store_true", help="redo automatic ownership decisions")
    s.add_argument("--force-retranscribe", action="store_true")
    s.add_argument(
        "--keep-files", action="store_true",
        help="skip delete_after_processing for this run",
    )
    s.add_argument("--limit", type=int)
    s.set_defaults(func=cmd_mp_process)

    jr = sub.add_parser("journals", help="handwritten journals").add_subparsers(dest="jr_command", required=True)
    jr.add_parser("auth", help="sign in to Google Drive (read-only)").set_defaults(func=cmd_journals_auth)
    jr.add_parser("list", help="list journal PDFs in Drive").set_defaults(func=cmd_journals_list)
    s = jr.add_parser("process", help="transcribe journal PDFs")
    s.add_argument("--source", choices=["drive", "local"], default="drive")
    s.add_argument("--retry-failed", action="store_true")
    s.add_argument("--force", action="store_true", help="re-transcribe pages already done")
    s.add_argument("--limit", type=int, help="only the first N PDFs (for sampling)")
    s.set_defaults(func=cmd_journals_process)
    s = jr.add_parser("evaluate", help="score transcriptions against hand-checked pages")
    s.add_argument("--truth", required=True, help="folder of <pdf stem>__p<page>.txt files")
    s.set_defaults(func=cmd_journals_evaluate)

    s = sub.add_parser("review", help="open the local review interface")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_review)
    sub.add_parser("export", help="write CSV, JSON, text files and review queue").set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "sample", None) == 0:
        args.sample = None
    args.func(args)


if __name__ == "__main__":
    main()
