"""
Make a python3 script for extracting file from a disk image using the database from a ddscan output.
Arguments:
  -i <input disk image> (mandatory)
  -d <ddscan database file> (mandatory)
  -o <output directory> (mandatory)
  -n <number of files to extract> (optional, default: all files)
  -w <sqlite3 where clause> (optional, default: none) - a where clause to filter which files to extract from the ddscan database.
  --dry-run (optional, default: false) - if set, the script will only print the files that would be extracted and to where, without actually extracting them.
  -v (optional, default: false) - if set, the script will print verbose output during extraction.
  -h (optional) - display help message and exit.

  Also update the README.md file to include usage instructions for this script.
  
  The schema for the ddscan database is located in the assets/ddscan-schema.sql file.
  The database contains these info:
    - Look in the files table:
      _id    INTEGER NOT NULL
      name    TEXT NOT NULL: File name, the name to give the file when extracting.
      path    INTEGER NOT NULL: This number refers to the paths table, which contains the directory structure. Use the directory from here as <path-dir>
      block    INTEGER: Multiply this number with 512 to get the offset in the disk image where the file starts.
      size    INTEGER DEFAULT 0: Size of the file in bytes.
      date    INTEGER: UNIX timestamp of the file's modification date, use this when writing the extracted file to preserve the modification date.
      hasFilePlaces    bit NOT NULL: Ignore
      mark    INTEGER DEFAULT 0: Ignore
      deletedState    INTEGER: Ignore
      recovered    INTEGER DEFAULT 0: Ignore
      fileCategory    INTEGER: Ignore
      restorerCookie    INTEGER: Ignore
      sysPathIndex      INTEGER: Ignore
      attributes    BLOB: Ignore
      FOREIGN KEY(path) REFERENCES paths("index") ON DELETE CASCADE: Ignore
      PRIMARY KEY(_id AUTOINCREMENT): Ignore

      When selecting entries from the files table, only select on row for each block/size combination. I.e. if there are multiple entries with the same block andsize, only select one of them.

      The file is to be saved into this directory structure:
        <output directory>/<path-dir>/<name>
        
      Update requirements.txt to include any new dependencies needed for this script.
      Keep this text in the script.

"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

SECTOR_SIZE = 512


class FileEntry(NamedTuple):
    file_id: int
    name: str
    path_dir: str
    block: int
    size: int
    mtime: Optional[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract files from a ddscan SQLite database and a raw disk image."
    )
    parser.add_argument("-i", "--input", required=True, help="Path to input disk image")
    parser.add_argument("-d", "--database", required=True, help="Path to ddscan SQLite database")
    parser.add_argument("-o", "--output", required=True, help="Directory to write extracted files")
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=None,
        help="Maximum number of files to extract (default: all)",
    )
    parser.add_argument(
        "-w",
        "--where",
        dest="where_clause",
        help="SQLite WHERE clause to filter files table (without the WHERE keyword)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be extracted without writing files",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose output during extraction",
    )
    return parser.parse_args()


def normalize_subpath(raw: str) -> Path:
    cleaned = raw.replace("\\", "/").lstrip("/")
    parts = []
    for part in Path(cleaned).parts:
        if part in ("", ".", ".."):
            continue
        if part.endswith(":"):  # drop drive letters like C:
            continue
        parts.append(part)
    return Path(*parts)


def fetch_entries(conn: sqlite3.Connection, where_clause: Optional[str], limit: Optional[int]) -> Iterable[FileEntry]:
    base_filter = "f.block IS NOT NULL AND f.size IS NOT NULL"
    if where_clause:
        base_filter = f"{base_filter} AND ({where_clause})"

    query = f"""
    WITH ranked AS (
        SELECT
            f._id AS file_id,
            f.name,
            f.block,
            f.size,
            f.date,
            p.path AS path_dir,
            ROW_NUMBER() OVER (PARTITION BY f.block, f.size ORDER BY f._id) AS rn
        FROM files f
        JOIN paths p ON f.path = p."index"
        WHERE {base_filter}
    )
    SELECT file_id, name, block, size, date, path_dir
    FROM ranked
    WHERE rn = 1
    ORDER BY block ASC
    """
    params = []
    if limit is not None and limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    cursor = conn.execute(query, params)
    for row in cursor:
        yield FileEntry(
            file_id=row[0],
            name=row[1],
            path_dir=row[5],
            block=row[2],
            size=row[3],
            mtime=row[4],
        )


def ensure_within_output(output_root: Path, target: Path) -> bool:
    # resolve(strict=False) avoids FileNotFoundError before directories exist
    target_resolved = target.resolve(strict=False)
    output_resolved = output_root.resolve(strict=False)
    return target_resolved == output_resolved or output_resolved in target_resolved.parents


def extract_files(
    image_path: Path,
    entries: Iterable[FileEntry],
    output_dir: Path,
    dry_run: bool,
    verbose: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_size = image_path.stat().st_size

    extracted = 0
    skipped = 0

    with image_path.open("rb") as image_fp:
        for entry in entries:
            if entry.block < 0 or entry.size is None or entry.size <= 0:
                skipped += 1
                if verbose:
                    print(f"[skip] invalid block/size for id={entry.file_id}")
                continue

            offset = entry.block * SECTOR_SIZE
            end_offset = offset + entry.size
            if end_offset > image_size:
                skipped += 1
                if verbose:
                    print(f"[skip] id={entry.file_id} offset+size exceeds image bounds")
                continue

            safe_dir = normalize_subpath(entry.path_dir)
            dest_dir = output_dir / safe_dir
            dest_path = dest_dir / Path(entry.name).name

            if not ensure_within_output(output_dir, dest_path):
                skipped += 1
                print(f"[skip] destination escapes output dir for id={entry.file_id}: {dest_path}")
                continue

            if dry_run:
                print(f"[dry-run] {dest_path} (offset {offset}, size {entry.size})")
                extracted += 1
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)

            image_fp.seek(offset)
            data = image_fp.read(entry.size)
            if len(data) != entry.size:
                skipped += 1
                print(f"[skip] could not read full data for id={entry.file_id}")
                continue

            if dest_path.exists():
                skipped += 1
                print(f"[skip] destination exists, not overwriting: {dest_path}")
                continue

            with dest_path.open("wb") as out_fp:
                out_fp.write(data)

            if entry.mtime:
                try:
                    os.utime(dest_path, times=(entry.mtime, entry.mtime))
                except OSError:
                    if verbose:
                        print(f"[warn] failed to set mtime for {dest_path}")

            extracted += 1
            if verbose:
                dt = datetime.utcfromtimestamp(entry.mtime).isoformat() + "Z" if entry.mtime else "unknown"
                print(f"[ok] wrote {dest_path} (size {entry.size}, mtime {dt})")

    print(f"Done. Extracted {extracted} file(s); skipped {skipped}.")


def main() -> None:
    args = parse_args()
    image_path = Path(args.input)
    db_path = Path(args.database)
    output_dir = Path(args.output)

    if not image_path.is_file():
        print(f"Input image not found: {image_path}", file=sys.stderr)
        sys.exit(1)
    if not db_path.is_file():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    try:
        entries = list(fetch_entries(conn, args.where_clause, args.number))
    except sqlite3.DatabaseError as exc:
        print(f"Failed to read database: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

    if not entries:
        print("No files matched the selection criteria.", file=sys.stderr)
        sys.exit(1)

    extract_files(
        image_path=image_path,
        entries=entries,
        output_dir=output_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
