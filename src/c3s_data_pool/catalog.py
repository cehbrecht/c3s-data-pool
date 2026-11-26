"""Stream and validate compressed CSV catalogs, reporting each collection."""

import csv
import gzip
import logging
from pathlib import Path, PurePosixPath
import time
import zlib

from .pool import process_row
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


def relative_path(value):
    """Accept only unambiguous POSIX paths beneath the configured roots."""
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("empty path, NUL or backslash")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("path must be relative without empty, '.' or '..' components")
    return Path(*path.parts)


def process_catalog(name, paths, *, build, apply, progress_every):
    stats = Stats()
    last_report = time.monotonic()
    try:
        with gzip.open(paths["catalog"], "rt", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            required = {"path", "size", "mip_era"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("catalog requires path, size and mip_era columns")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("catalog has duplicate column names")
            for row in reader:
                stats.rows += 1
                try:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("row does not match catalog header")
                    relative = relative_path(row["path"])
                    if not row["size"].isascii() or not row["size"].isdigit():
                        raise ValueError("size must be a non-negative integer in bytes")
                    size = int(row["size"])
                except ValueError as exc:
                    stats.invalid += 1
                    LOG.error("%s row %d: invalid catalog entry: %s", name, stats.rows, exc)
                else:
                    stats.logical_bytes += size
                    try:
                        process_row(paths, relative, size, stats, build=build, apply=apply)
                    except (OSError, RuntimeError) as exc:
                        stats.errors += 1
                        LOG.error("%s row %d (%s): %s", name, stats.rows, relative, exc)
                now = time.monotonic()
                if stats.rows % progress_every == 0 or now - last_report >= 30:
                    stats.report(name, "progress")
                    last_report = now
        if stats.rows == 0:
            raise ValueError("catalog has no file rows")
    except (OSError, EOFError, UnicodeError, csv.Error, ValueError, zlib.error) as exc:
        stats.errors += 1
        LOG.error("%s: catalog failed: %s", name, exc)
    stats.report(name, "summary")
    return stats
