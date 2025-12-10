#!/usr/bin/env python3
"""
Rename recovered images and videos based on creation timestamps read with exiftool.

Usage:
  python rename-images.py [input_dir] [output_dir] [-v] [-n]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
import re

import exiftool
from dateutil import parser as date_parser

# Prefer metadata over extensions, but fall back to these when needed.
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".png",
    ".gif",
    ".bmp",
    ".heic",
    ".heif",
    ".webp",
    ".psd",
    ".dng",
    ".raf",
    ".arw",
    ".cr2",
    ".cr3",
    ".nef",
    ".orf",
    ".rw2",
    ".pef",
    ".sr2",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".wmv",
    ".mkv",
    ".mts",
    ".m2ts",
    ".3gp",
    ".mpg",
    ".mpeg",
    ".mod",
    ".mts",
}

# Tags are ordered by preference.
DATETIME_TAGS = [
    "EXIF:DateTimeOriginal",
    "EXIF:CreateDate",
    "XMP:CreateDate",
    "QuickTime:CreateDate",
    "QuickTime:TrackCreateDate",
    "QuickTime:ContentCreateDate",
    "Composite:SubSecCreateDate",
    "Composite:SubSecDateTimeOriginal",
    "Composite:MediaCreateDate",
    "IPTC:DateTimeCreated",
    "EXIF:GPSDateTime",
    "Composite:GPSDateTime",
]

EXIF_DATE_PREFIX = re.compile(r"^(\d{4}):(\d{2}):(\d{2})")
SPACE_PADDED_REGEX = re.compile(
    r"^(\d{4})[-:]?\s?(\d{1,2})[-:]?\s?(\d{1,2})\s+(\d{1,2}):\s?(\d{1,2}):\s?(\d{1,2})(.*)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename images/videos using EXIF creation timestamps."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=".",
        help="Directory to scan for media files (default: current directory).",
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
    logger = logging.getLogger("recovery_tools")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def iter_files(input_dir: Path, output_dir: Optional[Path]) -> Iterable[Path]:
    for path in input_dir.rglob("*"):
        if not path.is_file():
            continue
        if output_dir and output_dir in path.parents:
            # Avoid re-processing files already in the output directory.
            continue
        yield path


def normalize_timestamp(raw_value: object) -> Optional[str]:
    if raw_value is None:
        return None
    if isinstance(raw_value, (list, tuple)):
        raw_value = raw_value[0]
    text = str(raw_value).strip()
    if not text:
        return None
    if "0000:00:00 00:00:00" in text:
        return None

    match = SPACE_PADDED_REGEX.match(text)
    if match:
        return (
            f"{match.group(1)}:{match.group(2).zfill(2)}:{match.group(3).zfill(2)} "
            f"{match.group(4).zfill(2)}:{match.group(5).zfill(2)}:{match.group(6).zfill(2)}{match.group(7)}"
        )
    return text


def parse_datetime(metadata: dict) -> Optional[datetime]:
    for tag in DATETIME_TAGS:
        cleaned = normalize_timestamp(metadata.get(tag))
        if not cleaned:
            continue
        cleaned = cleaned.split(".")[0]
        cleaned = EXIF_DATE_PREFIX.sub(r"\1-\2-\3", cleaned)
        try:
            dt = date_parser.parse(cleaned)
        except (ValueError, TypeError, OverflowError):
            continue
        if dt.year < 1900 or dt.year > datetime.now().year + 1:
            continue
        if dt.tzinfo:
            dt = dt.astimezone()
        return dt
    return None


def is_video(metadata: dict, path: Path) -> bool:
    mime = metadata.get("File:MIMEType")
    if isinstance(mime, str) and mime.lower().startswith("video/"):
        return True
    if isinstance(mime, str) and mime.lower().startswith("image/"):
        return False
    file_type = metadata.get("File:FileType")
    if isinstance(file_type, str):
        lowered = file_type.lower()
        if lowered in {"mov", "mp4", "avi", "mkv", "wmv", "mpeg", "mpg", "mts"}:
            return True
        if lowered in {"jpeg", "png", "tiff", "heic", "heif", "gif", "bmp", "webp"}:
            return False
    ext = path.suffix.lower()
    return ext in VIDEO_EXTENSIONS


def is_supported_media(metadata: dict, path: Path) -> bool:
    mime = metadata.get("File:MIMEType")
    if isinstance(mime, str):
        if mime.lower().startswith(("image/", "video/")):
            return True
        return False
    ext = path.suffix.lower()
    return ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS


def build_target_path(
    source: Path, dt: datetime, output_dir: Optional[Path], is_video_file: bool
) -> Path:
    prefix = "MOV_" if is_video_file else "IMG_"
    target_dir = output_dir if output_dir else source.parent
    target_name = f"{prefix}{dt.strftime('%Y-%m-%d_%H-%M-%S')}{source.suffix}"
    return target_dir / target_name


def read_metadata(et: exiftool.ExifTool, path: Path, logger: logging.Logger) -> Optional[dict]:
    try:
        if hasattr(et, "get_metadata"):
            data = et.get_metadata(str(path))
        else:
            data = et.get_metadata_batch([str(path)])
    except Exception as exc:
        logger.error("Failed to read metadata for %s: %s", path, exc)
        return None

    if isinstance(data, list):
        return data[0] if data else None
    return data


def process_file(
    path: Path,
    et: exiftool.ExifTool,
    logger: logging.Logger,
    output_dir: Optional[Path],
    verbose: bool,
    dry_run: bool,
) -> bool:
    metadata = read_metadata(et, path, logger)
    if not metadata:
        return False

    if metadata.get("Error") or metadata.get("ExifTool:Error"):
        logger.error("ExifTool error for %s: %s", path, metadata.get("Error") or metadata.get("ExifTool:Error"))
        return False

    if not is_supported_media(metadata, path):
        return False

    dt = parse_datetime(metadata)
    if not dt:
        return False

    target_path = build_target_path(path, dt, output_dir, is_video(metadata, path))

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
    log_path = log_dir / "rename-errors.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logger(log_path)

    files = list(iter_files(input_dir, output_dir))
    if not files and args.verbose:
        print("No files found to process.")

    processed = 0
    renamed = 0
    with exiftool.ExifTool() as et:
        for file_path in files:
            processed += 1
            if process_file(
                file_path,
                et,
                logger,
                output_dir,
                args.verbose,
                args.dry_run,
            ):
                renamed += 1

    if args.verbose:
        action = "would be renamed" if args.dry_run else "renamed"
        print(f"{renamed} of {processed} files {action}. Errors logged to {log_path}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
