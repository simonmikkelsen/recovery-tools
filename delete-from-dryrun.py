#!/usr/bin/env python3
"""
Make this pythong 3 script:

Given a file on the command line with this format:

[DRY RUN] /path/to the from file/928378122.html -> /path/to the to file/good file name.html

It will delete the from file, i.e. /path/to the from file/928378122.html in this example
and keep the to file, i.e. /path/to the to file/good file name.html in this example.
It will not check if the to file exists or if the files are the same, it will just delete the from file.

Usage: python3 delete-from-dryrun.py <file_with_dryrun_output> [-n|--dry-run][-h|--help]

Keep this text in the file but do not include it in the help section.

"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_line(line: str) -> Tuple[Optional[Tuple[Path, Path]], Optional[str]]:
    stripped = line.strip()
    if not stripped:
        return None, None
    if not stripped.startswith("[DRY RUN]"):
        return None, None

    payload = stripped[len("[DRY RUN]") :].strip()
    if payload.startswith("Would move"):
        payload = payload[len("Would move") :].strip()

    parts = payload.rsplit("->", 1)
    if len(parts) != 2:
        return None, "missing '->' separator"

    from_path = parts[0].strip()
    to_path = parts[1].strip()
    if not from_path or not to_path:
        return None, "missing source or target path"

    return (Path(from_path), Path(to_path)), None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete source files listed in a dry-run log.",
    )
    parser.add_argument(
        "dryrun_file",
        help="Path to file containing [DRY RUN] ... -> ... lines.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without making changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dryrun_path = Path(args.dryrun_file).expanduser()
    try:
        handle = dryrun_path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        eprint(f"[error] Unable to read {dryrun_path}: {exc}")
        return 2

    errors = 0
    with handle:
        for line_no, line in enumerate(handle, 1):
            parsed, error = parse_line(line)
            if error:
                eprint(f"[warn] Line {line_no} ignored: {error}")
                continue
            if parsed is None:
                continue

            from_path, to_path = parsed
            if args.dry_run:
                print(f"[DRY RUN] Delete: {from_path}")
                continue

            try:
                from_path.unlink()
                print(f"[DELETED] {from_path}")
            except FileNotFoundError:
                errors += 1
                eprint(f"[warn] Missing source {from_path}")
            except IsADirectoryError:
                errors += 1
                eprint(f"[warn] Source is a directory, skipping {from_path}")
            except OSError as exc:
                errors += 1
                eprint(f"[error] Failed to delete {from_path}: {exc}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
