import io
import logging

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
