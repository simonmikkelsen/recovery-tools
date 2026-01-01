"""
This python3 script combines the functionality of, rename-zero-files.py, mkhashes.py and mkfilesize-tables.py to the following functionality:

The script is given a directory as argument. This is the root directory to process.

- All files in the root are scanned. If a file is found to be all-zero bytes and its size is at least a specified minimum (default 8 bytes),
  it is renamed by appending a specified extension (default .damaged) to the filename. Start by reading at most 8 bytes form a file to
  determine if it is a zero file. If all bytes are zero, read the rest of the file in 1 MiB chunks to confirm it is a zero file.
- If the given file is not all zeros, then process it in the following way:
  - Add the file to a size table (filesizes.txt) in the root directory, with lines of the form
    <size in bytes> <relative file path>
  - Add the file to a hash table (hashes.txt) in the root directory, with lines of the form
    <SHA256 hash> <relative file path>

If either of the output files already exist, halt the script with an error message.

Usage: python3 total-meta-collector.py <directory> [--extension .damaged] [--min-bytes 8] [-v|--verbose] [-n|--dry-run] [-h|--help]
The script processes all files in the specified directory and its subdirectories.
The output files filesizes.txt and hashes.txt will be created in the specified directory.

Keep this text in the file but do not use it directly in the help section.

"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Iterable, Optional, TextIO, Tuple

HASH_FILE_NAME = "hashes.txt"
SIZE_FILE_NAME = "filesizes.txt"
HEAD_CHECK_BYTES = 8
TAIL_CHECK_CHUNK = 1024 * 1024
HASH_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_MIN_BYTES = 8


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename all-zero files and build hashes.txt/filesizes.txt tables."
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
        help="Show what would be renamed without writing output files.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    parser.add_argument(
        "--skip-rename",
        action="store_true",
        help="Do not rename zero files; only generate hashes/filesizes.",
    )
    parser.add_argument(
        "--truncate-damaged-files",
        action="store_true",
        help="Truncate renamed damaged files to zero bytes while preserving timestamps.",
    )
    return parser.parse_args()


def iter_files(base_path: Path) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(base_path):
        for name in filenames:
            yield Path(root) / name


def inspect_file(path: Path) -> Tuple[bool, bool, Optional[str]]:
    try:
        with path.open("rb", buffering=0) as handle:
            head = handle.read(HEAD_CHECK_BYTES)
            if head and head.count(0) != len(head):
                digest = hashlib.sha256()
                digest.update(head)
                for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
                    digest.update(chunk)
                return True, False, digest.hexdigest()

            digest = hashlib.sha256()
            digest.update(head)
            all_zero = True
            while True:
                chunk = handle.read(TAIL_CHECK_CHUNK)
                if not chunk:
                    break
                if all_zero and chunk.count(0) != len(chunk):
                    all_zero = False
                    digest.update(chunk)
                    for rest in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
                        digest.update(rest)
                    return True, False, digest.hexdigest()
                digest.update(chunk)
            return True, True, None
    except OSError as exc:
        eprint(f"[warn] Failed to read {path}: {exc}")
        return False, False, None


def write_entry(
    size: int,
    digest: str,
    rel_path: str,
    size_writer: Optional[TextIO],
    hash_writer: Optional[TextIO],
) -> None:
    if size_writer is not None:
        size_writer.write(f"{size} {rel_path}\n")
    if hash_writer is not None:
        hash_writer.write(f"{digest} {rel_path}\n")


def process_files(
    base_path: Path,
    extension: str,
    min_bytes: int,
    dry_run: bool,
    verbose: bool,
    skip_rename: bool,
    truncate_damaged_files: bool,
    size_writer: Optional[TextIO],
    hash_writer: Optional[TextIO],
) -> None:
    size_path = base_path / SIZE_FILE_NAME
    hash_path = base_path / HASH_FILE_NAME

    for path in iter_files(base_path):
        if path == size_path or path == hash_path:
            continue

        try:
            stat_info = path.stat()
        except OSError as exc:
            eprint(f"[warn] Failed to stat {path}: {exc}")
            continue
        size = stat_info.st_size

        already_tagged = bool(extension) and path.name.endswith(extension)

        ok, all_zero, digest = inspect_file(path)
        if not ok:
            continue

        if all_zero:
            if skip_rename:
                if verbose:
                    eprint(f"[info] Skipping rename for zero file {path}")
                continue
            if size >= min_bytes and not already_tagged:
                target = path.with_name(f"{path.name}{extension}")
                if target.exists():
                    eprint(f"[warn] Target exists, skipping {path}")
                    continue
                if dry_run:
                    print(f"[DRY RUN] {path} -> {target}")
                else:
                    try:
                        path.rename(target)
                        if truncate_damaged_files:
                            try:
                                with target.open("r+b") as handle:
                                    handle.truncate(0)
                                os.utime(
                                    target,
                                    ns=(stat_info.st_atime_ns, stat_info.st_mtime_ns),
                                )
                            except OSError as exc:
                                eprint(
                                    f"[error] Failed to truncate {target}: {exc}"
                                )
                        if verbose:
                            eprint(f"[info] Renamed {path} -> {target}")
                    except OSError as exc:
                        eprint(f"[error] Failed to rename {path} to {target}: {exc}")
            continue

        if digest is None:
            continue

        rel_path = path.relative_to(base_path).as_posix()
        if dry_run:
            if verbose:
                eprint(f"[info] Would record {rel_path}")
            continue
        try:
            write_entry(size, digest, rel_path, size_writer, hash_writer)
        except OSError as exc:
            eprint(f"[error] Failed to write entry for {path}: {exc}")
            continue

        if verbose:
            eprint(f"[info] Recorded {rel_path} ({size} bytes)")


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1
    if args.min_bytes < 0:
        eprint("Minimum bytes must be zero or greater.")
        return 1

    size_path = base_path / SIZE_FILE_NAME
    hash_path = base_path / HASH_FILE_NAME
    if size_path.exists() or hash_path.exists():
        if size_path.exists():
            eprint(f"[error] Output file already exists: {size_path}")
        if hash_path.exists():
            eprint(f"[error] Output file already exists: {hash_path}")
        return 1

    if args.dry_run:
        process_files(
            base_path=base_path,
            extension=args.extension,
            min_bytes=args.min_bytes,
            dry_run=True,
            verbose=args.verbose,
            skip_rename=args.skip_rename,
            truncate_damaged_files=args.truncate_damaged_files,
            size_writer=None,
            hash_writer=None,
        )
        return 0

    try:
        with size_path.open("w", encoding="utf-8", newline="\n") as size_writer, hash_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as hash_writer:
            process_files(
                base_path=base_path,
                extension=args.extension,
                min_bytes=args.min_bytes,
                dry_run=False,
                verbose=args.verbose,
                skip_rename=args.skip_rename,
                truncate_damaged_files=args.truncate_damaged_files,
                size_writer=size_writer,
                hash_writer=hash_writer,
            )
    except OSError as exc:
        eprint(f"[error] Failed to open output files: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
