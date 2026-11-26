"""Stream and validate CSV catalogs, reporting each collection."""

import csv
import gzip
import logging
import time
import zlib
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path, PurePosixPath

from .cache import cache_catalog
from .metadata import MetadataCache
from .pool import process_row
from .progress import Heartbeat
from .quick import check_source
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


@contextmanager
def open_catalog(location):
    """Open a local catalog, including a cached remote snapshot."""
    opener = gzip.open if Path(location).suffix == ".gz" else open
    with opener(location, "rt", encoding="utf-8-sig", newline="") as stream:
        yield stream


def relative_path(value):
    """Accept only unambiguous POSIX paths beneath the configured roots."""
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("empty path, NUL or backslash")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("path must be relative without empty, '.' or '..' components")
    return Path(*path.parts)


def catalog_reader(stream):
    reader = csv.DictReader(stream, strict=True)
    required = {"path", "size", "mip_era"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("catalog requires path, size and mip_era columns")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("catalog has duplicate column names")
    return reader


def count_catalog_files(name, stream):
    """Count CSV records, including quoted multiline records, without file checks."""
    LOG.info("%s: counting catalog files", name)
    count = 0
    last_report = time.monotonic()
    for count, _ in enumerate(catalog_reader(stream), start=1):
        now = time.monotonic()
        if now - last_report >= 30:
            LOG.info("%s: counted %d catalog files so far", name, count)
            last_report = now
    if count == 0:
        raise ValueError("catalog has no file rows")
    LOG.info("%s: catalog contains %d files", name, count)
    return count


def process_catalog(
    name,
    paths,
    *,
    build,
    apply,
    progress_every,
    cache_dir=None,
    refresh=False,
    quick=False,
    heartbeat_seconds=15,
):
    if quick and (apply or not build):
        raise ValueError("quick mode is only available for read-only source scans")
    stats = Stats()
    dataset_directories = set()
    metadata = MetadataCache()
    with Heartbeat(name, interval=heartbeat_seconds) as heartbeat:
        try:
            heartbeat.update("preparing catalog", paths["catalog"])
            location = cache_catalog(paths["catalog"], cache_dir, refresh=refresh)
            heartbeat.update("counting catalog", location)
            with open_catalog(location) as stream:
                stats.total_files = count_catalog_files(name, stream)
                stats.report(name, "progress")
                heartbeat.update("reading catalog", completed=0, total=stats.total_files)
                stream.seek(0)
                last_report = time.monotonic()
                for row in catalog_reader(stream):
                    if stats.files == stats.total_files:
                        raise ValueError(
                            "catalog file count changed between passes; use a fixed catalog snapshot"
                        )
                    stats.files += 1
                    try:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError("row does not match catalog header")
                        relative = relative_path(row["path"])
                        if not row["size"].isascii() or not row["size"].isdigit():
                            raise ValueError("size must be a non-negative integer in bytes")
                        size = int(row["size"])
                    except ValueError as exc:
                        stats.invalid += 1
                        LOG.error("%s row %d: invalid catalog entry: %s", name, stats.files, exc)
                    else:
                        dataset_directories.add(relative.parent)
                        stats.datasets = len(dataset_directories)
                        stats.logical_bytes += size
                        try:
                            heartbeat.update(
                                "checking source" if quick else "checking file",
                                (paths["source"] if build else paths["target"]) / relative,
                                completed=stats.files - 1,
                                total=stats.total_files,
                            )
                            if quick:
                                check_source(paths, relative, size, stats)
                            else:
                                process_row(
                                    paths,
                                    relative,
                                    size,
                                    stats,
                                    build=build,
                                    apply=apply,
                                    metadata=metadata,
                                )
                        except (OSError, RuntimeError) as exc:
                            stats.errors += 1
                            LOG.error("%s row %d (%s): %s", name, stats.files, relative, exc)
                    heartbeat.update(
                        "reading catalog", completed=stats.files, total=stats.total_files
                    )
                    now = time.monotonic()
                    if stats.files % progress_every == 0 or now - last_report >= 30:
                        stats.report(name, "progress")
                        last_report = now
            if stats.files != stats.total_files:
                raise ValueError(
                    "catalog file count changed between passes; use a fixed catalog snapshot"
                )
        except (
            OSError,
            EOFError,
            UnicodeError,
            csv.Error,
            ValueError,
            zlib.error,
            HTTPException,
        ) as exc:
            stats.errors += 1
            LOG.error("%s: catalog failed: %s", name, exc)
    stats.report(name, "quick summary" if quick else "summary")
    return stats
