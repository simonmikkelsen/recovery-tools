#!/usr/bin/env python3
"""
Validate recovered .doc files using multiple readers.

Checks:
- OLE container validation via olefile
- Metadata parsing via hachoir
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Tuple

import olefile
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
import textract

DEBUG_MODE = False


@dataclass
class ValidationResult:
    name: str
    success: bool
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate .doc files by probing them with multiple parsers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=".",
        help="Directory to scan for .doc files.",
    )
    parser.add_argument(
        "-n",
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Only scan the top-level of the input directory.",
        default=True,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show validator details even for valid files.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print invalid files.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--only-valid",
        action="store_true",
        help="Print only the paths of valid .doc files.",
    )
    group.add_argument(
        "--only-invalid",
        action="store_true",
        help="Print only the paths of invalid .doc files.",
    )
    parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="Print a summary of totals after processing.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging from validators (e.g., hachoir warnings).",
    )
    return parser.parse_args()


def iter_doc_files(base: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*.doc" if recursive else "*.doc"
    yield from (p for p in base.glob(pattern) if p.is_file())


def validate_with_olefile(path: Path) -> ValidationResult:
    if not olefile.isOleFile(str(path)):
        return ValidationResult("olefile", False, "Not an OLE compound file")

    try:
        with olefile.OleFileIO(str(path)) as ole:
            streams = ole.listdir()
            if not streams:
                return ValidationResult("olefile", False, "OLE container has no streams")
            # Summary streams indicate structured Word content
            if ole.exists("\x05SummaryInformation") or ole.exists("\x05DocumentSummaryInformation"):
                return ValidationResult("olefile", True, "OLE opened; summary info present")
            return ValidationResult("olefile", True, "OLE opened; streams present")
    except Exception as exc:
        return ValidationResult("olefile", False, f"OleFile error: {exc}")


def validate_with_hachoir(path: Path) -> ValidationResult:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    redirects = []
    if not DEBUG_MODE:
        redirects = [
            contextlib.redirect_stdout(stdout_buffer),
            contextlib.redirect_stderr(stderr_buffer),
        ]

    try:
        with contextlib.ExitStack() as stack:
            for redirect in redirects:
                stack.enter_context(redirect)
            parser = createParser(str(path))
    except Exception as exc:
        return ValidationResult("hachoir", False, f"Parser creation failed: {exc}")

    if not parser:
        return ValidationResult("hachoir", False, "Unable to create parser")

    try:
        with contextlib.ExitStack() as stack:
            for redirect in redirects:
                stack.enter_context(redirect)
            with parser:
                metadata = extractMetadata(parser)
    except Exception as exc:
        return ValidationResult("hachoir", False, f"Metadata extraction failed: {exc}")

    if not metadata:
        return ValidationResult("hachoir", False, "No metadata extracted")

    try:
        exported = list(metadata.exportPlaintext() or [])
    except Exception:
        exported = []

    detail = "Metadata extracted" if exported else "Metadata object returned"
    return ValidationResult("hachoir", True, detail)


def validate_with_textract(path: Path) -> ValidationResult:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    redirects = []
    if not DEBUG_MODE:
        redirects = [
            contextlib.redirect_stdout(stdout_buffer),
            contextlib.redirect_stderr(stderr_buffer),
        ]

    try:
        with contextlib.ExitStack() as stack:
            for redirect in redirects:
                stack.enter_context(redirect)
            text = textract.process(str(path))
    except Exception as exc:
        return ValidationResult("textract", False, f"Text extraction failed: {exc}")

    if text is None:
        return ValidationResult("textract", False, "No text extracted")

    clean_text = text.decode(errors="ignore").strip()
    if clean_text:
        return ValidationResult("textract", True, "Text extracted")
    return ValidationResult("textract", False, "Empty text extracted")


VALIDATORS: List[Callable[[Path], ValidationResult]] = [
    validate_with_olefile,
    validate_with_hachoir,
    validate_with_textract,
]


def validate_file(path: Path) -> Tuple[bool, List[ValidationResult]]:
    results = [validator(path) for validator in VALIDATORS]
    valid = any(r.success for r in results)
    textract_results = [r for r in results if r.name == "textract"]
    if textract_results:
        # If text extraction fails, consider the file invalid to catch documents
        # that open structurally but are unreadable.
        if not any(r.success for r in textract_results):
            valid = False
    return valid, results


def configure_hachoir_logging(debug: bool) -> None:
    if debug:
        logging.disable(logging.NOTSET)
        level = logging.DEBUG
    else:
        # Silence noisy parsers unless explicitly enabled.
        logging.disable(logging.CRITICAL)
        level = logging.CRITICAL

    for name in ("hachoir", "hachoir.metadata", "hachoir.parser"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        logger.handlers.clear()
        if debug:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            logger.addHandler(handler)
        else:
            logger.addHandler(logging.NullHandler())


def main() -> int:
    args = parse_args()
    global DEBUG_MODE
    DEBUG_MODE = args.debug
    configure_hachoir_logging(args.debug)
    base = Path(args.input_dir).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        print(f"Input directory does not exist or is not a directory: {base}", file=sys.stderr)
        return 1

    files = list(iter_doc_files(base, args.recursive))
    total = len(files)
    valid_count = 0
    invalid_count = 0

    for path in files:
        is_valid, results = validate_file(path)
        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1

        if args.only_valid:
            if is_valid:
                print(path)
            continue

        if args.only_invalid:
            if not is_valid:
                print(path)
            continue

        if args.quiet and is_valid:
            continue

        status = "VALID" if is_valid else "INVALID"
        if args.verbose:
            details = "; ".join(f"{r.name}: {r.detail}" for r in results)
            print(f"{status}: {path} ({details})")
        else:
            print(f"{status}: {path}")

    if args.summary:
        print(f"Processed: {total}, valid: {valid_count}, invalid: {invalid_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
