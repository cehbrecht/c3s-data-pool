import csv
import errno
import gzip
import io
import logging
import os
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from c3s_data_pool import cache as cache_module
from c3s_data_pool.cli import main
from c3s_data_pool.config import tomllib


@pytest.fixture
def pool(tmp_path, write_config):
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "not-created" / "pool"
    catalog = tmp_path / "files.csv.gz"
    config = tmp_path / "config.toml"
    write_config(
        config,
        {
            "collections": {
                "test": {
                    "source": "source",
                    "target": "not-created/pool",
                    "catalog": "files.csv.gz",
                }
            }
        },
    )

    def write(rows=None):
        if rows is None:
            rows = [("model/v20260101/file.nc", 4, "CMIP6")]
        with gzip.open(catalog, "wt", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["path", "size", "mip_era"])
            writer.writerows(rows)

    write()
    file = source / "model/v20260101/file.nc"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"data")
    return config, source, target, catalog, write


def run(pool, *args, command="build"):
    # Operation tests confirm apply; dedicated tests below exercise the prompt.
    with patch("builtins.input", return_value="yes"):
        return main([command, "--config", str(pool[0]), *args])


@pytest.mark.parametrize("args", [(), ("--dry-run",)])
def test_dry_run_never_writes(pool, monkeypatch, caplog, args):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run attempted a write")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(os, "link", forbidden)
    with caplog.at_level(logging.INFO):
        assert run(pool, *args) == 0
    assert not pool[2].parent.exists()
    assert "planned=1" in caplog.text
    assert "volume=0.00 GB" in caplog.text


def test_hardlink_and_repeated_build(pool, caplog):
    assert run(pool, "--apply") == 0
    source = pool[1] / "model/v20260101/file.nc"
    target = pool[2] / "model/v20260101/file.nc"
    assert source.samefile(target)
    inode = target.stat().st_ino
    with caplog.at_level(logging.INFO):
        assert run(pool, "--apply") == 0
    assert target.stat().st_ino == inode
    assert "existing=1" in caplog.text


def test_verify_without_source(pool, write_config):
    assert run(pool, "--apply") == 0
    (pool[1] / "model/v20260101/file.nc").unlink()
    # Verification also accepts a configuration without any source key.
    config = tomllib.loads(pool[0].read_text())
    del config["collections"]["test"]["source"]
    write_config(pool[0], config)
    assert run(pool, command="verify") == 0


@pytest.mark.parametrize("apply", [(), ("--apply",)])
def test_missing_source_and_resume(pool, apply):
    pool[4]([("missing.nc", 4, "CMIP6"), ("model/v20260101/file.nc", 4, "CMIP6")])
    assert run(pool, *apply) == 1
    (pool[1] / "missing.nc").write_bytes(b"more")
    assert run(pool, "--apply") == 0
    assert (pool[2] / "missing.nc").samefile(pool[1] / "missing.nc")


def test_source_size_mismatch(pool):
    pool[4]([("model/v20260101/file.nc", 5, "CMIP6")])
    assert run(pool, "--apply") == 1
    assert not pool[2].exists()


@pytest.mark.parametrize("kind", ["copy", "directory", "symlink", "dangling"])
def test_conflicts_never_overwritten(pool, kind):
    target = pool[2] / "model/v20260101/file.nc"
    target.parent.mkdir(parents=True)
    if kind == "copy":
        target.write_bytes(b"data")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(pool[1] / ("model/v20260101/file.nc" if kind == "symlink" else "absent"))
    before = target.lstat()
    assert run(pool, "--apply") == 1
    assert target.lstat() == before
    if kind == "copy":
        assert target.read_bytes() == b"data"


@pytest.mark.parametrize(
    "path",
    ["../escape", "/absolute", "a/../../escape", "a/./b", "a//b", "a/", "", "a\\b", "a\x00b"],
)
def test_invalid_paths(pool, path):
    # Write these deliberately invalid fields literally: Python 3.10's CSV
    # writer rejects NUL bytes before the catalog reader can inspect them.
    with gzip.open(pool[3], "wt", newline="") as stream:
        stream.write(f"path,size,mip_era\n{path},0,other\n")
    assert run(pool, "--apply") == 1
    assert not pool[2].exists()


def test_symlink_source_resolves_to_regular_hardlink(pool):
    real = pool[1].parent / "actual-data"
    real.write_bytes(b"data")
    source = pool[1] / "model/v20260101/file.nc"
    source.unlink()
    source.symlink_to(real)
    assert run(pool, "--apply") == 0
    target = pool[2] / "model/v20260101/file.nc"
    assert not target.is_symlink()
    assert target.samefile(real)
    source.unlink()
    real.unlink()
    assert run(pool, command="verify") == 0


def test_destination_parent_symlink_rejected(pool, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    pool[2].mkdir(parents=True)
    (pool[2] / "model").symlink_to(outside, target_is_directory=True)
    assert run(pool, "--apply") == 1
    assert not list(outside.iterdir())
    assert run(pool, command="verify") == 1


@pytest.mark.parametrize("operation", ["build", "verify"])
def test_parent_file_conflict(pool, operation):
    pool[2].parent.mkdir(parents=True)
    pool[2].write_bytes(b"untouched")
    args = ("--apply",) if operation == "build" else ()
    assert run(pool, *args, command=operation) == 1
    assert pool[2].read_bytes() == b"untouched"


def test_hardlink_failure(pool, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", fail)
    assert run(pool, "--apply") == 1
    assert "hardlink failed" in caplog.text


def test_missing_and_wrong_size_destination(pool):
    assert run(pool, command="verify") == 1
    assert not pool[2].exists()
    target = pool[2] / "model/v20260101/file.nc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong-size")
    assert run(pool, command="verify") == 1


@pytest.mark.parametrize("size", ["-1", "1.0", "NaN", "", " 4", "٤"])
def test_invalid_sizes(pool, size):
    pool[4]([("file", size, "anything")])
    assert run(pool, "--apply") == 1


@pytest.mark.parametrize(
    "contents",
    [
        "path,size\nx,1\n",
        "path,size,mip_era\n",
        "path,size,mip_era\nx,4\n",
        "path,size,mip_era\nx,4,a,extra\n",
    ],
)
def test_malformed_catalog(pool, contents):
    with gzip.open(pool[3], "wt") as stream:
        stream.write(contents)
    assert run(pool) == 1


def test_truncated_gzip(pool):
    pool[3].write_bytes(pool[3].read_bytes()[:-8])
    assert run(pool) == 1


def test_collection_selection_and_progress(pool, caplog, write_config):
    config = tomllib.loads(pool[0].read_text())
    config["collections"]["unused"] = {
        "catalog": "missing.csv.gz",
        "target": "other",
        "source": "source",
    }
    write_config(pool[0], config)
    with caplog.at_level(logging.INFO):
        assert run(pool, "--collection", "test", "--progress-every", "1") == 0
    assert "test progress:" in caplog.text
    assert run(pool, "--collection", "unknown") == 2
    assert run(pool) == 1


def test_same_roots_rejected(pool, write_config):
    config = tomllib.loads(pool[0].read_text())
    config["collections"]["test"]["target"] = "source"
    write_config(pool[0], config)
    assert run(pool, "--apply") == 2


def test_mutually_exclusive_modes(pool):
    with pytest.raises(SystemExit) as exc:
        run(pool, "--apply", "--dry-run")
    assert exc.value.code == 2


def test_concurrent_matching_link_is_restartable(pool, monkeypatch):
    original_link = os.link

    def race(source, target, **kwargs):
        original_link(source, target, **kwargs)
        raise FileExistsError(errno.EEXIST, "another builder won")

    monkeypatch.setattr(os, "link", race)
    assert run(pool, "--apply") == 0


@pytest.mark.parametrize("kind", ["broken", "loop", "directory"])
def test_unusable_source(pool, kind):
    source = pool[1] / "model/v20260101/file.nc"
    source.unlink()
    if kind == "directory":
        source.mkdir()
    else:
        source.symlink_to(source if kind == "loop" else source.parent / "absent")
    assert run(pool, "--apply") == 1
    assert not pool[2].exists()


def test_verify_rejects_symlink(pool):
    target = pool[2] / "model/v20260101/file.nc"
    target.parent.mkdir(parents=True)
    target.symlink_to(pool[1] / "model/v20260101/file.nc")
    assert run(pool, command="verify") == 1


def test_readonly_directory_dry_run(pool):
    pool[2].parent.mkdir()
    pool[2].parent.chmod(0o555)
    try:
        assert run(pool) == 0
        assert not pool[2].exists()
    finally:
        pool[2].parent.chmod(0o755)


def test_invalid_config(pool):
    pool[0].write_text("collections = []\n")
    assert run(pool) == 2


def test_zero_size_file(pool):
    (pool[1] / "empty").touch()
    pool[4]([("empty", 0, "generic")])
    assert run(pool, "--apply") == 0
    assert run(pool, command="verify") == 0


@pytest.fixture
def remote_catalog(pool, monkeypatch, write_config):
    monkeypatch.setenv("XDG_CACHE_HOME", str(pool[0].parent / "cache-root"))
    url = "https://example.test/catalog.csv.gz?version=pinned"
    config = tomllib.loads(pool[0].read_text())
    config["collections"]["test"]["catalog"] = url
    write_config(pool[0], config)
    responses = []

    class StreamingResponse(io.BytesIO):
        headers = {}

        def read(self, size=-1):
            assert size >= 0, "remote catalog must not be read in one unbounded request"
            return super().read(size)

    def fetch(location, *, timeout):
        assert location == url
        assert timeout == 30
        response = StreamingResponse(pool[3].read_bytes())
        responses.append(response)
        return response

    monkeypatch.setattr(cache_module, "urlopen", fetch)
    return responses


def test_remote_dry_run_writes_only_cache(pool, remote_catalog, monkeypatch):
    original_mkdir = Path.mkdir

    def cache_mkdir(path, *args, **kwargs):
        cache_root = pool[0].parent / "cache-root"
        assert path == cache_root or cache_root in path.parents
        return original_mkdir(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("remote dry-run attempted a hardlink")

    monkeypatch.setattr(Path, "mkdir", cache_mkdir)
    monkeypatch.setattr(os, "link", forbidden)
    assert run(pool) == 0
    assert not pool[2].parent.exists()
    assert len(remote_catalog) == 1
    assert all(response.closed for response in remote_catalog)


def test_remote_build_repeat_and_verify_without_source(pool, remote_catalog):
    assert run(pool, "--apply") == 0
    assert run(pool, "--apply") == 0
    source = pool[1] / "model/v20260101/file.nc"
    assert source.samefile(pool[2] / "model/v20260101/file.nc")
    source.unlink()
    assert run(pool, command="verify") == 0
    assert len(remote_catalog) == 1
    assert all(response.closed for response in remote_catalog)


def test_cli_cache_directory_and_refresh(pool, remote_catalog):
    chosen = pool[0].parent / "chosen-cache"
    assert run(pool, "--cache-dir", str(chosen)) == 0
    assert len(list(chosen.glob("*.csv.gz"))) == 1
    assert run(pool, "--cache-dir", str(chosen)) == 0
    assert len(remote_catalog) == 1
    assert run(pool, "--cache-dir", str(chosen), "--refresh-catalog") == 0
    assert len(remote_catalog) == 2
    assert not (pool[0].parent / "cache-root").exists()
    assert not pool[2].exists()


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://example.test/catalog.csv.gz", 404, "Not Found", {}, None),
        URLError("DNS unavailable"),
        TimeoutError("timed out"),
        IncompleteRead(b"partial", 100),
    ],
)
def test_remote_failure_returns_nonzero(pool, remote_catalog, monkeypatch, caplog, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(cache_module, "urlopen", fail)
    assert run(pool) == 1
    assert "catalog failed" in caplog.text
    assert not pool[2].exists()


@pytest.mark.parametrize(
    "contents",
    [
        b"not gzip",
        gzip.compress(b"path,size\nfile,1\n"),
        gzip.compress(b"path,size,mip_era\nfile,1,x\n")[:-8],
    ],
)
def test_remote_invalid_catalog_closes_response(pool, remote_catalog, contents):
    pool[3].write_bytes(contents)
    assert run(pool) == 1
    assert remote_catalog[0].closed


@pytest.mark.parametrize(
    "location",
    [
        "http://example.test/catalog.csv.gz",
        "ftp://example.test/catalog.csv.gz",
        "https:///catalog.csv.gz",
        "https://example.test/catalog.csv",
    ],
)
def test_invalid_catalog_url(pool, location, write_config):
    config = tomllib.loads(pool[0].read_text())
    config["collections"]["test"]["catalog"] = location
    write_config(pool[0], config)
    assert run(pool) == 2


def test_absolute_local_catalog(pool, write_config):
    config = tomllib.loads(pool[0].read_text())
    config["collections"]["test"]["catalog"] = str(pool[3])
    write_config(pool[0], config)
    assert run(pool) == 0


@pytest.mark.parametrize("answer", ["y", "yes", "YES", " Yes "])
def test_apply_requires_positive_confirmation(pool, monkeypatch, capsys, answer):
    monkeypatch.setattr("builtins.input", lambda: answer)
    assert main(["build", "--config", str(pool[0]), "--apply"]) == 0
    prompt = capsys.readouterr().err
    assert "Continue? [y/N]" in prompt
    assert str(pool[1]) in prompt
    assert str(pool[2]) in prompt
    assert (pool[2] / "model/v20260101/file.nc").samefile(pool[1] / "model/v20260101/file.nc")


@pytest.mark.parametrize("answer", ["n", "no", "", "maybe"])
def test_declined_apply_does_not_read_catalog_or_write(pool, remote_catalog, monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda: answer)
    assert main(["build", "--config", str(pool[0]), "--apply"]) == 1
    assert not pool[2].parent.exists()
    assert not remote_catalog


@pytest.mark.parametrize(
    "error,code", [(EOFError(), 1), (OSError("no stdin"), 1), (KeyboardInterrupt(), 130)]
)
def test_unavailable_confirmation_cancels_apply(pool, monkeypatch, error, code):
    def interrupted():
        raise error

    monkeypatch.setattr("builtins.input", interrupted)
    assert main(["build", "--config", str(pool[0]), "--apply"]) == code
    assert not pool[2].parent.exists()


@pytest.mark.parametrize("command", ["build", "verify"])
def test_readonly_commands_never_prompt(pool, monkeypatch, command):
    def forbidden():
        pytest.fail("read-only command requested confirmation")

    monkeypatch.setattr("builtins.input", forbidden)
    expected = 0 if command == "build" else 1
    assert main([command, "--config", str(pool[0])]) == expected


def test_quick_scan_never_checks_destination_or_prompts(pool, monkeypatch, caplog):
    from c3s_data_pool import catalog as catalog_module

    original_resolve = Path.resolve

    def resolve_config_only(path, *args, **kwargs):
        assert path == pool[0], "quick mode resolved a filesystem root"
        return original_resolve(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("quick mode attempted a full check, write or prompt")

    monkeypatch.setattr(Path, "resolve", resolve_config_only)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(catalog_module, "process_row", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    monkeypatch.setattr(os, "link", forbidden)
    with caplog.at_level(logging.INFO):
        assert main(["build", "--config", str(pool[0]), "--quick"]) == 0
    assert "mode=quick" in caplog.text
    assert "checked=1" in caplog.text
    assert "planned=0" in caplog.text
    assert "not checked" in caplog.text
    assert not pool[2].exists()


@pytest.mark.parametrize("problem", ["missing", "size", "directory", "traversal"])
def test_quick_scan_reports_failures(pool, problem):
    source = pool[1] / "model/v20260101/file.nc"
    if problem == "missing":
        source.unlink()
    elif problem == "size":
        source.write_bytes(b"wrong size")
    elif problem == "directory":
        source.unlink()
        source.mkdir()
    else:
        pool[4]([("../escape", 4, "test")])
    assert run(pool, "--quick") == 1
    assert not pool[2].exists()


@pytest.mark.parametrize("broken", [False, True])
def test_quick_source_symlinks(pool, broken):
    source = pool[1] / "model/v20260101/file.nc"
    source.unlink()
    real = pool[1] / "real"
    if not broken:
        real.write_bytes(b"data")
    source.symlink_to(real)
    assert run(pool, "--quick") == (1 if broken else 0)


def test_quick_skips_destination_conflicts(pool):
    destination = pool[2] / "model/v20260101/file.nc"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"independent copy")
    assert run(pool, "--quick") == 0
    assert run(pool) == 1


def test_quick_cannot_apply(pool):
    with pytest.raises(SystemExit) as error:
        run(pool, "--quick", "--apply")
    assert error.value.code == 2
    assert not pool[2].exists()


@pytest.mark.parametrize("interval", ["0", "-1"])
def test_heartbeat_interval_must_be_positive(pool, interval):
    with pytest.raises(SystemExit) as error:
        run(pool, "--heartbeat-seconds", interval)
    assert error.value.code == 2
