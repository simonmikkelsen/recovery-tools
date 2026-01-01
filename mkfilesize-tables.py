"""
This python3 script finds all files in the specified directory tree and creates size tables for them.
A size table is a text file named "filesizes.txt" which contains lines of the form
<size in bytes> <relative file path>
for each file found in the directory tree, including files in subdirectories and hidden files.
The relative file path is relative to the specified base directory. The output file "filesizes.txt" is created in the specified base directory.

Make a help section, verbose, dry-run options and output file option.
Usage: python3 mkfilesize-tables.py <directory> [-v|--verbose] [-n|--dry-run][-o|--output <output file>]

Keep this text in the file but do not use it directly in the help section.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional, TextIO

DEFAULT_OUTPUT_NAME = "filesizes.txt"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a filesizes.txt table for a directory tree."
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose progress updates.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print output to stdout without writing a file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: <base>/filesizes.txt).",
    )
    return parser.parse_args()


def resolve_output_path(base_path: Path, output_arg: Optional[str]) -> Path:
    if not output_arg:
        return base_path / DEFAULT_OUTPUT_NAME
    output_path = Path(output_arg).expanduser()
    if output_path.is_absolute():
        return output_path.resolve()
    return (base_path / output_path).resolve()


def iter_files(base_path: Path) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(base_path):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            yield Path(root) / name


def write_sizes(
    base_path: Path,
    output_path: Path,
    writer: Optional[TextIO],
    verbose: bool,
) -> None:
    output_rel: Optional[Path] = None
    try:
        output_rel = output_path.relative_to(base_path)
    except ValueError:
        output_rel = None

    for file_path in iter_files(base_path):
        if output_rel is not None:
            try:
                if file_path.relative_to(base_path) == output_rel:
                    continue
            except ValueError:
                pass

        try:
            size = file_path.stat().st_size
        except OSError as exc:
            eprint(f"[warn] Failed to stat {file_path}: {exc}")
            continue

        rel_path = file_path.relative_to(base_path).as_posix()
        line = f"{size} {rel_path}\n"

        if writer is None:
            print(line, end="")
        else:
            try:
                writer.write(line)
            except OSError as exc:
                eprint(f"[error] Failed to write entry for {file_path}: {exc}")
                continue

        if verbose:
            eprint(f"[info] Recorded {rel_path} ({size} bytes)")


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1

    output_path = resolve_output_path(base_path, args.output)
    if output_path.exists() and not output_path.is_file():
        eprint(f"[error] Expected file at {output_path}, found non-file.")
        return 1

    if args.dry_run:
        if args.verbose:
            eprint(f"[info] Dry run: would write to {output_path}")
        write_sizes(base_path, output_path, None, args.verbose)
        return 0

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="\n") as writer:
            write_sizes(base_path, output_path, writer, args.verbose)
    except OSError as exc:
        eprint(f"[error] Failed to write {output_path}: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
