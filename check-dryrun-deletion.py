#!/usr/bin/env python3
"""
Make this pythong 3 script:

Given a file on the command line with this format:

[DRY RUN] /path/to the from file/928378122.html -> /path/to the to file/good file name.html

It will check that the 2 files have the same contents and print if they do not.
Files larger than 512 KB should only have their sizes compared as well as blocks of 32 KB at the start, middle, 10 sports from across the file and end.
Make an option to test only every Nth file.
Verbose mode should print all files compared and their status.

Usage: python3 check-dryrun-deletion.py <file_with_dryrun_output> [--test-every N][-v|--verbose][-h|--help]

Keep this text in the file but do not include it in the help section.

"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

SMALL_COMPARE_THRESHOLD = 512 * 1024
SAMPLE_BLOCK_BYTES = 32 * 1024
SAMPLE_SPOTS = 10
FULL_COMPARE_CHUNK = 256 * 1024


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

    left, sep, right = payload.partition("->")
    if not sep:
        return None, "missing '->' separator"

    from_path = left.strip()
    to_path = right.strip()
    if not from_path or not to_path:
        return None, "missing source or target path"

    return (Path(from_path), Path(to_path)), None


def files_same_size(path_a: Path, path_b: Path) -> Tuple[bool, int, int]:
    try:
        size_a = path_a.stat().st_size
    except OSError as exc:
        eprint(f"[warn] Could not stat {path_a}: {exc}")
        return False, -1, -1
    try:
        size_b = path_b.stat().st_size
    except OSError as exc:
        eprint(f"[warn] Could not stat {path_b}: {exc}")
        return False, size_a, -1
    return size_a == size_b, size_a, size_b


def files_binary_equal(path_a: Path, path_b: Path, chunk_size: int = FULL_COMPARE_CHUNK) -> bool:
    try:
        with path_a.open("rb", buffering=0) as fa, path_b.open("rb", buffering=0) as fb:
            while True:
                chunk_a = fa.read(chunk_size)
                chunk_b = fb.read(chunk_size)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True
    except OSError as exc:
        eprint(f"[warn] Binary compare failed for {path_a} and {path_b}: {exc}")
        return False


def read_segment(fp, offset: int, length: int) -> bytes:
    fp.seek(max(offset, 0))
    return fp.read(max(length, 0))


def sampled_offsets(size: int, block_size: int, spots: int) -> Iterable[int]:
    max_offset = max(size - block_size, 0)
    seen = set()

    def add(offset: int) -> None:
        bounded = min(max(offset, 0), max_offset)
        if bounded in seen:
            return
        seen.add(bounded)
        offsets.append(bounded)

    offsets: list[int] = []
    add(0)

    middle = max((size // 2) - (block_size // 2), 0)
    add(middle)

    if spots > 0 and max_offset > 0:
        for i in range(1, spots + 1):
            offset = int(round(i * max_offset / (spots + 1)))
            add(offset)

    add(max_offset)
    return offsets


def files_sampled_equal(path_a: Path, path_b: Path, size: int) -> bool:
    if size <= 0:
        return False
    try:
        with path_a.open("rb", buffering=0) as fa, path_b.open("rb", buffering=0) as fb:
            for offset in sampled_offsets(size, SAMPLE_BLOCK_BYTES, SAMPLE_SPOTS):
                length = min(SAMPLE_BLOCK_BYTES, max(size - offset, 0))
                if length <= 0:
                    continue
                if read_segment(fa, offset, length) != read_segment(fb, offset, length):
                    return False
            return True
    except OSError as exc:
        eprint(f"[warn] Sampled compare failed for {path_a} and {path_b}: {exc}")
        return False


def files_equivalent(path_a: Path, path_b: Path, size: int) -> Tuple[bool, str]:
    if size <= SMALL_COMPARE_THRESHOLD:
        if files_binary_equal(path_a, path_b, chunk_size=max(1, size)):
            return True, "match"
        return False, "content differs"

    if files_sampled_equal(path_a, path_b, size):
        return True, "match"
    return False, "content differs (sampled)"


def compare_paths(path_a: Path, path_b: Path) -> Tuple[bool, str]:
    if not path_a.exists():
        return False, "missing source"
    if not path_b.exists():
        return False, "missing target"

    sizes_equal, size_a, size_b = files_same_size(path_a, path_b)
    if not sizes_equal:
        return False, f"size differs ({size_a} vs {size_b})"

    return files_equivalent(path_a, path_b, size_a)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that dry-run deletion pairs point to identical files.",
    )
    parser.add_argument(
        "dryrun_file",
        help="Path to file containing [DRY RUN] ... -> ... lines.",
    )
    parser.add_argument(
        "--test-every",
        type=int,
        default=1,
        help="Only test every Nth entry (default: 1).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.test_every < 1:
        eprint("[error] --test-every must be >= 1.")
        return 2

    dryrun_path = Path(args.dryrun_file)
    try:
        handle = dryrun_path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        eprint(f"[error] Unable to read {dryrun_path}: {exc}")
        return 2

    compared = 0
    mismatches = 0
    entries = 0

    with handle:
        for line_no, line in enumerate(handle, 1):
            parsed, error = parse_line(line)
            if error:
                eprint(f"[warn] Line {line_no} ignored: {error}")
                continue
            if parsed is None:
                continue

            entries += 1
            if args.test_every > 1 and (entries - 1) % args.test_every != 0:
                if args.verbose:
                    from_path, to_path = parsed
                    print(f"[SKIP] {from_path} -> {to_path}")
                continue

            from_path, to_path = parsed
            compared += 1
            matches, reason = compare_paths(from_path, to_path)
            if matches:
                if args.verbose:
                    print(f"[OK] {from_path} -> {to_path}")
            else:
                mismatches += 1
                print(f"[DIFF] {from_path} -> {to_path} ({reason})")

    if args.verbose:
        eprint(f"[info] Entries: {entries}, compared: {compared}, mismatches: {mismatches}.")

    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
