"""Progress reporting and summary counters."""

import logging
from dataclasses import dataclass

LOG = logging.getLogger("c3s-data-pool")


@dataclass
class Stats:
    rows: int = 0
    logical_bytes: int = 0
    created: int = 0
    planned: int = 0
    existing: int = 0
    verified: int = 0
    missing: int = 0
    size_mismatches: int = 0
    conflicts: int = 0
    invalid: int = 0
    hardlink_failures: int = 0
    errors: int = 0

    @property
    def failed(self):
        return any(
            (
                self.missing,
                self.size_mismatches,
                self.conflicts,
                self.invalid,
                self.hardlink_failures,
                self.errors,
            )
        )

    def report(self, name, label):
        counts = " ".join(f"{key}={value}" for key, value in vars(self).items())
        LOG.info("%s %s: %s logical_TiB=%.6f", name, label, counts, self.logical_bytes / 1024**4)
