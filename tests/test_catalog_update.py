import csv
import gzip
import os
from pathlib import Path

import pytest

from c3s_data_pool import catalog_update
from c3s_data_pool.cli import main


def write_catalog(path, columns, rows):
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_catalog(path):
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def run(catalog, source, output, *options):
    return main(
        [
            "update-catalog",
            "--catalog",
            str(catalog),
            "--source",
            str(source),
            "--output",
            str(output),
            "--mip-era",
            "CMIP5",
            "--batch",
            *options,
        ]
    )


@pytest.mark.parametrize("input_suffix", [".csv", ".csv.gz"])
@pytest.mark.parametrize("output_suffix", [".csv", ".csv.gz"])
@pytest.mark.parametrize("existing_columns", [False, True])
def test_update_preserves_rows_columns_and_input(
    tmp_path, input_suffix, output_suffix, existing_columns
):
    source = tmp_path / "pool"
    source.mkdir()
    (source / "file.nc").write_bytes(b"data")
    (source / "empty.nc").touch()
    (source / "linked.nc").symlink_to(source / "file.nc")
    columns = ["ds_id", "path", "description"]
    rows = [
        {"ds_id": "one", "path": "file.nc", "description": 'quoted, "value"\nand newline'},
        {"ds_id": "two", "path": "empty.nc", "description": ""},
        {"ds_id": "three", "path": "linked.nc", "description": "symlink"},
        {"ds_id": "one", "path": "file.nc", "description": "duplicate path"},
    ]
    if existing_columns:
        columns = ["size", "mip_era", *columns]
        for index, row in enumerate(rows):
            row.update(size="" if index % 2 else "999", mip_era="old")
    catalog = tmp_path / f"input{input_suffix}"
    output = tmp_path / f"new/output{output_suffix}"
    write_catalog(catalog, columns, rows)
    before = catalog.read_bytes()
    info = (source / "file.nc").stat()
    assert run(catalog, source, output) == 0
    fields, updated = read_catalog(output)
    assert fields == columns + [key for key in ("size", "mip_era") if key not in columns]
    assert len(updated) == len(rows)
    for old, new, size in zip(rows, updated, (4, 0, 4, 4)):
        assert new == {**old, "size": str(size), "mip_era": "CMIP5"}
    assert catalog.read_bytes() == before
    assert (source / "file.nc").stat() == info
    assert not list(output.parent.glob(".c3s-catalog-*.part"))


def test_updated_catalog_can_build_and_verify_pool(tmp_path, write_config):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.nc").write_bytes(b"data")
    catalog = tmp_path / "input.csv"
    output = tmp_path / "updated.csv.gz"
    write_catalog(
        catalog, ["path", "size", "project"], [{"path": "file.nc", "size": "", "project": "CMIP5"}]
    )
    assert run(catalog, source, output) == 0
    config = tmp_path / "config.toml"
    write_config(
        config,
        {
            "collections": {
                "cmip5": {"catalog": output.name, "source": "source", "target": "target"}
            }
        },
    )
    assert main(["build", "--config", str(config), "--hardlink", "--apply", "--batch"]) == 0
    assert (tmp_path / "target/file.nc").samefile(source / "file.nc")
    (source / "file.nc").unlink()
    assert main(["verify", "--config", str(config), "--batch"]) == 0


def test_all_row_errors_are_reported_without_publishing_partial_catalog(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "valid.nc").write_bytes(b"data")
    (source / "directory").mkdir()
    (source / "broken.nc").symlink_to(source / "absent.nc")
    catalog = tmp_path / "input.csv"
    rows = [
        {"path": path, "size": "999"}
        for path in ("missing.nc", "valid.nc", "../escape.nc", "directory", "broken.nc", "valid.nc")
    ]
    write_catalog(catalog, ["path", "size"], rows)
    before = catalog.read_bytes()
    output = tmp_path / "output.csv.gz"
    log_file = tmp_path / "update.log"
    assert run(catalog, source, output, "--log-file", str(log_file)) == 1
    assert catalog.read_bytes() == before
    assert not output.exists()
    assert not list(tmp_path.glob(".c3s-catalog-*.part"))
    log = log_file.read_text()
    assert "missing source:" in log
    assert "invalid catalog entry:" in log
    assert "source is not a regular file:" in log
    assert "files=6/6 (100.0%)" in log
    assert "checked=2 missing=2" in log
    assert "output was not published" in log


@pytest.mark.parametrize("kind", ["file", "symlink", "input", "hardlink"])
def test_existing_output_is_never_overwritten(tmp_path, monkeypatch, kind):
    catalog = tmp_path / "input.csv"
    catalog.write_text("path\nfile.nc\n")
    output = tmp_path / "output.csv"
    if kind == "input":
        output = catalog
    elif kind == "symlink":
        output.symlink_to(catalog)
    elif kind == "hardlink":
        os.link(catalog, output)
    else:
        output.write_text("existing")
    before = output.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("existing output should be rejected before opening the input")

    monkeypatch.setattr(catalog_update, "cache_catalog", forbidden)
    assert run(catalog, tmp_path / "source", output) == 1
    assert output.read_bytes() == before


def test_interrupted_update_removes_temporary_catalog(tmp_path, monkeypatch):
    catalog = tmp_path / "input.csv"
    catalog.write_text("path\nfile.nc\n")
    output = tmp_path / "output.csv"
    original_stat = Path.stat

    def interrupted(path, *args, **kwargs):
        if path == tmp_path / "source/file.nc":
            raise KeyboardInterrupt()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", interrupted)
    assert run(catalog, tmp_path / "source", output) == 130
    assert not output.exists()
    assert not list(tmp_path.glob(".c3s-catalog-*.part"))


def test_publish_race_does_not_overwrite_new_output(tmp_path, monkeypatch):
    catalog = tmp_path / "input.csv"
    catalog.write_text("path\nfile.nc\n")
    (tmp_path / "file.nc").write_bytes(b"data")
    output = tmp_path / "output.csv"

    def concurrent(*args, **kwargs):
        output.write_bytes(b"concurrent file")
        raise FileExistsError("destination created by another process")

    monkeypatch.setattr(os, "link", concurrent)
    assert run(catalog, tmp_path, output) == 1
    assert output.read_bytes() == b"concurrent file"
    assert not list(tmp_path.glob(".c3s-catalog-*.part"))


@pytest.mark.parametrize(
    "contents",
    ["size\n4\n", "path,path\na,b\n", "path\n", 'path\n"unterminated', "path,extra\na.nc\n"],
)
def test_malformed_catalog_does_not_publish(tmp_path, contents):
    catalog = tmp_path / "input.csv"
    catalog.write_text(contents)
    output = tmp_path / "output.csv"
    assert run(catalog, tmp_path, output) == 1
    assert not output.exists()
    assert catalog.read_text() == contents


def test_remote_catalog_uses_existing_cache_workflow(tmp_path, monkeypatch):
    catalog = tmp_path / "cached.csv.gz"
    write_catalog(catalog, ["path"], [{"path": "file.nc"}])
    (tmp_path / "file.nc").write_bytes(b"data")
    url = "https://example.test/catalog.csv.gz"
    calls = []

    def cached(location, cache_dir, *, refresh):
        calls.append((location, cache_dir, refresh))
        return catalog

    monkeypatch.setattr(catalog_update, "cache_catalog", cached)
    assert run(url, tmp_path, tmp_path / "output.csv", "--refresh-catalog") == 0
    assert calls == [(url, None, True)]


@pytest.mark.parametrize("target", ["input", "output", "input-hardlink"])
def test_log_file_cannot_modify_catalogs(tmp_path, target):
    catalog = tmp_path / "input.csv"
    catalog.write_text("path\nfile.nc\n")
    output = tmp_path / "output.csv"
    log_file = catalog if target == "input" else output
    if target == "input-hardlink":
        log_file = tmp_path / "log.csv"
        os.link(catalog, log_file)
    with pytest.raises(SystemExit) as error:
        run(catalog, tmp_path, output, "--log-file", str(log_file))
    assert error.value.code == 2
    assert catalog.read_text() == "path\nfile.nc\n"
    assert not output.exists()
