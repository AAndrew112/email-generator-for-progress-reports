"""Logging, progress reporting, run locking and file hashing."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger("pha")


def setup_logging(log_dir: Path, verbose: bool = False) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pha.log"
    root = logging.getLogger("pha")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(message)s"))
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)
    return log_file


class Progress:
    """Plain-text progress lines that work in any terminal and in log files."""

    def __init__(self, total: int, label: str) -> None:
        self.total = total
        self.label = label
        self.done = 0
        self.counts: dict[str, int] = {}
        self.start = time.monotonic()

    def step(self, name: str, outcome: str) -> None:
        self.done += 1
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        elapsed = time.monotonic() - self.start
        eta = ""
        if self.done and self.done < self.total:
            remaining = elapsed / self.done * (self.total - self.done)
            eta = f" eta {remaining / 60:.1f}m"
        log.info("[%s %d/%d]%s %s: %s", self.label, self.done, self.total, eta, name, outcome)

    def summary(self) -> str:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        return f"{self.label}: {self.done}/{self.total} processed ({parts})"


@contextmanager
def run_lock(data_dir: Path) -> Iterator[None]:
    """Prevent two pipeline runs from writing the same archive at once."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = data_dir / ".run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pid = lock.read_text().strip() if lock.exists() else "?"
        if pid.isdigit() and not _pid_alive(int(pid)):
            log.warning("Removing stale lock from process %s", pid)
            lock.unlink()
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            raise RuntimeError(
                f"Another run (pid {pid}) is using {data_dir}. If none is running, delete {lock}."
            ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()
