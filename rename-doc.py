#!/usr/bin/env python3
"""
Rename recovered .doc files using internal creation/modification timestamps.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple
import re

import olefile
from dateutil import parser as date_parser
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser

# Matches names like f1622085904_musik.doc -> postfix "musik"
POSTFIX_REGEX = re.compile(r"^[A-Za-z]+[0-9]+_(.+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename recovered .doc files using internal timestamps."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=".",
        help="Directory to scan for .doc files (default: current directory).",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Directory to move renamed files into (default: rename in place).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print actions performed.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not make any changes.",
    )
    return parser.parse_args()


def configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("rename_doc")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def iter_doc_files(input_dir: Path, output_dir: Optional[Path]) -> Iterable[Path]:
    for path in input_dir.rglob("*"):
        if not path.is_file():
            continue
        if output_dir and output_dir in path.parents:
            continue
        if path.suffix.lower() == ".doc":
            yield path


def extract_postfix(path: Path) -> str:
    name = path.stem
    match = POSTFIX_REGEX.match(name)
    if match:
        return match.group(1)
    return ""


def valid_datetime(dt: Optional[datetime]) -> bool:
    if not isinstance(dt, datetime):
        return False
    current_year = datetime.now().year
    return 1900 <= dt.year <= current_year + 1


def extract_timestamp_with_olefile(path: Path, logger: logging.Logger) -> tuple[Optional[datetime], Optional[dict], bool]:
    try:
        with olefile.OleFileIO(str(path)) as ole:
            metadata = ole.get_metadata()
            meta_dict = metadata_to_dict(metadata)
            candidates = [
                metadata.create_time,
                metadata.last_saved_time,
                metadata.modification_time,
            ]
    except Exception as exc:
        logger.error("Failed to read metadata for %s: %s", path, exc)
        return None, None, False

    found_any = bool(meta_dict)

    for dt in candidates:
        if valid_datetime(dt):
            return dt, meta_dict, True
    if found_any:
        return None, meta_dict, True
    return None, None, False


def extract_timestamp_with_hachoir(path: Path, logger: logging.Logger) -> tuple[Optional[datetime], Optional[dict], bool]:
    try:
        parser = createParser(str(path))
    except Exception as exc:
        logger.error("Failed to create parser for %s: %s", path, exc)
        return None, None, False

    if not parser:
        return None, None, False

    try:
        with parser:
            metadata = extractMetadata(parser)
    except Exception as exc:
        logger.error("Failed to extract metadata with hachoir for %s: %s", path, exc)
        return None, None, False

    if not metadata:
        return None, None, False

    meta_dict = {}
    dt_candidate = None
    try:
        for line in metadata.exportPlaintext() or []:
            clean_line = line[2:] if line.startswith("- ") else line
            key, _, value = clean_line.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                meta_dict[key] = value
    except Exception:
        pass

    for key in (
        "Creation date",
        "CreationDate",
        "Create Date",
        "Last Saved",
        "Last modification",
        "Modification date",
    ):
        value = meta_dict.get(key)
        if not value:
            continue
        try:
            dt_candidate = date_parser.parse(value)
            break
        except Exception:
            continue

    found_any = bool(meta_dict)

    if dt_candidate and dt_candidate.tzinfo:
        dt_candidate = dt_candidate.astimezone()

    if dt_candidate:
        return dt_candidate, meta_dict or None, True
    if found_any:
        return None, meta_dict or None, True
    return None, None, False


def extract_timestamp(path: Path, logger: logging.Logger) -> Tuple[Optional[datetime], Optional[dict], bool]:
    dt, meta, found = extract_timestamp_with_olefile(path, logger)
    if found:
        return dt, meta, found

    return extract_timestamp_with_hachoir(path, logger)


def metadata_to_dict(metadata: Optional[olefile.OleMetadata]) -> dict:
    if metadata is None:
        return {}
    if hasattr(metadata, "__dict__") and metadata.__dict__:
        return {k: v for k, v in metadata.__dict__.items() if not k.startswith("_")}

    collected = {}
    for attr in dir(metadata):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(metadata, attr)
        except Exception:
            continue
        if callable(value):
            continue
        collected[attr] = value
    return collected


def build_target_path(
    source: Path, dt: datetime, postfix: str, output_dir: Optional[Path]
) -> Path:
    base = dt.strftime("%Y-%m-%d_%H-%M-%S")
    if postfix:
        base = f"{base}_{postfix}"
    ext = source.suffix or ".doc"
    if output_dir:
        target_dir = output_dir / f"{dt.year:04d}"
    else:
        target_dir = source.parent
    return target_dir / f"{base}{ext}"


def process_file(
    path: Path,
    logger: logging.Logger,
    output_dir: Optional[Path],
    verbose: bool,
    dry_run: bool,
) -> bool:
    dt, metadata, _ = extract_timestamp(path, logger)
    if not dt:
        if metadata:
            print(f"{path}: {metadata}\n")
        else:
            print(f"{path}: No metadata found\n")
        return False

    postfix = extract_postfix(path)
    target_path = build_target_path(path, dt, postfix, output_dir)

    if target_path.exists():
        logger.error("Target already exists for %s -> %s", path, target_path)
        return False

    if dry_run:
        if verbose:
            print(f"[DRY RUN] Would move {path} -> {target_path}")
        return True

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target_path)
        if verbose:
            print(f"Moved {path} -> {target_path}")
        return True
    except Exception as exc:
        logger.error("Failed to move %s -> %s: %s", path, target_path, exc)
        return False


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Input directory does not exist or is not a directory: {input_dir}", file=sys.stderr)
        return 1

    if output_dir and not args.dry_run:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"Failed to create output directory {output_dir}: {exc}", file=sys.stderr)
            return 1

    log_dir: Path
    if args.dry_run:
        log_dir = output_dir if output_dir and output_dir.exists() else Path(".").resolve()
    else:
        log_dir = output_dir if output_dir else Path(".").resolve()
    log_path = log_dir / "rename-doc-errors.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logger(log_path)

    files = list(iter_doc_files(input_dir, output_dir))
    if not files and args.verbose:
        print("No .doc files found to process.")

    processed = 0
    renamed = 0
    for file_path in files:
        processed += 1
        if process_file(file_path, logger, output_dir, args.verbose, args.dry_run):
            renamed += 1

    if args.verbose:
        action = "would be renamed" if args.dry_run else "renamed"
        print(f"{renamed} of {processed} files {action}. Errors logged to {log_path}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
