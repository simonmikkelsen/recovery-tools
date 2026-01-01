"""
This python 3 program finds all files named "hashes.txt" in the specified directory tree and combines them into
a single "combined_hashes.txt" file in the current directory.

hashes.txt has the format produced by mkhashes.py: lines of the form "<hash> <relative file path>".
combined hashes must have the same format, with relative file paths adjusted to be relative to the specified directory:
i.e. if a hashes.txt file is found at onedir/subdir/hashes.txt, and it contains a line
"abcd1234 file.txt", then the combined_hashes.txt file should contain the line
"abcd1234 onedir/subdir/file.txt".

Usage: python3 combinehashes.py <directory>
The output file combined_hashes.txt will be created in the current directory.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

HASH_FILE_NAME = "hashes.txt"
OUTPUT_FILE_NAME = "combined_hashes.txt"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine hashes.txt files into a single combined_hashes.txt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan for hashes.txt files.",
    )
    return parser.parse_args()


def normalize_relative_path(rel_path: str) -> Optional[Path]:
    cleaned = rel_path.strip().replace("\\", "/")
    if not cleaned:
        return None
    path = Path(cleaned)
    if path.is_absolute():
        return None
    if any(part == ".." for part in path.parts):
        return None
    return path


def iter_hash_files(base_path: Path) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(base_path):
        dirnames.sort()
        filenames.sort()
        if HASH_FILE_NAME in filenames:
            yield Path(root) / HASH_FILE_NAME


def iter_entries(hash_path: Path) -> Iterable[Tuple[str, Path]]:
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
                digest, rel_path = parts
                normalized = normalize_relative_path(rel_path)
                if normalized is None:
                    eprint(f"[warn] {hash_path}:{line_no}: invalid relative path: {rel_path}")
                    continue
                yield digest, normalized
    except OSError as exc:
        eprint(f"[error] Failed to read {hash_path}: {exc}")


def combine_hashes(base_path: Path, output_path: Path) -> int:
    try:
        writer = output_path.open("w", encoding="utf-8", newline="\n")
    except OSError as exc:
        eprint(f"[error] Failed to open {output_path} for writing: {exc}")
        return 1

    with writer:
        for hash_path in iter_hash_files(base_path):
            rel_dir = hash_path.parent.relative_to(base_path)
            for digest, rel_path in iter_entries(hash_path):
                combined_path = (rel_dir / rel_path).as_posix()
                writer.write(f"{digest} {combined_path}\n")
    return 0


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1
    output_path = Path.cwd() / OUTPUT_FILE_NAME
    return combine_hashes(base_path, output_path)


if __name__ == "__main__":
    sys.exit(main())
