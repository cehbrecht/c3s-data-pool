import csv
import gzip
import logging

import pytest

from c3s_data_pool import catalog as catalog_module
from c3s_data_pool.catalog import count_catalog_files, open_catalog, process_catalog


@pytest.mark.parametrize("build", [False, True])
def test_dataset_counts_use_distinct_versioned_directories(tmp_path, caplog, build):
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "size", "mip_era"])
        writer.writerows(
            [
                ("model/v1/a.nc", 1, "test"),
                ("model/v2/b.nc", 1, "test"),
                ("model/v1/c.nc", 1, "test"),  # Unsorted files in the same dataset.
                ("model/v1/a.nc", 1, "test"),  # Duplicate catalog entry.
                ("other/v1/d.nc", 1, "test"),
                ("../escape.nc", 1, "test"),
                ("invalid-size/file.nc", -1, "test"),
            ]
        )
    paths = {"catalog": catalog, "target": tmp_path / "target", "source": tmp_path / "source"}
    with caplog.at_level(logging.INFO):
        stats = process_catalog("test", paths, build=build, apply=False, progress_every=1)
    assert stats.files == 7
    assert stats.datasets == 3
    assert stats.invalid == 2
    assert stats.missing == 5
    assert stats.logical_bytes == 5
    assert stats.total_files == 7
    assert "test progress: files=0/7 (0.0%)" in caplog.text
    assert "test progress: files=1/7 (14.3%)" in caplog.text
    assert "test summary: files=7/7 (100.0%) datasets=3" in caplog.text
    assert not paths["target"].exists()


@pytest.mark.parametrize("suffix", [".csv", ".csv.gz"])
def test_count_csv_records_instead_of_lines(tmp_path, suffix):
    catalog = tmp_path / f"catalog{suffix}"
    contents = (
        b'path,size,mip_era,description\n\nfile.nc,1,test,"two\nlines"\n\nsecond.nc,2,test,ok\n'
    )
    catalog.write_bytes(gzip.compress(contents) if suffix == ".csv.gz" else contents)
    with open_catalog(catalog) as stream:
        assert count_catalog_files("test", stream) == 2


def test_count_failure_prevents_file_operations(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.csv"
    catalog.write_text('path,size,mip_era\n"unterminated')
    paths = {"catalog": catalog, "source": tmp_path / "source", "target": tmp_path / "target"}

    def forbidden(*args, **kwargs):
        pytest.fail("file processing started before the catalog was counted")

    monkeypatch.setattr(catalog_module, "process_row", forbidden)
    stats = process_catalog("test", paths, build=True, apply=True, progress_every=1)
    assert stats.failed
    assert stats.files == 0
    assert not paths["target"].exists()


@pytest.mark.parametrize("replacement", ["", "a.nc,1,test\nb.nc,1,test\n"])
def test_both_passes_use_same_open_snapshot(tmp_path, monkeypatch, replacement):
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("path,size,mip_era\na.nc,1,test\n")
    original_count = catalog_module.count_catalog_files

    def count_and_replace(name, stream):
        count = original_count(name, stream)
        fresh = tmp_path / "replacement.csv"
        fresh.write_text("path,size,mip_era\n" + replacement)
        fresh.replace(catalog)
        return count

    monkeypatch.setattr(catalog_module, "count_catalog_files", count_and_replace)
    paths = {"catalog": catalog, "target": tmp_path / "target"}
    stats = process_catalog("test", paths, build=False, apply=False, progress_every=1)
    assert stats.total_files == stats.files == 1
    assert stats.errors == 0
    assert stats.missing == 1
