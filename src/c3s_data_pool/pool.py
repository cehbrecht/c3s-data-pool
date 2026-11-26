"""Inspect destination files and safely create or verify hardlinks."""

import logging
import os
import stat

LOG = logging.getLogger("c3s-data-pool")


def destination_stat(root, relative):
    """Reject destination symlinks, including dangling links and parent links."""
    current = root
    for part in (None, *relative.parts[:-1]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
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


def process_row(paths, relative, size, stats, *, build, apply):
    destination = paths["target"] / relative
    try:
        existing = destination_stat(paths["target"], relative)
    except (ValueError, NotADirectoryError) as exc:
        stats.conflicts += 1
        LOG.error("conflict %s: %s", destination, exc)
        return
    if not build:
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
    try:
        source = source.resolve(strict=True)
        source_info = source.stat()
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
        LOG.error("source resolves to destination; no independent link: %s", source)
        return
    if existing is not None:
        if same_file(existing, source_info) and existing.st_size == size:
            stats.existing += 1
        else:
            stats.conflicts += 1
            LOG.error("conflict: destination is not the expected hardlink: %s", destination)
        return
    if not apply:
        # Inspect the nearest existing ancestor without creating directories.
        ancestor = destination.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if ancestor.stat().st_dev != source_info.st_dev:
            stats.hardlink_failures += 1
            LOG.error("hardlink requires the same filesystem: %s -> %s", source, destination)
        else:
            stats.planned += 1
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after mkdir; link itself never replaces an existing name.
        destination_stat(paths["target"], relative)
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            concurrent = destination_stat(paths["target"], relative)
            if (
                concurrent is not None
                and same_file(concurrent, source_info)
                and concurrent.st_size == size
            ):
                stats.existing += 1
                return
            raise ValueError("destination appeared and is not the expected hardlink")
        linked = destination.lstat()
        if (
            not stat.S_ISREG(linked.st_mode)
            or not same_file(linked, source_info)
            or linked.st_size != size
        ):
            raise ValueError("new link failed inode/device/size validation; inspect destination")
        stats.created += 1
    except (OSError, ValueError) as exc:
        stats.hardlink_failures += 1
        LOG.error("hardlink failed %s -> %s: %s", source, destination, exc)
