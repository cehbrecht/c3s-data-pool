"""Inspect destination files and safely create hardlinks or copies."""

import logging
import os
import stat

from .copying import copy_file
from .metadata import MetadataCache
from .source import check_source

LOG = logging.getLogger("c3s-data-pool")


def destination_stat(root, relative, metadata=None):
    """Reject destination symlinks, including dangling links and parent links."""
    current = root
    for part in (None, *relative.parts[:-1]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat() if metadata is None else metadata.directory_stat(current)
        except FileNotFoundError:
            return None
        if info is None:
            return None
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"destination parent is not a real directory: {current}")
    try:
        info = (root / relative).lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("destination exists but is not a regular file (symlinks forbidden)")
    return info


def same_file(first, second):
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def prepare_destination(root, relative):
    """Create missing parents, rejecting symlinks before descending into them."""
    current = root
    for part in (None, *relative.parts[:-1]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            # Only the configured root may need ancestors outside the pool.
            current.mkdir(parents=part is None, exist_ok=True)
            info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"destination parent is not a real directory: {current}")


def process_row(
    paths, relative, size, stats, *, build, apply, metadata=None, method="hardlink", heartbeat=None
):
    if method not in {"hardlink", "copy"}:
        raise ValueError(f"unsupported retention method: {method}")
    if metadata is None:
        metadata = MetadataCache()

    def report(stage, current):
        if heartbeat is not None:
            heartbeat.update(stage, current, completed=stats.files - 1, total=stats.total_files)

    if build and not apply:
        check_source(paths, relative, size, stats)
        return
    destination = paths["target"] / relative
    if not build:
        report("checking destination", destination)
        try:
            existing = destination_stat(paths["target"], relative, metadata)
        except (ValueError, NotADirectoryError) as exc:
            stats.conflicts += 1
            LOG.error("conflict %s: %s", destination, exc)
            return
        if existing is None:
            stats.missing += 1
            LOG.error("missing destination: %s", destination)
        elif existing.st_size != size:
            stats.size_mismatches += 1
            LOG.error(
                "destination size mismatch %s: expected=%d actual=%d",
                destination,
                size,
                existing.st_size,
            )
        else:
            stats.verified += 1
        return

    source = paths["source"] / relative
    report("checking source", source)
    try:
        source, source_info = metadata.source_file(source)
    except FileNotFoundError:
        stats.missing += 1
        LOG.error("missing source: %s", source)
        return
    if not stat.S_ISREG(source_info.st_mode):
        stats.conflicts += 1
        LOG.error("source is not a regular file: %s", source)
        return
    if source_info.st_size != size:
        stats.size_mismatches += 1
        LOG.error(
            "source size mismatch %s: expected=%d actual=%d", source, size, source_info.st_size
        )
        return
    if source == destination:
        stats.conflicts += 1
        LOG.error("source resolves to destination; no independent retained path: %s", source)
        return
    try:
        try:
            report("preparing destination", destination.parent)
            prepare_destination(paths["target"], relative)
        except (ValueError, NotADirectoryError) as exc:
            stats.conflicts += 1
            LOG.error("conflict %s: %s", destination, exc)
            return
        if method == "copy":
            try:
                created = copy_file(source, destination, size, source_info, on_stage=report)
            except FileExistsError as exc:
                stats.conflicts += 1
                LOG.error("conflict %s: %s", destination, exc)
                return
            if created:
                stats.created += 1
            else:
                stats.existing += 1
            return
        try:
            report("creating hardlink", destination)
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            try:
                concurrent = destination_stat(paths["target"], relative)
            except (ValueError, NotADirectoryError) as exc:
                stats.conflicts += 1
                LOG.error("conflict %s: %s", destination, exc)
                return
            if (
                concurrent is not None
                and same_file(concurrent, source_info)
                and concurrent.st_size == size
            ):
                stats.existing += 1
                return
            stats.conflicts += 1
            LOG.error("conflict: destination is not the expected hardlink: %s", destination)
            return
        linked = destination.lstat()
        if (
            not stat.S_ISREG(linked.st_mode)
            or not same_file(linked, source_info)
            or linked.st_size != size
        ):
            raise ValueError("new link failed inode/device/size validation; inspect destination")
        stats.created += 1
    except (OSError, ValueError) as exc:
        if method == "copy":
            stats.copy_failures += 1
        else:
            stats.hardlink_failures += 1
        LOG.error("%s failed %s -> %s: %s", method, source, destination, exc)
