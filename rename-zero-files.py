"""
This script looks at the contents of all files in a specified directory tree and renames any files which contents is only
binary zero bytes (i.e. all bytes are 0x00) to have a .damaged extension added to their filename.
The extension can be given using the --extension argument, which defaults to .damaged.

Start by reading at most 8 bytes form a file to determine if it is a zero file. If all bytes are zero, read the rest of the file in 1 MiB chunks to confirm it is a zero file.
If a file is confirmed to be a zero file, rename it by adding the specified extension to the filename.

Usage: python3 rename-zero-files.py <directory> [--extension .damaged]
The script processes all files in the specified directory and its subdirectories.

"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HEAD_CHECK_BYTES = 8
TAIL_CHECK_CHUNK = 1024 * 1024
DEFAULT_MIN_BYTES = 8


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename all-zero files by appending an extension.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan.",
    )
    parser.add_argument(
        "--extension",
        default=".damaged",
        help="Extension to append to zero files (default: .damaged).",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=DEFAULT_MIN_BYTES,
        help="Minimum size in bytes required to rename a zero file (default: 8).",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without making changes.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    return parser.parse_args()


def is_all_zero(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(HEAD_CHECK_BYTES)
            if head and head.count(0) != len(head):
                return False
            while True:
                chunk = handle.read(TAIL_CHECK_CHUNK)
                if not chunk:
                    return True
                if chunk.count(0) != len(chunk):
                    return False
    except OSError as exc:
        eprint(f"[warn] Failed to read {path}: {exc}")
        return False


def rename_zero_files(
    base_path: Path,
    extension: str,
    dry_run: bool,
    verbose: bool,
    min_bytes: int,
) -> int:
    renamed = 0
    for root, dirnames, filenames in os.walk(base_path):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            path = Path(root) / name
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                eprint(f"[warn] Failed to stat {path}: {exc}")
                continue
            if size <= min_bytes:
                if verbose:
                    eprint(f"[info] Skipping {path} ({size} bytes) under or equal to {min_bytes} bytes.")
                continue
            if extension and name.endswith(extension):
                if verbose:
                    eprint(f"[info] Skipping already tagged {path}")
                continue
            if not is_all_zero(path):
                if verbose:
                    eprint(f"[info] Skipping non-zero {path}")
                continue
            target = path.with_name(f"{name}{extension}")
            if target.exists():
                eprint(f"[warn] Target exists, skipping {path}")
                continue
            if dry_run:
                print(f"[DRY RUN] {path} -> {target}")
                continue
            try:
                path.rename(target)
                renamed += 1
                if verbose:
                    eprint(f"[info] Renamed {path} -> {target}")
            except OSError as exc:
                eprint(f"[error] Failed to rename {path} to {target}: {exc}")
    return renamed


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1
    if args.min_bytes < 0:
        eprint("Minimum bytes must be zero or greater.")
        return 1
    rename_zero_files(base_path, args.extension, args.dry_run, args.verbose, args.min_bytes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
