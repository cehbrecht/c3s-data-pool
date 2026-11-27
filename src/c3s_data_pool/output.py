"""Keep detailed logs on disk and a single updating line on the terminal."""

import logging
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path


class ProgressBar:
    def __init__(self, stream):
        self.stream = stream
        self.width = shutil.get_terminal_size(fallback=(100, 20)).columns - 1
        self.previous_width = 0
        self.frame = 0

    def render(self, name, state, elapsed):
        stage, _, completed, total, _ = state
        spinner = "|/-\\"[self.frame % 4]
        self.frame += 1
        if total:
            filled = min(20, 20 * completed // total)
            bar = "#" * filled + "-" * (20 - filled)
            prefix = f"{name} [{bar}] {100 * completed / total:5.1f}% {completed}/{total}"
        else:
            prefix = f"{name} [{spinner:^20}]"
        text = f"{prefix} {timedelta(seconds=int(elapsed))} {spinner} {stage}"
        text = text[: max(1, self.width)]
        self.stream.write("\r" + text.ljust(self.previous_width))
        self.stream.flush()
        self.previous_width = len(text)

    def finish(self):
        if self.previous_width:
            self.stream.write("\n")
            self.stream.flush()
            self.previous_width = 0


class RunOutput:
    def __init__(self, log_file, command, *, verbose=False, silent=False):
        if log_file is None:
            state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            log_file = state / "c3s-data-pool/logs" / f"{command}-{stamp}-{os.getpid()}.log"
        self.log_file = Path(log_file).expanduser().absolute()
        if not self.log_file.parent.is_dir():
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.handler = logging.FileHandler(self.log_file, encoding="utf-8")
        self.handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S %z",
            )
        )
        self.logger = logging.getLogger("c3s-data-pool")
        self.old_level = self.logger.level
        self.silent = silent
        self.stream_handler = logging.StreamHandler(sys.stderr) if verbose else None
        if self.stream_handler is not None:
            self.stream_handler.setFormatter(self.handler.formatter)
        self.console = (
            ProgressBar(sys.stderr) if not (verbose or silent) and sys.stderr.isatty() else None
        )

    def __enter__(self):
        self.logger.addHandler(self.handler)
        if self.stream_handler is not None:
            self.logger.addHandler(self.stream_handler)
        self.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        if self.console is not None:
            self.console.finish()
        self.logger.removeHandler(self.handler)
        self.handler.close()
        if self.stream_handler is not None:
            self.logger.removeHandler(self.stream_handler)
            self.stream_handler.close()
        self.logger.setLevel(self.old_level)

    def finish(self, code, mode):
        if self.silent:
            return
        if self.console is not None:
            self.console.finish()
        status = (
            f"{mode} completed" if code == 0 else f"{mode} incomplete or cancelled (exit {code})"
        )
        print(f"{status}. Log: {self.log_file}", file=sys.stderr)
