"""Report activity without performing filesystem operations or blocking workers."""

import logging
import time
from datetime import timedelta
from threading import Event, Lock, Thread

LOG = logging.getLogger("c3s-data-pool")


class Heartbeat:
    def __init__(self, name, interval=15, console=None):
        self.name = name
        self.interval = interval
        self.console = console
        self.started = time.monotonic()
        self.lock = Lock()
        self.stopped = Event()
        self.state = ("starting", "-", 0, 0, self.started)
        self.dataset_state = None
        self.thread = Thread(target=self._run, name="catalog-heartbeat", daemon=True)

    def __enter__(self):
        if self.console is not None:
            self.console.render(self.name, self.state, 0)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopped.set()
        self.thread.join()
        if self.console is not None:
            self.console.render(self.name, self.state, time.monotonic() - self.started)
            self.console.finish()

    def update(self, stage, current="-", completed=0, total=0):
        with self.lock:
            self.state = (stage, str(current), completed, total, time.monotonic())

    def set_dataset(
        self, directory=None, *, completed=0, total=0, seen=0, total_datasets=0, filename="-"
    ):
        with self.lock:
            self.dataset_state = (
                (directory, completed, total, seen, total_datasets, filename)
                if directory is not None
                else None
            )

    def _run(self):
        last_log = self.started
        tick = min(0.2, self.interval) if self.console is not None else self.interval
        while not self.stopped.wait(tick):
            with self.lock:
                state = self.state
                dataset = self.dataset_state
            now = time.monotonic()
            if self.console is not None:
                self.console.render(self.name, state, now - self.started)
            if now - last_log < self.interval:
                continue
            last_log = now
            stage, current, completed, total, active_since = state
            files = (
                f"{completed}/{total} ({100 * completed / total:.1f}%)" if total else str(completed)
            )
            if dataset is None:
                context = f"current={current}"
            else:
                directory, done, count, seen, total_datasets, filename = dataset
                context = (
                    f"datasets={seen}/{total_datasets} dataset={directory} "
                    f"dataset_files={done}/{count} file={filename}"
                )
            LOG.info(
                "%s heartbeat: files=%s elapsed=%s stage=%s current_for=%s %s",
                self.name,
                files,
                timedelta(seconds=int(now - self.started)),
                stage,
                timedelta(seconds=int(now - active_since)),
                context,
            )
