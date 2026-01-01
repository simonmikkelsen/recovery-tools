"""
This python 3 script finds all files named *.damaged in the specified directory tree and truncates them to 0 bytes while keeping all time stampes intact.

Keep stats of how many files were truncated, total bytes truncated, and average bytes truncated per file.
Usage: python3 truncate-damaged-files.py <directory> [--extension .damaged] [-v|--verbose] [-n|--dry-run] [-h|--help]
The script processes all files in the specified directory and its subdirectories.

Keep this text in the file but do not use it directly in the help section.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Tuple


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Truncate damaged files to zero bytes while preserving timestamps."
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan for damaged files.",
    )
    parser.add_argument(
        "--extension",
        default=".damaged",
        help="Extension used to mark damaged files (default: .damaged).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be truncated without writing files.",
    )
    return parser.parse_args()


def iter_damaged_files(base_path: Path, extension: str) -> Iterable[Path]:
    for root, _, filenames in os.walk(base_path):
        for name in filenames:
            if extension and not name.endswith(extension):
                continue
            yield Path(root) / name


def truncate_file(path: Path, dry_run: bool, verbose: bool) -> Tuple[bool, int]:
    try:
        stat_info = path.stat()
    except OSError as exc:
        eprint(f"[warn] Failed to stat {path}: {exc}")
        return False, 0

    size = stat_info.st_size
    if dry_run:
        print(f"[DRY RUN] {path} ({size} bytes)")
        return True, size

    try:
        with path.open("r+b") as handle:
            handle.truncate(0)
        os.utime(path, ns=(stat_info.st_atime_ns, stat_info.st_mtime_ns))
    except OSError as exc:
        eprint(f"[error] Failed to truncate {path}: {exc}")
        return False, 0

    if verbose:
        eprint(f"[info] Truncated {path} ({size} bytes)")
    return True, size


def process_damaged_files(
    base_path: Path,
    extension: str,
    dry_run: bool,
    verbose: bool,
) -> Tuple[int, int]:
    truncated = 0
    total_bytes = 0

    for damaged_path in iter_damaged_files(base_path, extension):
        ok, size = truncate_file(damaged_path, dry_run=dry_run, verbose=verbose)
        if not ok:
            continue
        truncated += 1
        total_bytes += size

    return truncated, total_bytes


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1

    truncated, total_bytes = process_damaged_files(
        base_path=base_path,
        extension=args.extension,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    avg_bytes = (total_bytes / truncated) if truncated else 0.0
    print(f"Truncated files: {truncated}")
    print(f"Total bytes truncated: {total_bytes}")
    print(f"Average bytes truncated per file: {avg_bytes:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
