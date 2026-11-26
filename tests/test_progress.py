import logging
from threading import Event

import pytest

from c3s_data_pool import catalog as catalog_module
from c3s_data_pool import progress as progress_module
from c3s_data_pool.catalog import process_catalog
from c3s_data_pool.progress import Heartbeat


def test_heartbeat_reports_while_file_check_is_blocked(tmp_path, monkeypatch, caplog):
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("path,size,mip_era\nfile.nc,4,test\n")
    reported = Event()
    original_info = progress_module.LOG.info

    def capture(message, *args, **kwargs):
        original_info(message, *args, **kwargs)
        if "heartbeat:" in message and "checking source" in args:
            reported.set()

    def blocked_check(paths, relative, size, stats):
        assert reported.wait(timeout=2), "no heartbeat arrived during the pending file check"
        stats.checked += 1

    monkeypatch.setattr(progress_module.LOG, "info", capture)
    monkeypatch.setattr(catalog_module, "check_source", blocked_check)
    with caplog.at_level(logging.INFO):
        stats = process_catalog(
            "test",
            {"catalog": catalog, "source": tmp_path / "source"},
            build=True,
            apply=False,
            progress_every=10000,
            heartbeat_seconds=0.01,
        )
    assert not stats.failed
    assert stats.checked == 1
    assert "heartbeat: files=0/1 (0.0%) elapsed=" in caplog.text
    assert "stage=checking source" in caplog.text
    assert f"current={tmp_path / 'source/file.nc'}" in caplog.text
    assert "current_for=" in caplog.text


def test_heartbeat_stops_when_processing_raises():
    heartbeat = Heartbeat("test", interval=0.01)
    with pytest.raises(RuntimeError):
        with heartbeat:
            raise RuntimeError("processing failed")
    assert not heartbeat.thread.is_alive()


def test_console_updates_independently_of_log_heartbeat():
    rendered = Event()

    class Console:
        def render(self, name, state, elapsed):
            if state[0] == "checking file":
                rendered.set()

        def finish(self):
            pass

    with Heartbeat("test", interval=60, console=Console()) as heartbeat:
        heartbeat.update("checking file", "file.nc", completed=0, total=1)
        assert rendered.wait(timeout=2), "the bar did not update while the operation was pending"
    assert not heartbeat.thread.is_alive()
