import logging

import pytest

from c3s_data_pool.stats import Stats


@pytest.mark.parametrize(
    "size,volume",
    [
        (0, "0.00 GB"),
        (1_500_000_000, "1.50 GB"),
        (999_000_000_000, "999.00 GB"),
        (1_000_000_000_000, "1.00 TB"),
        (1_612_094_073_214, "1.61 TB"),
    ],
)
def test_readable_logical_volume(size, volume, caplog):
    stats = Stats(files=1, logical_bytes=size)
    with caplog.at_level(logging.INFO):
        stats.report("pool", "progress")
    assert f"volume={volume}" in caplog.text
    assert "logical_bytes=" not in caplog.text
    assert "logical_TiB=" not in caplog.text
    assert stats.logical_bytes == size
