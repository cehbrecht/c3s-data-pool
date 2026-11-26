"""Check source existence, type and size with one stat call per catalog entry."""

import logging
import stat

LOG = logging.getLogger("c3s-data-pool")


def check_source(paths, relative, size, stats):
    source = paths["source"] / relative
    try:
        # stat follows symlinks in the kernel, avoiding user-space path walks.
        info = source.stat()
    except FileNotFoundError:
        stats.missing += 1
        LOG.error("missing source: %s", source)
        return
    if not stat.S_ISREG(info.st_mode):
        stats.conflicts += 1
        LOG.error("source is not a regular file: %s", source)
    elif info.st_size != size:
        stats.size_mismatches += 1
        LOG.error("source size mismatch %s: expected=%d actual=%d", source, size, info.st_size)
    else:
        stats.checked += 1
