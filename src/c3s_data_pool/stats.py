"""Progress reporting and summary counters."""

import logging
from dataclasses import dataclass

LOG = logging.getLogger("c3s-data-pool")


@dataclass
class Stats:
    files: int = 0
    datasets: int = 0
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
        unit, divisor = ("TB", 10**12) if self.logical_bytes >= 10**12 else ("GB", 10**9)
        counts = " ".join(
            f"{key}={value}"
            for key, value in vars(self).items()
            if key not in {"files", "datasets", "logical_bytes"}
        )
        LOG.info(
            "%s %s: files=%d datasets=%d volume=%.2f %s %s",
            name,
            label,
            self.files,
            self.datasets,
            self.logical_bytes / divisor,
            unit,
            counts,
        )
