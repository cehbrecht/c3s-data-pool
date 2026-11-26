"""Download remote catalog snapshots into an atomic, reusable local cache."""

import gzip
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

LOG = logging.getLogger("c3s-data-pool")
CHUNK_SIZE = 1024 * 1024


def cache_catalog(location, cache_dir=None, *, refresh=False):
    """Return a local catalog path; failed refreshes preserve the previous cache."""
    if not isinstance(location, str) or not location.startswith("https://"):
        return Path(location)
    if cache_dir is None:
        cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "c3s-data-pool"
    cache_dir = Path(cache_dir).expanduser()
    filename = hashlib.sha256(location.encode("utf-8")).hexdigest() + ".csv.gz"
    cached = cache_dir / filename
    if cached.is_file() and not refresh:
        LOG.info("using cached catalog: %s", cached)
        return cached

    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        LOG.info("downloading catalog: %s", location)
        with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            with urlopen(location, timeout=30) as response:
                expected = response.headers.get("Content-Length")
                downloaded = 0
                while chunk := response.read(CHUNK_SIZE):
                    output.write(chunk)
                    downloaded += len(chunk)
                if expected is not None and downloaded != int(expected):
                    raise ValueError(
                        f"incomplete catalog download: expected {expected} bytes, got {downloaded}"
                    )
        # Check gzip integrity before publishing, so partial downloads are never reused.
        with gzip.open(temporary, "rb") as stream:
            while stream.read(CHUNK_SIZE):
                pass
        temporary.replace(cached)
        LOG.info("cached catalog: %s", cached)
        return cached
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
