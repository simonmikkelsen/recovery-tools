"""

Make a python3 script that takes 2 arguments:
- <input disk image> (mandatory)
- <file> (mandatory)
-v (optional, default: false) - if set, the script will print verbose output during extraction.
-h (optional) - display help message and exit.

The script will read the disk image from end to end and print all file locations found in the given disk image.

      Update requirements.txt to include any new dependencies needed for this script.
    Keep this text in the script.

"""

import argparse
import os
import sys
from pathlib import Path
from typing import Generator, Iterable


DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find all occurrences of a file's byte content within a disk image."
    )
    parser.add_argument("disk_image", help="Path to the input disk image")
    parser.add_argument(
        "files",
        nargs="+",
        help="One or more files whose content to search for",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose progress updates",
    )
    return parser.parse_args()


def stream_find(
    image_path: Path,
    needle: bytes,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    verbose: bool = False,
    label: str = "",
) -> Generator[int, None, None]:
    """
    Stream through the image file and yield byte offsets where `needle` is found.
    """
    needle_len = len(needle)
    if needle_len == 0:
        return

    chunk_size = max(chunk_size, needle_len + 1)
    processed = 0
    prev_tail = b""
    next_report = 0
    report_step = 1 * 1024 * 1024 * 1024  # 1 GiB

    with image_path.open("rb", buffering=0) as fp:
        while True:
            chunk = fp.read(chunk_size)
            if not chunk:
                break

            data = prev_tail + chunk
            search_from = 0
            while True:
                idx = data.find(needle, search_from)
                if idx == -1:
                    break
                match_offset = processed - len(prev_tail) + idx
                yield match_offset
                search_from = idx + 1

            processed += len(chunk)
            if needle_len > 1:
                prev_tail = data[-(needle_len - 1) :]
            else:
                prev_tail = b""

            if verbose and processed >= next_report:
                prefix = f"[info][{label}] " if label else "[info] "
                print(f"{prefix}scanned {processed // (1024 * 1024)} MiB", file=sys.stderr)
                next_report += report_step


def format_offset(offset: int) -> str:
    sector = offset // 512
    return f"byte {offset} (sector {sector})"


def main() -> None:
    args = parse_args()
    image_path = Path(args.disk_image)
    file_paths = [Path(p) for p in args.files]

    if not image_path.is_file():
        print(f"Disk image not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    for fp in file_paths:
        if not fp.is_file():
            print(f"File to search not found: {fp}", file=sys.stderr)
            sys.exit(1)
        if fp.stat().st_size == 0:
            print(f"Cannot search for empty file: {fp}", file=sys.stderr)
            sys.exit(1)

    any_matches = False
    for fp in file_paths:
        needle = fp.read_bytes()
        label = fp.name
        if args.verbose:
            print(
                f"[info][{label}] searching for {len(needle)} bytes inside {image_path}",
                file=sys.stderr,
            )

        matches = list(stream_find(image_path, needle, verbose=args.verbose, label=label))
        if matches:
            any_matches = True
            for offset in matches:
                print(f"{label}: {format_offset(offset)}")
            if args.verbose:
                print(f"[info][{label}] found {len(matches)} occurrence(s).", file=sys.stderr)
        else:
            if args.verbose:
                print(f"[info][{label}] no occurrences found.", file=sys.stderr)

    if not any_matches:
        sys.exit(1)


if __name__ == "__main__":
    main()
