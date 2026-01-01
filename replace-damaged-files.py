"""
Python3 script that takes a folder and a filesizes.txt file as argument.
filesizes.txt has the format <filesize in bytes> <relative path>

The script finds all files in the folder tree named *.damaged (or other specified extension).
If the file size matches the size of a file in filesizes.txt, the file is renamed to remove the .damaged extension and
the contents of the file in .damaged file is used to replace the contents of the original file.

Make a help section, verbose, dry-run options and extension option.
Usage: python3 replace-damaged-files.py <directory> <filesizes.txt ...> [--extension .damaged] [-v|--verbose] [-n|--dry-run]
The script processes all files in the specified directory and its subdirectories.

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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


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
        description="Replace original files using *.damaged content based on filesizes tables."
    )
    parser.add_argument(
        "directory",
        help="Base directory to scan for damaged files and originals.",
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
        help="Enable verbose output.",
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


def load_size_table(table_path: Path) -> Dict[Path, int]:
    sizes: Dict[Path, int] = {}
    try:
        with table_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split(maxsplit=1)
                if len(parts) != 2:
                    eprint(f"[warn] {table_path}:{line_no}: expected '<size> <relative path>'")
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
                if normalized in sizes and sizes[normalized] != size:
                    eprint(
                        f"[warn] {table_path}:{line_no}: conflicting sizes for {normalized}"
                    )
                sizes[normalized] = size
    except OSError as exc:
        eprint(f"[error] Failed to read {table_path}: {exc}")
    return sizes


@dataclass
class SizeTable:
    path: Path
    base_dir: Path
    sizes: Dict[Path, int]


def equivalent_extensions(extension: str) -> List[str]:
    if not extension:
        return [""]
    ext_lower = extension.lower()
    group = EXTENSION_EQUIVALENTS.get(ext_lower)
    if not group:
        return [ext_lower]
    if group[0] == ext_lower:
        return list(group)
    return [ext_lower] + [item for item in group if item != ext_lower]


def candidate_relative_paths(rel_path: Path) -> List[Path]:
    suffix = rel_path.suffix
    suffix_lower = suffix.lower()
    variants = equivalent_extensions(suffix_lower)
    candidates: List[Path] = []
    seen: set[Path] = set()

    for variant in variants:
        if variant == suffix_lower:
            candidate = rel_path
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
            if suffix != variant:
                candidate = rel_path.with_suffix(variant)
                if candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)
            continue
        candidate = rel_path.with_suffix(variant)
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


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


def process_damaged_files(
    base_path: Path,
    size_tables: List[SizeTable],
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

        target_path = remove_extension(damaged_path, extension)
        matched = False
        for table in size_tables:
            try:
                rel_target = target_path.relative_to(table.base_dir)
            except ValueError:
                continue

            for candidate in candidate_relative_paths(rel_target):
                expected_size = table.sizes.get(candidate)
                if expected_size is None:
                    continue
                if expected_size != damaged_size:
                    if verbose:
                        eprint(
                            f"[info] Size mismatch for {damaged_path} in {table.path}: "
                            f"expected {expected_size}, found {damaged_size}"
                        )
                    continue
                target_path = table.base_dir / candidate
                matched = True
                break
            if not matched:
                continue

            matched = True
            if dry_run:
                print(f"[DRY RUN] {damaged_path} -> {target_path}")
                replaced += 1
                break

            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                damaged_path.replace(target_path)
                replaced += 1
                if verbose:
                    eprint(f"[info] Replaced {target_path} using {damaged_path}")
            except OSError as exc:
                eprint(f"[error] Failed to replace {target_path} using {damaged_path}: {exc}")
            break

        if not matched and verbose:
            eprint(f"[info] No size table match for {damaged_path}")
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

    size_tables: List[SizeTable] = []
    for table_path in table_paths:
        sizes = load_size_table(table_path)
        if not sizes:
            eprint(f"[warn] Size table is empty or invalid: {table_path}")
            continue
        size_tables.append(
            SizeTable(path=table_path, base_dir=table_path.parent, sizes=sizes)
        )

    if not size_tables:
        eprint("[warn] No valid size tables loaded; nothing to do.")
        return 0

    process_damaged_files(
        base_path=base_path,
        size_tables=size_tables,
        extension=args.extension,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
