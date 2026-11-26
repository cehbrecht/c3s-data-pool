import gzip
import io
from urllib.error import URLError

import pytest

from c3s_data_pool import cache as cache_module
from c3s_data_pool.cache import cache_catalog

URL = "https://example.test/catalog.csv.gz"


class Response(io.BytesIO):
    def __init__(self, contents, expected=None):
        super().__init__(contents)
        self.headers = {"Content-Length": str(len(contents) if expected is None else expected)}

    def read(self, size=-1):
        assert 0 < size <= cache_module.CHUNK_SIZE
        return super().read(size)


def test_cache_reuse_and_explicit_refresh(tmp_path, monkeypatch):
    payloads = [gzip.compress(b"first snapshot"), gzip.compress(b"second snapshot")]
    responses = []

    def fetch(url, *, timeout):
        assert url == URL
        assert timeout == 30
        response = Response(payloads[len(responses)])
        responses.append(response)
        return response

    monkeypatch.setattr(cache_module, "urlopen", fetch)
    cached = cache_catalog(URL, tmp_path)
    assert cached.read_bytes() == payloads[0]
    assert cache_catalog(URL, tmp_path) == cached
    assert len(responses) == 1
    assert cache_catalog(URL, tmp_path, refresh=True) == cached
    assert cached.read_bytes() == payloads[1]
    assert len(responses) == 2
    assert all(response.closed for response in responses)
    assert not list(tmp_path.glob("*.part"))


def test_cache_is_keyed_by_full_url(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "urlopen", lambda *a, **kw: Response(gzip.compress(b"data")))
    first = cache_catalog(URL + "?version=1", tmp_path)
    second = cache_catalog(URL + "?version=2", tmp_path)
    assert first != second
    assert first.is_file() and second.is_file()


@pytest.mark.parametrize("failure", ["network", "length", "gzip", "interrupt"])
@pytest.mark.parametrize("refresh", [False, True])
def test_failed_download_never_publishes_partial_cache(tmp_path, monkeypatch, failure, refresh):
    good = gzip.compress(b"old snapshot")
    monkeypatch.setattr(cache_module, "urlopen", lambda *a, **kw: Response(good))
    cached = cache_catalog(URL, tmp_path) if refresh else None

    def broken(*args, **kwargs):
        if failure == "network":
            raise URLError("offline")
        if failure == "interrupt":
            raise KeyboardInterrupt()
        if failure == "length":
            return Response(good, expected=len(good) + 1)
        return Response(good[:-8])

    monkeypatch.setattr(cache_module, "urlopen", broken)
    with pytest.raises((OSError, ValueError, EOFError, KeyboardInterrupt)):
        cache_catalog(URL, tmp_path, refresh=refresh)
    assert not list(tmp_path.glob("*.part"))
    if refresh:
        assert cached.read_bytes() == good
        # A subsequent run can still use the previous snapshot without a network request.
        assert cache_catalog(URL, tmp_path) == cached
    else:
        assert not list(tmp_path.iterdir())


def test_local_catalog_does_not_create_cache(tmp_path):
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("path,size,mip_era\n")
    cache = tmp_path / "unused"
    assert cache_catalog(catalog, cache, refresh=True) == catalog
    assert not cache.exists()
