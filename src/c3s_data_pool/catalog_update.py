"""Update an existing catalog using source metadata, preserving its other fields."""

import csv
import gzip
import logging
import os
import stat
import tempfile
import time
import zlib
from http.client import HTTPException
from pathlib import Path

from .cache import cache_catalog
from .catalog import catalog_reader, count_catalog_files, open_catalog, relative_path
from .config import catalog_location
from .progress import Heartbeat
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


def update_catalog(
    catalog,
    source,
    output,
    mip_era,
    *,
    progress_every=10000,
    cache_dir=None,
    refresh=False,
    heartbeat_seconds=15,
    console=None,
):
    """Publish a new catalog only when all rows succeed; never replace a file."""
    stats = Stats()
    temporary = None
    datasets = set()
    source = Path(source).expanduser().absolute()
    output = Path(output).expanduser().absolute()
    with Heartbeat("catalog-update", interval=heartbeat_seconds, console=console) as heartbeat:
        try:
            if not output.name.endswith((".csv", ".csv.gz")):
                raise ValueError("output must end in .csv or .csv.gz")
            if not mip_era.strip():
                raise ValueError("mip_era must not be empty")
            try:
                output.lstat()
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(f"output already exists; choose a new path: {output}")
            location = catalog_location(str(catalog), Path.cwd())
            LOG.info(
                "mode=update-catalog catalog=%s source=%s output=%s mip_era=%s",
                location,
                source,
                output,
                mip_era,
            )
            heartbeat.update("preparing catalog", location)
            location = cache_catalog(location, cache_dir, refresh=refresh)
            with open_catalog(location) as stream:
                heartbeat.update("counting catalog", location)
                stats.total_files = count_catalog_files(
                    "catalog-update", stream, required=("path",)
                )
                stream.seek(0)
                reader = catalog_reader(stream, required=("path",))
                columns = list(reader.fieldnames)
                columns.extend(column for column in ("size", "mip_era") if column not in columns)
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=output.parent, prefix=".c3s-catalog-", suffix=".part", delete=False
                ) as pending:
                    temporary = Path(pending.name)
                opener = gzip.open if output.name.endswith(".gz") else open
                with opener(temporary, "wt", encoding="utf-8", newline="") as destination:
                    writer = csv.DictWriter(destination, fieldnames=columns)
                    writer.writeheader()
                    stats.report("catalog-update", "progress")
                    last_report = time.monotonic()
                    for row in reader:
                        stats.files += 1
                        if stats.files > stats.total_files:
                            raise ValueError("catalog file count changed between passes")
                        try:
                            if None in row or any(value is None for value in row.values()):
                                raise ValueError("row does not match catalog header")
                            relative = relative_path(row["path"])
                        except ValueError as exc:
                            stats.invalid += 1
                            LOG.error(
                                "catalog-update row %d: invalid catalog entry: %s", stats.files, exc
                            )
                        else:
                            current = source / relative
                            heartbeat.update(
                                "checking source",
                                current,
                                completed=stats.files - 1,
                                total=stats.total_files,
                            )
                            try:
                                info = (
                                    current.stat()
                                )  # Follow symlinks without reading file contents.
                            except FileNotFoundError:
                                stats.missing += 1
                                LOG.error("missing source: %s", current)
                            except (OSError, RuntimeError) as exc:
                                stats.errors += 1
                                LOG.error("cannot inspect source %s: %s", current, exc)
                            else:
                                if not stat.S_ISREG(info.st_mode):
                                    stats.conflicts += 1
                                    LOG.error("source is not a regular file: %s", current)
                                else:
                                    row["size"] = str(info.st_size)
                                    row["mip_era"] = mip_era
                                    writer.writerow(row)
                                    stats.checked += 1
                                    stats.logical_bytes += info.st_size
                                    datasets.add(relative.parent)
                                    stats.datasets = len(datasets)
                        heartbeat.update(
                            "reading catalog", completed=stats.files, total=stats.total_files
                        )
                        now = time.monotonic()
                        if stats.files % progress_every == 0 or now - last_report >= 30:
                            stats.report("catalog-update", "progress")
                            last_report = now
                if stats.files != stats.total_files:
                    raise ValueError("catalog file count changed between passes")
            if stats.failed:
                LOG.error("catalog update incomplete; output was not published; input is unchanged")
            else:
                heartbeat.update(
                    "publishing catalog", output, completed=stats.files, total=stats.total_files
                )
                with temporary.open("rb+") as pending:
                    os.fsync(pending.fileno())
                os.link(temporary, output, follow_symlinks=False)
                LOG.info("updated catalog written: %s", output)
        except (
            OSError,
            RuntimeError,
            EOFError,
            UnicodeError,
            csv.Error,
            ValueError,
            zlib.error,
            HTTPException,
        ) as exc:
            stats.errors += 1
            LOG.error("catalog update failed: %s", exc)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    stats.errors += 1
                    LOG.error("cannot remove temporary catalog %s: %s", temporary, exc)
        heartbeat.update(
            "finished with errors" if stats.failed else "complete",
            completed=stats.files,
            total=stats.total_files,
        )
    stats.report("catalog-update", "summary")
    return stats
