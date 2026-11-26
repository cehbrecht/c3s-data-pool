"""Report activity without performing filesystem operations or blocking workers."""

import logging
import time
from datetime import timedelta
from threading import Event, Lock, Thread

LOG = logging.getLogger("c3s-data-pool")


class Heartbeat:
    def __init__(self, name, interval=15):
        self.name = name
        self.interval = interval
        self.started = time.monotonic()
        self.lock = Lock()
        self.stopped = Event()
        self.state = ("starting", "-", 0, 0, self.started)
        self.thread = Thread(target=self._run, name="catalog-heartbeat", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopped.set()
        self.thread.join()

    def update(self, stage, current="-", completed=0, total=0):
        with self.lock:
            self.state = (stage, str(current), completed, total, time.monotonic())

    def _run(self):
        while not self.stopped.wait(self.interval):
            with self.lock:
                stage, current, completed, total, active_since = self.state
            now = time.monotonic()
            files = (
                f"{completed}/{total} ({100 * completed / total:.1f}%)" if total else str(completed)
            )
            LOG.info(
                "%s heartbeat: files=%s elapsed=%s stage=%s current_for=%s current=%s",
                self.name,
                files,
                timedelta(seconds=int(now - self.started)),
                stage,
                timedelta(seconds=int(now - active_since)),
                current,
            )
