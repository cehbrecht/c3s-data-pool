import io
import logging
import sys

import pytest

from c3s_data_pool.output import ProgressBar, RunOutput


def test_progress_bar_reuses_console_line():
    stream = io.StringIO()
    bar = ProgressBar(stream)
    bar.render("pool", ("checking file", "a.nc", 1, 4, 0), 12)
    bar.render("pool", ("checking file", "b.nc", 2, 4, 0), 13)
    bar.finish()
    output = stream.getvalue()
    assert "25.0% 1/4" in output
    assert "50.0% 2/4" in output
    assert output.count("\r") == 2
    assert output.count("\n") == 1
    assert "0:00:13" in output


def test_detailed_logs_stay_out_of_console(tmp_path, capsys):
    path = tmp_path / "run.log"
    with RunOutput(path, "build") as output:
        logging.getLogger("c3s-data-pool").info("detailed progress")
        output.finish(0, "Dry-run")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Dry-run completed. Log: {path}\n"
    assert "INFO detailed progress" in path.read_text()


def test_log_handler_is_closed_after_failure(tmp_path):
    output = RunOutput(tmp_path / "run.log", "build")
    logger = logging.getLogger("c3s-data-pool")
    level = logger.level
    with pytest.raises(RuntimeError):
        with output:
            raise RuntimeError("failed")
    assert output.handler not in logger.handlers
    assert output.handler.stream is None
    assert logger.level == level


def test_explicit_log_file_appends(tmp_path):
    path = tmp_path / "run.log"
    for number in (1, 2):
        with RunOutput(path, "build"):
            logging.getLogger("c3s-data-pool").info("run %d", number)
    contents = path.read_text()
    assert contents.count("run 1") == contents.count("run 2") == 1


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("mode", ["verbose", "silent"])
def test_explicit_console_modes_keep_file_logs(tmp_path, monkeypatch, capsys, terminal, mode):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: terminal)
    path = tmp_path / "run.log"
    logger = logging.getLogger("c3s-data-pool")
    with RunOutput(path, "build", **{mode: True}) as output:
        assert output.console is None
        logger.info("detailed progress")
        logger.error("synthetic failure")
        output.finish(1, "Apply")
    captured = capsys.readouterr()
    assert captured.out == ""
    if mode == "silent":
        assert captured.err == ""
    else:
        assert "INFO detailed progress" in captured.err
        assert "ERROR synthetic failure" in captured.err
        assert "exit 1" in captured.err
        assert "\r" not in captured.err
    assert "INFO detailed progress" in path.read_text()
    assert "ERROR synthetic failure" in path.read_text()
    assert output.stream_handler not in logger.handlers


def test_verbose_handler_is_removed_after_failure(tmp_path):
    output = RunOutput(tmp_path / "run.log", "build", verbose=True)
    with pytest.raises(RuntimeError), output:
        raise RuntimeError("failed")
    assert output.stream_handler not in output.logger.handlers
