#!/usr/bin/env python3
"""
This program removes duplicate files.
Usage: deduplicate.py [options] <path1> <path2> ...
Normal output to stdout:
For each deleted file print: <full path to deleted file> -> <full path to kept file>

In each input path there must exist a file caled hashes.txt
Each line of hashes.txt must contain:
    <hash> <relative path to file>
The hash could be a SHA256 hash, but the only rule is that identical files must have identical hashes.
The relative path is relative to the path where hashes.txt is located.
The program will delete duplicate files (files with the same hash) only from higher-numbered
paths (path1, path2, ... follow the command line order). If a file exists in multiple paths,
the copy in the lowest-numbered path is kept and copies in higher-numbered paths are deleted.
If a file exists only in duplicate copies within the same path number, no files are deleted.

No files in path1 may be deleted, only files in path2, path3, ...
If a file exists in path1 and path2 with the same hash, the file in path2 is deleted.
If a file exists in path2 and path3 with the same hash, the file in path3 is deleted.
If a file exists in path1, path2 and path3 with the same hash, the files in path2 and path3 are deleted.
If a file exists multiple times only in path2, those copies are never deleted.
By default, no files less than 1 KB are deleted (override with --min-bytes).
Files are only deleted when their sizes match. By default, binary equality is required:
  - Files <= 512 KB must match completely.
  - Files > 512 KB must match in the first 256 KB, middle 128 KB, and last 128 KB.
Use --naive to disable binary comparisons (size still must match).

Options:
  -h, --help      Show this help message and exit.
  -v, --verbose   Enable verbose output.
  -n, --dry-run   Perform a trial run with no changes made.
  -m, --min-bytes Minimum file size (bytes) eligible for deletion (default: 1024).
  --naive         Skip binary comparison; requires matching size only.
  --ignore-pure-zero  Skip deleting files that are entirely zero bytes.
  --print-delete  Print full paths of files that would be deleted (one per line).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

MIN_DELETE_BYTES = 1024
SMALL_COMPARE_THRESHOLD = 512 * 1024
HEAD_COMPARE_BYTES = 256 * 1024
MIDDLE_COMPARE_BYTES = 128 * 1024
TAIL_COMPARE_BYTES = 128 * 1024
FULL_COMPARE_CHUNK = 256 * 1024
ZERO_CHECK_CHUNK = 8 * 1024 * 1024

@dataclass
class HashEntry:
    digest: str
    path: Path
    base_index: int
    line_no: int


@dataclass
class DedupStats:
    examined: int = 0
    duplicates: int = 0
    deleted: int = 0
    skipped_small: int = 0
    skipped_zero: int = 0
    missing_files: int = 0
    dry_run: bool = False


def eprint(message: str) -> None:
    """Print to stderr to keep normal output clean."""
    print(message, file=sys.stderr)


def normalize_relative_path(rel_path: str) -> Path:
    """
    Normalize a relative path string to handle both '/' and '\\' separators
    across platforms.
    """
    cleaned = rel_path.strip().replace("\\", "/")
    return Path(cleaned)


def files_same_size(path_a: Path, path_b: Path) -> tuple[bool, int, int]:
    try:
        size_a = path_a.stat().st_size
    except OSError:
        return False, -1, -1
    try:
        size_b = path_b.stat().st_size
    except OSError:
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


def files_sampled_equal(path_a: Path, path_b: Path, size: int) -> bool:
    if size <= 0:
        return False
    try:
        with path_a.open("rb", buffering=0) as fa, path_b.open("rb", buffering=0) as fb:
            segments = [
                (0, min(HEAD_COMPARE_BYTES, size)),
                (
                    max((size // 2) - (MIDDLE_COMPARE_BYTES // 2), 0),
                    min(MIDDLE_COMPARE_BYTES, size),
                ),
                (max(size - TAIL_COMPARE_BYTES, 0), min(TAIL_COMPARE_BYTES, size)),
            ]
            for offset, length in segments:
                if read_segment(fa, offset, length) != read_segment(fb, offset, length):
                    return False
            return True
    except OSError as exc:
        eprint(f"[warn] Sampled compare failed for {path_a} and {path_b}: {exc}")
        return False


def files_equivalent(
    path_a: Path, path_b: Path, size: int, naive: bool
) -> bool:
    if naive:
        return True
    if size <= SMALL_COMPARE_THRESHOLD:
        return files_binary_equal(path_a, path_b, chunk_size=max(size, 1))
    return files_sampled_equal(path_a, path_b, size)


def file_is_pure_zero(path: Path, size: int) -> bool:
    if size <= 0:
        return True
    head_size = min(size, HEAD_COMPARE_BYTES)
    try:
        with path.open("rb", buffering=0) as handle:
            head = handle.read(head_size)
            if head.count(0) != len(head):
                return False
            if size <= head_size:
                return True
            while True:
                chunk = handle.read(ZERO_CHECK_CHUNK)
                if not chunk:
                    return True
                if chunk.count(0) != len(chunk):
                    return False
    except OSError as exc:
        eprint(f"[warn] Failed to read {path} for zero check: {exc}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove duplicate files using hashes listed in hashes.txt manifests, keeping the lowest-numbered path.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Directories (path1 path2 ...) each containing hashes.txt.",
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
        dest="dry_run",
        action="store_true",
        help="Perform a trial run with no changes made.",
    )
    parser.add_argument(
        "-m",
        "--min-bytes",
        type=int,
        default=MIN_DELETE_BYTES,
        help="Minimum file size (bytes) eligible for deletion (default: 1024).",
    )
    parser.add_argument(
        "--naive",
        action="store_true",
        help="Do not perform binary comparisons; require only matching size for deletion.",
    )
    parser.add_argument(
        "--ignore-pure-zero",
        action="store_true",
        help="Skip deleting files that are entirely zero bytes.",
    )
    parser.add_argument(
        "--print-delete",
        action="store_true",
        help="Print full paths of files that would be deleted (one per line).",
    )
    return parser.parse_args()


def validate_paths(raw_paths: List[str]) -> List[Path]:
    base_paths: List[Path] = []
    for raw in raw_paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            eprint(f"Input path is not a directory: {path}")
            sys.exit(1)
        hash_file = path / "hashes.txt"
        if not hash_file.is_file():
            eprint(f"Missing hashes.txt in {path}")
            sys.exit(1)
        base_paths.append(path)
    return base_paths


def iter_hash_entries(base_path: Path, base_index: int) -> Iterable[HashEntry]:
    hash_file = base_path / "hashes.txt"
    with hash_file.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(maxsplit=1)
            if len(parts) != 2:
                eprint(f"[warn] {hash_file}:{line_no}: expected '<hash> <relative path>'")
                continue
            digest, rel_path = parts
            if not rel_path:
                eprint(f"[warn] {hash_file}:{line_no}: relative path missing")
                continue
            normalized_rel = normalize_relative_path(rel_path)
            if normalized_rel.is_absolute():
                eprint(f"[warn] {hash_file}:{line_no}: relative path is absolute: {rel_path}")
                continue
            file_path = (base_path / normalized_rel).resolve()
            yield HashEntry(digest=digest, path=file_path, base_index=base_index, line_no=line_no)


def deduplicate_paths(
    base_paths: List[Path],
    dry_run: bool,
    verbose: bool,
    min_delete_bytes: int,
    naive: bool,
    ignore_pure_zero: bool,
    print_delete: bool,
) -> DedupStats:
    kept: Dict[str, HashEntry] = {}
    stats = DedupStats(dry_run=dry_run)

    def note_missing(entry: HashEntry) -> None:
        stats.missing_files += 1
        if verbose:
            eprint(f"[warn] File listed but missing: {entry.path}")

    def try_delete(entry: HashEntry, keeper: HashEntry) -> None:
        if entry.path == keeper.path:
            if verbose:
                eprint(f"[info] Duplicate hash entry for same file skipped: {entry.path}")
            return

        stats.duplicates += 1

        if not entry.path.exists():
            note_missing(entry)
            return
        if not keeper.path.exists():
            stats.missing_files += 1
            if verbose:
                eprint(
                    f"[warn] Kept file missing ({keeper.path}); skipping delete of {entry.path}."
                )
            return

        try:
            size_entry = entry.path.stat().st_size
        except OSError as exc:
            stats.missing_files += 1
            eprint(f"[warn] Could not stat {entry.path}: {exc}")
            return

        if size_entry < min_delete_bytes:
            stats.skipped_small += 1
            if verbose:
                eprint(
                    f"[info] Skipping {entry.path} ({size_entry} bytes) under {min_delete_bytes} bytes."
                )
            return
        if ignore_pure_zero and file_is_pure_zero(entry.path, size_entry):
            stats.skipped_zero += 1
            if verbose:
                eprint(f"[info] Skipping all-zero file {entry.path}.")
            return

        sizes_equal, size_a, size_b = files_same_size(entry.path, keeper.path)
        if not sizes_equal:
            if verbose:
                eprint(
                    f"[info] Skip delete; size differs {entry.path} ({size_a}) vs {keeper.path} ({size_b})."
                )
            return

        if not files_equivalent(entry.path, keeper.path, size_a, naive):
            if verbose:
                eprint(
                    f"[info] Skip delete; content differs between {entry.path} and {keeper.path}."
                )
            return

        if print_delete:
            print(f"{entry.path}")
            stats.deleted += 1
            return

        if dry_run:
            print(f"[DRY RUN] {entry.path} -> {keeper.path}")
            return

        try:
            entry.path.unlink()
            stats.deleted += 1
            print(f"{entry.path} -> {keeper.path}")
        except OSError as exc:
            eprint(f"[error] Failed to delete {entry.path}: {exc}")

    for base_index, base_path in enumerate(base_paths):
        for entry in iter_hash_entries(base_path, base_index):
            stats.examined += 1

            kept_entry = kept.get(entry.digest)
            if kept_entry is None:
                if not entry.path.exists():
                    note_missing(entry)
                    continue
                kept[entry.digest] = entry
                continue

            if not kept_entry.path.exists():
                if not entry.path.exists():
                    note_missing(entry)
                    continue
                if verbose:
                    eprint(
                        f"[warn] Kept file missing ({kept_entry.path}); keeping {entry.path} instead."
                    )
                kept[entry.digest] = entry
                continue

            if not entry.path.exists():
                note_missing(entry)
                continue

            if entry.base_index == kept_entry.base_index:
                if entry.path == kept_entry.path and verbose:
                    eprint(f"[info] Duplicate hash entry for same file skipped: {entry.path}")
                continue

            if entry.base_index < kept_entry.base_index:
                kept[entry.digest] = entry
                continue

            try_delete(entry, kept_entry)

    return stats


def main() -> int:
    args = parse_args()
    if args.min_bytes < 0:
        eprint("Minimum delete bytes must be zero or greater.")
        return 1
    base_paths = validate_paths(args.paths)
    stats = deduplicate_paths(
        base_paths,
        args.dry_run,
        args.verbose,
        args.min_bytes,
        args.naive,
        args.ignore_pure_zero,
        args.print_delete,
    )

    if args.verbose:
        deleted_label = "deleted"
        if args.print_delete:
            deleted_label = "printed"
        summary = (
            f"Examined {stats.examined} entries; duplicates found {stats.duplicates}; "
            f"{deleted_label} {stats.deleted}; skipped under {args.min_bytes} bytes {stats.skipped_small}; "
            f"skipped all-zero {stats.skipped_zero}; missing/stat failures {stats.missing_files}."
        )
        if stats.dry_run:
            summary += " Dry run: no files deleted."
        if args.print_delete:
            summary += " Print-delete: no files deleted."
        eprint(f"[summary] {summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
