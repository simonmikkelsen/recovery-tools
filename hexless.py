"""
This python 3 script works as close as possible to the core functionality of the less command with the twist that the files contents is shown in hexadecimal format without the ASCII representation on the right side.
It reads the specified file (or stdin if no file is specified) and outputs the hexadecimal representation to stdout.
Usage: python3 hexless.py [file]
If no file is specified, it reads from standard input.

It is possible to page both up and down with arrow keys, page up/down keys, home/end keys.
"""

from __future__ import annotations

import argparse
import curses
import mmap
import os
import sys
from pathlib import Path
from typing import BinaryIO, Optional, TextIO

DEFAULT_BYTES_PER_LINE = 16
READ_CHUNK_SIZE = 8192


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="View file contents in hex with paging controls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="File to view (reads stdin if omitted).",
    )
    return parser.parse_args()


def format_hex_line(data: bytes) -> str:
    return " ".join(f"{value:02x}" for value in data)


def bytes_per_line_from_columns(columns: int) -> int:
    return max(1, (columns + 1) // 3)


class DataSource:
    def __init__(self, length: int) -> None:
        self.length = length

    def read(self, offset: int, size: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        return None


class MMapDataSource(DataSource):
    def __init__(self, path: Path) -> None:
        self._file = path.open("rb")
        self._size = path.stat().st_size
        if self._size:
            self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            super().__init__(self._size)
        else:
            self._mmap = None
            super().__init__(0)

    def read(self, offset: int, size: int) -> bytes:
        if self._mmap is None:
            return b""
        end = min(offset + size, self.length)
        if offset >= end:
            return b""
        return self._mmap[offset:end]

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
        self._file.close()


class BufferDataSource(DataSource):
    def __init__(self, data: bytes) -> None:
        super().__init__(len(data))
        self._data = data

    def read(self, offset: int, size: int) -> bytes:
        end = min(offset + size, self.length)
        if offset >= end:
            return b""
        return self._data[offset:end]


def write_hex_stream(reader: BinaryIO, writer: TextIO, bytes_per_line: int) -> None:
    remainder = b""
    while True:
        chunk = reader.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        data = remainder + chunk
        line_count = len(data) // bytes_per_line
        end = line_count * bytes_per_line
        for offset in range(0, end, bytes_per_line):
            writer.write(format_hex_line(data[offset : offset + bytes_per_line]))
            writer.write("\n")
        remainder = data[end:]
    if remainder:
        writer.write(format_hex_line(remainder))
        writer.write("\n")


def pager(stdscr: curses.window, source: DataSource) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    top_offset = 0

    while True:
        stdscr.erase()
        rows, cols = stdscr.getmaxyx()
        bytes_per_line = bytes_per_line_from_columns(cols)
        total_lines = (
            (source.length + bytes_per_line - 1) // bytes_per_line
            if source.length
            else 0
        )
        lines_visible = rows

        top_line = top_offset // bytes_per_line if bytes_per_line else 0
        max_top_line = max(total_lines - lines_visible, 0)
        if top_line > max_top_line:
            top_line = max_top_line
            top_offset = top_line * bytes_per_line

        for line_index in range(lines_visible):
            offset = (top_line + line_index) * bytes_per_line
            if offset >= source.length:
                break
            chunk = source.read(offset, bytes_per_line)
            stdscr.addnstr(line_index, 0, format_hex_line(chunk), cols)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord("q"), ord("Q")):
            break
        if key == curses.KEY_UP:
            top_line = max(top_line - 1, 0)
        elif key == curses.KEY_DOWN:
            top_line = min(top_line + 1, max_top_line)
        elif key == curses.KEY_PPAGE:
            top_line = max(top_line - lines_visible, 0)
        elif key == curses.KEY_NPAGE:
            top_line = min(top_line + lines_visible, max_top_line)
        elif key == curses.KEY_HOME:
            top_line = 0
        elif key == curses.KEY_END:
            top_line = max_top_line

        top_offset = top_line * bytes_per_line


def run_interactive(source: DataSource) -> int:
    try:
        curses.wrapper(pager, source)
    except curses.error as exc:
        eprint(f"[error] curses failed: {exc}")
        return 1
    return 0


def main() -> int:
    args = parse_args()
    file_arg = args.file
    stdout_is_tty = sys.stdout.isatty()

    if file_arg:
        path = Path(file_arg).expanduser().resolve()
        if not path.is_file():
            eprint(f"File not found: {path}")
            return 1
        if stdout_is_tty:
            source = MMapDataSource(path)
            try:
                return run_interactive(source)
            finally:
                source.close()
        with path.open("rb") as reader:
            write_hex_stream(reader, sys.stdout, DEFAULT_BYTES_PER_LINE)
        return 0

    if stdout_is_tty:
        data = sys.stdin.buffer.read()
        source = BufferDataSource(data)
        return run_interactive(source)

    write_hex_stream(sys.stdin.buffer, sys.stdout, DEFAULT_BYTES_PER_LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
