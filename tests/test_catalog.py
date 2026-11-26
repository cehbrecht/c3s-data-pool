import csv
import logging

import pytest

from c3s_data_pool.catalog import process_catalog


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
    assert "test summary: files=7 datasets=3" in caplog.text
    assert not paths["target"].exists()
