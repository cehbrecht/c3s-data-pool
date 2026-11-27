import csv
import errno
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from c3s_data_pool import copying
from c3s_data_pool.cli import main


@pytest.fixture
def copy_pool(tmp_path, write_config, request):
    contents = getattr(request, "param", b"synthetic climate data")
    source = tmp_path / "source/model/v20260101/file.nc"
    source.parent.mkdir(parents=True)
    source.write_bytes(contents)
    source.chmod(0o444)
    target = tmp_path / "target/model/v20260101/file.nc"
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "size", "mip_era"])
        writer.writerow(["model/v20260101/file.nc", len(contents), "test"])
    config = tmp_path / "config.toml"
    write_config(
        config,
        {
            "collections": {
                "test": {
                    "catalog": "catalog.csv",
                    "source": "source",
                    "target": "target",
                }
            }
        },
    )
    return config, source, target, contents


def run(pool, *args, method="copy", command="build"):
    options = [f"--{method}"] if command == "build" and method is not None else []
    with patch("builtins.input", return_value="yes"):
        return main([command, "--config", str(pool[0]), *options, *args])


@pytest.mark.parametrize("copy_pool", [b"", b"synthetic climate data"], indirect=True)
def test_copy_and_repeat_build(copy_pool, caplog):
    _, source, destination, contents = copy_pool
    assert run(copy_pool, "--apply") == 0
    assert destination.read_bytes() == contents
    assert not source.samefile(destination)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o444
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns
    inode = destination.stat().st_ino
    assert run(copy_pool, "--apply") == 0
    assert destination.stat().st_ino == inode
    assert "existing=1" in caplog.text
    assert not list(destination.parent.glob(".c3s-copy-*.part"))


def test_copy_survives_source_removal(copy_pool):
    assert run(copy_pool, "--apply") == 0
    copy_pool[1].unlink()
    assert run(copy_pool, command="verify") == 0
    assert copy_pool[2].read_bytes() == copy_pool[3]


def test_copy_follows_source_symlink(copy_pool):
    source = copy_pool[1]
    real = source.parent / "replica.nc"
    source.rename(real)
    source.symlink_to(real)
    assert run(copy_pool, "--apply") == 0
    assert not copy_pool[2].is_symlink()
    assert not copy_pool[2].samefile(real)
    assert copy_pool[2].read_bytes() == copy_pool[3]


@pytest.mark.parametrize("method", [None, "hardlink"])
def test_default_and_explicit_hardlink_are_unchanged(copy_pool, method):
    assert run(copy_pool, "--apply", method=method) == 0
    assert copy_pool[1].samefile(copy_pool[2])


def test_copy_works_when_hardlink_to_original_is_denied(copy_pool, monkeypatch):
    original_link = os.link

    def protected_link(source, destination, **kwargs):
        if not Path(source).name.startswith(".c3s-copy-"):
            raise PermissionError(errno.EPERM, "source-owner hardlink protection")
        assert Path(source).parent == Path(destination).parent
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", protected_link)
    assert run(copy_pool, "--apply", method="hardlink") == 1
    assert not copy_pool[2].exists()
    assert run(copy_pool, "--apply") == 0
    assert copy_pool[2].read_bytes() == copy_pool[3]
    assert not copy_pool[2].samefile(copy_pool[1])


def test_copy_dry_run_does_not_copy_or_link(copy_pool, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run attempted to copy or hardlink")

    monkeypatch.setattr(copying, "copy_file", forbidden)
    monkeypatch.setattr(copying.shutil, "copyfileobj", forbidden)
    monkeypatch.setattr(os, "link", forbidden)
    assert run(copy_pool) == 0
    assert not copy_pool[2].parent.exists()


def test_copy_stages_distinguish_existing_files_from_transfers(copy_pool):
    _, source, destination, contents = copy_pool
    destination.parent.mkdir(parents=True)
    stages = []

    def report(stage, path):
        stages.append(stage)
        if stage == "publishing file":
            assert not destination.exists()
            assert path == destination

    assert copying.copy_file(source, destination, len(contents), source.stat(), on_stage=report)
    assert stages == [
        "checking destination",
        "opening source",
        "copying file",
        "flushing copy",
        "publishing file",
    ]
    stages.clear()
    assert not copying.copy_file(source, destination, len(contents), source.stat(), on_stage=report)
    assert stages == ["checking destination"]


@pytest.mark.parametrize("kind", ["wrong-size", "symlink", "directory"])
def test_copy_conflicts_are_untouched(copy_pool, kind):
    destination = copy_pool[2]
    destination.parent.mkdir(parents=True)
    if kind == "wrong-size":
        destination.write_bytes(b"wrong")
    elif kind == "symlink":
        destination.symlink_to(copy_pool[1])
    else:
        destination.mkdir()
    before = destination.lstat()
    assert run(copy_pool, "--apply") == 1
    assert destination.lstat() == before
    assert not list(destination.parent.glob(".c3s-copy-*.part"))


def test_existing_copies_are_accepted_by_catalog_size_only(copy_pool):
    destination = copy_pool[2]
    destination.parent.mkdir(parents=True)
    contents = b"x" * len(copy_pool[3])
    destination.write_bytes(contents)
    inode = destination.stat().st_ino
    assert run(copy_pool, "--apply") == 0
    assert destination.stat().st_ino == inode
    assert destination.read_bytes() == contents


@pytest.mark.parametrize(
    "error,code", [(OSError(errno.ENOSPC, "no space"), 1), (KeyboardInterrupt(), 130)]
)
def test_failed_copy_is_not_published_and_can_resume(copy_pool, monkeypatch, error, code):
    original_copy = copying.shutil.copyfileobj

    def fail(source, destination, **kwargs):
        # Even a full-size temporary file must not become a completed destination.
        destination.write(copy_pool[3])
        raise error

    monkeypatch.setattr(copying.shutil, "copyfileobj", fail)
    assert run(copy_pool, "--apply") == code
    assert not copy_pool[2].exists()
    assert not list(copy_pool[2].parent.glob(".c3s-copy-*.part"))
    monkeypatch.setattr(copying.shutil, "copyfileobj", original_copy)
    assert run(copy_pool, "--apply") == 0
    assert copy_pool[2].read_bytes() == copy_pool[3]


def test_source_change_during_copy_is_not_published(copy_pool, monkeypatch):
    original_copy = copying.shutil.copyfileobj

    def change(source, destination, **kwargs):
        original_copy(source, destination, **kwargs)
        copy_pool[1].chmod(0o644)
        copy_pool[1].write_bytes(b"changed source")

    monkeypatch.setattr(copying.shutil, "copyfileobj", change)
    assert run(copy_pool, "--apply") == 1
    assert not copy_pool[2].exists()
    assert not list(copy_pool[2].parent.glob(".c3s-copy-*.part"))


@pytest.mark.parametrize("failure", ["short-copy", "read-error"])
def test_copy_failure_is_logged_and_later_files_are_copied(copy_pool, monkeypatch, failure):
    config, source, destination, contents = copy_pool
    for name in ("first.nc", "later.nc"):
        (source.parent / name).write_bytes(contents)
    with (config.parent / "catalog.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "size", "mip_era"])
        for name in ("first.nc", "file.nc", "later.nc"):
            writer.writerow([f"model/v20260101/{name}", len(contents), "test"])
    original_copy = copying.shutil.copyfileobj

    def copy(input_stream, output, **kwargs):
        if Path(input_stream.name).name == "file.nc":
            output.write(contents[:1])
            if failure == "read-error":
                raise OSError(errno.EIO, "synthetic read error")
            return
        original_copy(input_stream, output, **kwargs)

    monkeypatch.setattr(copying.shutil, "copyfileobj", copy)
    log_file = config.parent / "session.log"
    assert run(copy_pool, "--apply", "--log-file", str(log_file)) == 1
    assert not destination.exists()
    assert not list(destination.parent.glob(".c3s-copy-*.part"))
    for name in ("first.nc", "later.nc"):
        assert (destination.parent / name).read_bytes() == contents
    log = log_file.read_text()
    assert "ERROR copy failed" in log
    assert "file.nc" in log
    assert "files=3/3 (100.0%)" in log
    assert "created=2" in log
    assert "copy_failures=1" in log
    if failure == "short-copy":
        assert f"expected={len(contents)} actual=1" in log


@pytest.mark.parametrize("matching", [False, True])
def test_copy_publish_never_overwrites_a_concurrent_destination(copy_pool, monkeypatch, matching):
    original_copy = copying.shutil.copyfileobj
    raced = copy_pool[3] if matching else b"conflict"

    def concurrent(source, destination, **kwargs):
        original_copy(source, destination, **kwargs)
        copy_pool[2].write_bytes(raced)

    monkeypatch.setattr(copying.shutil, "copyfileobj", concurrent)
    assert run(copy_pool, "--apply") == (0 if matching else 1)
    assert copy_pool[2].read_bytes() == raced
    assert not list(copy_pool[2].parent.glob(".c3s-copy-*.part"))


def test_copy_requires_confirmation(copy_pool, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "no")
    assert main(["build", "--config", str(copy_pool[0]), "--copy", "--apply"]) == 1
    assert "independent file copies" in capsys.readouterr().err
    assert not copy_pool[2].parent.exists()


@pytest.mark.parametrize("flags", [("--copy", "--hardlink"), ("--hardlink", "--copy")])
def test_copy_and_hardlink_are_mutually_exclusive(copy_pool, flags):
    with pytest.raises(SystemExit) as error:
        run(copy_pool, *flags, method=None)
    assert error.value.code == 2
    assert not copy_pool[2].parent.exists()
