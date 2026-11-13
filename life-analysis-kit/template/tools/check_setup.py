#!/usr/bin/env python3
"""OPERATOR-RUN. Verifies the privacy guardrails before you start a session. Offline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SYNCED = ("Mobile Documents", "iCloud", "Dropbox", "Google Drive", "GoogleDrive", "OneDrive", "Box Sync")
REQUIRED_DENY = ["WebFetch", "WebSearch", "Bash(curl:*)", "Bash(wget:*)", "Read(./private/**)",
                 "Read(./out_real/**)", "Edit(./raw/**)", "Edit(./private/**)", "Bash(*ntfy*)",
                 "Bash(*/.claude/hooks/*)"]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    results: list[tuple[bool, str]] = []

    def check(ok: bool, msg: str) -> None:
        results.append((ok, msg))

    check(not any(s in str(root) for s in SYNCED), "project folder is not inside a synced folder")
    settings = root / ".claude" / "settings.json"
    deny = []
    if settings.exists():
        deny = json.loads(settings.read_text()).get("permissions", {}).get("deny", [])
    for rule in REQUIRED_DENY:
        check(rule in deny, f"settings.json denies {rule}")
    perms = json.loads(settings.read_text()).get("permissions", {}) if settings.exists() else {}
    check(perms.get("defaultMode") in ("acceptEdits", "default"),
          "permission mode is not auto or bypass (you approve commands)")
    check(not any(r.startswith("Write(") for r in deny), "no Write(...) deny rules (Claude Code ignores them; Edit(...) covers writes)")
    sb = json.loads(settings.read_text()).get("sandbox", {}) if settings.exists() else {}
    check(sb.get("enabled") is True and sb.get("failIfUnavailable") is True,
          "sandbox is enabled and required (commands cannot silently run outside it)")
    check(sb.get("allowUnsandboxedCommands") is False, "commands cannot retry outside the sandbox")
    check(not sb.get("network", {}).get("allowedDomains"), "sandbox allows no network domains")
    archive = root / "raw" / "archive.json"
    check(archive.exists(), "raw/archive.json is present")
    check(archive.exists() and not (archive.stat().st_mode & 0o222), "raw/archive.json is read-only")
    check((root / "private" / "names_input.csv").exists(), "private/names_input.csv exists")
    git = subprocess.run(["git", "-C", str(root), "remote", "-v"], capture_output=True, text=True)
    check(not git.stdout.strip(), "no git remote is configured here or in a parent repo")
    gi = (root / ".gitignore").read_text() if (root / ".gitignore").exists() else ""
    check(all(d in gi for d in ("raw/", "work/", "private/", "out/")), ".gitignore covers raw/ work/ private/ out/")
    for ok, msg in results:
        print(("PASS  " if ok else "FAIL  ") + msg)
    print("\nAlso do by hand: disable MCP connectors for this session; check your account's "
          "data-retention settings.")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
