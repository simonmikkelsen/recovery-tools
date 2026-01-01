#replace-damaged-files-2.py: A version of the 1st that actually works.
"""
Make a python3 script that takes a folder and a number of files we here call filesizes.txt.

filesizes.txt has the format <filesize in bytes> <relative path>

When the script loads, it must create a single mapping from the different file sizes from the given filesizes.txt files to sets of relative paths.

After load the script must look at alle files named *.damaged (or other specified extension) in the given folder tree.

If a .damaged file has a size that matches a file size in the mapping, the script must rename the .damaged file to remove the .damaged extension,
given that the file extension (after removing .damaged) matches the original file extension from filesizes.txt. Also accept file extensions that
are known equivalents, e.g. .jpg and .jpeg, see the table and examples later in this docstring.

Make a help section, verbose, dry-run options and extension option.
Usage: python3 replace-damaged-files.py <directory> <filesizes.txt ...> [--extension .damaged] [-v|--verbose] [-n|--dry-run]
The script processes all files in the specified directory and its subdirectories.

In verbose mode print to stdout and print: All files where size matched but extension did not match, and all files that were renamed.

Only replace files with the same extension, when the .damaged extension is removed. Note that some files may have multiple valid extensions.
E.g.:
  - damaged file: /path/to/file.txt.damaged, original file: /path/to/file.txt, action: Replace
  - damaged file: /path/to/file.txt.damaged, original file: /path/to/file.doc, action: No action
  - damaged file: /path/to/file.jpg.damaged, original file: /path/to/file.jpeg, action: Replace (note the jpg vs jpeg extensions)
Known equivalent extensions for the same format:
  - JPEG: .jpg, .jpeg, .jpe, .jfif
  - TIFF: .tif, .tiff
  - JPEG 2000: .jp2, .j2k, .jpf, .jpx, .jpm
  - HTML: .htm, .html
  - YAML: .yml, .yaml
  - MIDI: .mid, .midi
  - AIFF: .aif, .aiff, .aifc
  - WAV: .wav, .wave
  - MPEG video: .mpg, .mpeg, .mpe
  - MP4 video: .mp4, .m4v
  - QuickTime video: .mov, .qt


Keep this text in the file but do not use it directly in the help section.

"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


EQUIVALENT_EXTENSION_GROUPS: Tuple[Tuple[str, ...], ...] = (
    (".jpg", ".jpeg", ".jpe", ".jfif"),
    (".tif", ".tiff"),
    (".jp2", ".j2k", ".jpf", ".jpx", ".jpm"),
    (".htm", ".html"),
    (".yml", ".yaml"),
    (".mid", ".midi"),
    (".aif", ".aiff", ".aifc"),
    (".wav", ".wave"),
    (".mpg", ".mpeg", ".mpe"),
    (".mp4", ".m4v"),
    (".mov", ".qt"),
)
EXTENSION_EQUIVALENTS: Dict[str, Tuple[str, ...]] = {
    ext: group for group in EQUIVALENT_EXTENSION_GROUPS for ext in group
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace *.damaged files based on size tables and extension matching."
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan for damaged files.",
    )
    parser.add_argument(
        "filesizes",
        nargs="+",
        help="One or more filesizes.txt files containing '<size> <relative path>' entries.",
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
        help="Print size/extension mismatches and renames.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing files.",
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


def load_size_mapping(table_paths: Iterable[Path]) -> Dict[int, Set[Path]]:
    mapping: Dict[int, Set[Path]] = {}
    for table_path in table_paths:
        try:
            with table_path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    parts = stripped.split(maxsplit=1)
                    if len(parts) != 2:
                        eprint(
                            f"[warn] {table_path}:{line_no}: expected '<size> <relative path>'"
                        )
                        continue
                    size_text, rel_path = parts
                    try:
                        size = int(size_text)
                    except ValueError:
                        eprint(f"[warn] {table_path}:{line_no}: invalid size '{size_text}'")
                        continue
                    normalized = normalize_relative_path(rel_path)
                    if normalized is None:
                        eprint(f"[warn] {table_path}:{line_no}: invalid relative path: {rel_path}")
                        continue
                    candidate_path = table_path.parent / normalized
                    mapping.setdefault(size, set()).add(candidate_path)
        except OSError as exc:
            eprint(f"[error] Failed to read {table_path}: {exc}")
    return mapping


def iter_damaged_files(base_path: Path, extension: str) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(base_path):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            if extension and not name.endswith(extension):
                continue
            yield Path(root) / name


def remove_extension(path: Path, extension: str) -> Path:
    if extension and path.name.endswith(extension):
        return path.with_name(path.name[: -len(extension)])
    return path


def equivalent_extensions(extension: str) -> Set[str]:
    if not extension:
        return {""}
    ext_lower = extension.lower()
    group = EXTENSION_EQUIVALENTS.get(ext_lower)
    if not group:
        return {ext_lower}
    return set(group)


def extensions_compatible(ext_a: str, ext_b: str) -> bool:
    return ext_b.lower() in equivalent_extensions(ext_a)


def process_damaged_files(
    base_path: Path,
    size_mapping: Dict[int, Set[Path]],
    extension: str,
    dry_run: bool,
    verbose: bool,
) -> int:
    replaced = 0
    for damaged_path in iter_damaged_files(base_path, extension):
        try:
            damaged_size = damaged_path.stat().st_size
        except OSError as exc:
            eprint(f"[warn] Failed to stat {damaged_path}: {exc}")
            continue

        candidates = size_mapping.get(damaged_size)
        if not candidates:
            continue

        target_path = remove_extension(damaged_path, extension)
        target_ext = target_path.suffix.lower()
        matched_extension = False
        matched_candidate = None
        matched_candidates = [] if dry_run else None

        for candidate in candidates:
            candidate_path = candidate
            if not extensions_compatible(target_ext, candidate_path.suffix.lower()):
                continue
            matched_extension = True
            if dry_run:
                matched_candidates.append(candidate_path)
                continue
            matched_candidate = candidate_path
            break

        if not matched_extension:
            if verbose:
                print(f"[info] Size match but extension mismatch: {damaged_path} (matched candidate: {matched_candidate})")
            continue

        if dry_run:
            print()
            print(f"DAM: {damaged_path}")
            for candidate_path in matched_candidates:
                if not candidate_path.exists():
                    continue
                print(f"CAN: {candidate_path}")
            replaced += 1
            continue

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(matched_candidate, damaged_path)
            damaged_path.replace(target_path)
            replaced += 1
            if verbose:
                print(f"[info] Replaced {damaged_path} -> {target_path}")
        except OSError as exc:
            eprint(f"[error] Failed to replace {target_path} using {damaged_path}: {exc}")

    return replaced


def main() -> int:
    args = parse_args()
    base_path = Path(args.directory).expanduser().resolve()
    if not base_path.is_dir():
        eprint(f"Base path is not a directory: {base_path}")
        return 1

    table_paths = [Path(p).expanduser().resolve() for p in args.filesizes]
    for table_path in table_paths:
        if not table_path.is_file():
            eprint(f"filesizes.txt not found: {table_path}")
            return 1

    size_mapping = load_size_mapping(table_paths)
    if not size_mapping:
        eprint("[warn] Size mapping is empty or invalid; nothing to do.")
        return 0

    process_damaged_files(
        base_path=base_path,
        size_mapping=size_mapping,
        extension=args.extension,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
