#!/usr/bin/env python3
# Python 3 script that makes hashes for deduplicate.py using sha256sum.
# The script must find all files from the base dir (including subdirectories) and execute sha256sum or a similar library on them,
# saving the output to a file named hashes.txt in the base dir. The format must be that of sha256sum, i.e.:
# <hash> <relative path>
# All files must be included, including those in subdirectories and hidden files.
# The script must handle path names with spaces and special characters.
# The script must be optimized for performance and low memory usage on large file sets.
# The script must be cross-platform and work on Windows, Linux, and macOS.
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import deque
from pathlib import Path
from time import monotonic
from typing import Deque, Optional, Set, TextIO, Tuple

HASH_FILE_NAME = "hashes.txt"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB
STATS_WINDOW_SECONDS = 60


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


class StatsTracker:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.start_time = monotonic()
        self.last_report_time = self.start_time
        self.window: Deque[Tuple[float, int]] = deque()
        self.window_bytes = 0
        self.window_files = 0
        self.total_bytes = 0
        self.total_files = 0

    def _prune_window(self, now: float) -> None:
        cutoff = now - STATS_WINDOW_SECONDS
        while self.window and self.window[0][0] < cutoff:
            _, size = self.window.popleft()
            self.window_bytes -= size
            self.window_files -= 1

    def _report(self, now: float, force: bool = False) -> None:
        if not self.enabled or self.total_files == 0:
            return
        if not force and (now - self.last_report_time) < STATS_WINDOW_SECONDS:
            return

        self._prune_window(now)

        window_span = max(
            now - (self.window[0][0] if self.window else self.start_time), 1e-9
        )
        total_span = max(now - self.start_time, 1e-9)

        window_mib = self.window_bytes / (1024 * 1024)
        window_rate = window_mib / window_span if window_span else 0.0
        total_mib = self.total_bytes / (1024 * 1024)
        total_rate = total_mib / total_span if total_span else 0.0

        eprint(
            "[stats] last 60s: "
            f"{self.window_files} files, {window_mib:.2f} MiB, {window_rate:.2f} MiB/s; "
            f"total: {self.total_files} files, {total_mib:.2f} MiB, {total_rate:.2f} MiB/s"
        )
        self.last_report_time = now

    def record(self, size_bytes: int) -> None:
        if not self.enabled:
            return
        now = monotonic()
        self.total_files += 1
        self.total_bytes += size_bytes
        self.window.append((now, size_bytes))
        self.window_bytes += size_bytes
        self.window_files += 1
        self._prune_window(now)
        if (now - self.last_report_time) >= STATS_WINDOW_SECONDS:
            self._report(now)

    def finalize(self) -> None:
        if not self.enabled:
            return
        self._report(monotonic(), force=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate sha256-style hashes.txt for the base path."
    )
    parser.add_argument(
        "base",
        nargs="?",
        default=".",
        help="Base directory to scan (default: current directory).",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Chunk size in bytes when reading files (default: 8 MiB).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress information to stderr.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print throughput stats (files and MiB/s) roughly every minute to stderr.",
    )
    parser.add_argument(
        "--ignore-existing",
        action="store_true",
        help="Skip hashing files already listed in existing hashes.txt files.",
    )
    return parser.parse_args()


def hash_file(path: Path, chunk_size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_existing_path(rel_path: str) -> Optional[str]:
    cleaned = rel_path.strip().replace("\\", "/")
    if not cleaned or cleaned == ".":
        return None
    if Path(cleaned).is_absolute():
        return None
    return Path(cleaned).as_posix()


def read_existing_hashes(hash_path: Path) -> Set[str]:
    entries: Set[str] = set()
    try:
        with hash_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split(maxsplit=1)
                if len(parts) != 2:
                    eprint(f"[warn] {hash_path}:{line_no}: expected '<hash> <relative path>'")
                    continue
                normalized = normalize_existing_path(parts[1])
                if not normalized:
                    eprint(f"[warn] {hash_path}:{line_no}: invalid relative path: {parts[1]}")
                    continue
                entries.add(normalized)
    except OSError as exc:
        eprint(f"[warn] Failed to read {hash_path}: {exc}")
    return entries


def rotate_hash_file(hash_path: Path) -> bool:
    if not hash_path.exists():
        return True
    if not hash_path.is_file():
        eprint(f"[error] Expected file at {hash_path}, found non-file.")
        return False
    index = 0
    while True:
        candidate = hash_path.with_name(f"{HASH_FILE_NAME}.{index}")
        if not candidate.exists():
            try:
                hash_path.rename(candidate)
                return True
            except OSError as exc:
                eprint(f"[error] Failed to rename {hash_path} to {candidate}: {exc}")
                return False
        index += 1


def process_directory(
    directory: Path,
    base_path: Path,
    writer: TextIO,
    chunk_size: int,
    verbose: bool,
    stats: StatsTracker,
    existing_paths: Optional[Set[str]],
    ignore_existing: bool,
) -> None:
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda e: e.name.lower())
    except OSError as exc:
        eprint(f"[error] Failed to list {directory}: {exc}")
        return

    for entry in entries:
        name = entry.name
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
            is_file = entry.is_file(follow_symlinks=False)
        except OSError as exc:
            eprint(f"[warn] Could not stat {Path(directory, name)}: {exc}")
            continue

        if name == HASH_FILE_NAME:
            continue

        if is_dir:
            process_directory(
                Path(directory, name),
                base_path,
                writer,
                chunk_size,
                verbose,
                stats,
                existing_paths,
                ignore_existing,
            )
            continue

        if not is_file:
            continue

        file_path = Path(directory, name)
        rel_path = file_path.relative_to(base_path).as_posix()
        if ignore_existing and existing_paths is not None and rel_path in existing_paths:
            continue

        try:
            file_size = file_path.stat().st_size
        except OSError as exc:
            eprint(f"[warn] Failed to stat {file_path}: {exc}")
            continue

        try:
            digest = hash_file(file_path, chunk_size)
        except OSError as exc:
            eprint(f"[warn] Failed to hash {file_path}: {exc}")
            continue

        try:
            writer.write(f"{digest} {rel_path}\n")
        except Exception as exc:  # noqa: BLE001
            eprint(f"[warn] Failed to record hash for {file_path}: {exc}")
            continue

        if ignore_existing and existing_paths is not None:
            existing_paths.add(rel_path)

        stats.record(file_size)

        if verbose:
            eprint(f"[info] Hashed {file_path}")


def main() -> int:
    args = parse_args()
    base_path = Path(args.base).expanduser().resolve()
    if args.chunk_size <= 0:
        eprint("Chunk size must be a positive integer.")
        return 1
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1

    output_path = base_path / HASH_FILE_NAME
    if output_path.exists() and not output_path.is_file():
        eprint(f"[error] Expected file at {output_path}, found non-file.")
        return 1

    if args.ignore_existing:
        existing_paths: Optional[Set[str]] = (
            read_existing_hashes(output_path) if output_path.exists() else set()
        )
        mode = "a"
    else:
        if not rotate_hash_file(output_path):
            return 1
        existing_paths = None
        mode = "w"

    try:
        writer = output_path.open(mode, encoding="utf-8", newline="\n")
    except OSError as exc:
        eprint(f"[error] Failed to open {output_path} for writing: {exc}")
        return 1

    stats = StatsTracker(enabled=args.stats)
    with writer:
        process_directory(
            base_path,
            base_path,
            writer,
            args.chunk_size,
            args.verbose,
            stats,
            existing_paths,
            args.ignore_existing,
        )
    stats.finalize()
    eprint("Finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
