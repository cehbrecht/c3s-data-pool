import csv
import os

import pytest

from c3s_data_pool.catalog import process_catalog
from c3s_data_pool.metadata import MetadataCache
from c3s_data_pool.pool import process_row
from c3s_data_pool.stats import Stats


@pytest.mark.parametrize("existing_pool", [False, True])
def test_shared_directories_do_not_repeat_metadata_walks(tmp_path, monkeypatch, existing_pool):
    source, target = tmp_path / "source", tmp_path / "target"
    dataset = "activity/institute/model/experiment/member/table/variable/grid/version"
    source_dir = source / dataset
    source_dir.mkdir(parents=True)
    if existing_pool:
        (target / dataset).mkdir(parents=True)
    catalog = tmp_path / "catalog.csv"
    with catalog.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "size", "mip_era"])
        for index in range(100):
            name = f"file-{index}.nc"
            (source_dir / name).write_bytes(b"data")
            if existing_pool:
                os.link(source_dir / name, target / dataset / name)
            writer.writerow([f"{dataset}/{name}", 4, "test"])

    calls = 0
    original_stat, original_lstat = os.stat, os.lstat

    def counted_stat(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_stat(*args, **kwargs)

    def counted_lstat(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_lstat(*args, **kwargs)

    monkeypatch.setattr(os, "stat", counted_stat)
    monkeypatch.setattr(os, "lstat", counted_lstat)
    stats = process_catalog(
        "test",
        {"catalog": catalog, "source": source, "target": target},
        build=True,
        apply=False,
        progress_every=10000,
    )
    assert not stats.failed
    assert stats.files == 100
    assert stats.existing == (100 if existing_pool else 0)
    assert stats.planned == (0 if existing_pool else 100)
    # Allow room for platform differences, but catch per-file directory walks.
    assert calls < 500


def test_source_file_metadata_is_not_cached(tmp_path):
    source = tmp_path / "file.nc"
    source.write_bytes(b"a")
    metadata = MetadataCache()
    _, first = metadata.source_file(source)
    source.write_bytes(b"longer")
    _, second = metadata.source_file(source)
    assert first.st_size == 1
    assert second.st_size == 6


def test_source_directory_symlink_is_resolved(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    source = tmp_path / "alias"
    source.symlink_to(real, target_is_directory=True)
    (real / "file.nc").write_bytes(b"data")
    resolved, info = MetadataCache().source_file(source / "file.nc")
    assert resolved == real / "file.nc"
    assert info.st_size == 4


def test_apply_rechecks_destination_directories_between_files(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "dataset").mkdir(parents=True)
    for name in ("first.nc", "second.nc"):
        (source / "dataset" / name).write_bytes(b"data")
    paths = {"source": source, "target": target}
    stats = Stats()
    metadata = MetadataCache()
    relative = (source / "dataset/first.nc").relative_to(source)
    process_row(paths, relative, 4, stats, build=True, apply=True, metadata=metadata)
    assert stats.created == 1

    (target / "dataset").rename(tmp_path / "original-destination")
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "dataset").symlink_to(outside, target_is_directory=True)
    process_row(
        paths, relative.with_name("second.nc"), 4, stats, build=True, apply=True, metadata=metadata
    )
    assert stats.conflicts == 1
    assert stats.created == 1
    assert not list(outside.iterdir())
