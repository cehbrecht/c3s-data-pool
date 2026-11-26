"""Streaming catalog processing; no data files are opened for writing."""

import argparse
import csv
from dataclasses import dataclass
import gzip
import logging
import os
from pathlib import Path, PurePosixPath
import stat
import time
import zlib

import yaml

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
        return any((self.missing, self.size_mismatches, self.conflicts,
                    self.invalid, self.hardlink_failures, self.errors))

    def report(self, name, label):
        counts = " ".join(f"{key}={value}" for key, value in vars(self).items())
        LOG.info("%s %s: %s logical_TiB=%.6f", name, label, counts,
                 self.logical_bytes / 1024**4)


def relative_path(value):
    """Accept only unambiguous POSIX paths beneath the configured roots."""
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("empty path, NUL or backslash")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("path must be relative without empty, '.' or '..' components")
    return Path(*path.parts)


def load_config(filename, selected, build):
    config_path = Path(filename).resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    collections = config.get("collections") if isinstance(config, dict) else None
    if not isinstance(collections, dict) or not collections:
        raise ValueError("configuration requires a non-empty collections mapping")
    if selected:
        unknown = set(selected) - collections.keys()
        if unknown:
            raise ValueError(f"unknown collections: {', '.join(sorted(unknown))}")
    result = []
    for name, values in collections.items():
        if selected and name not in selected:
            continue
        if not isinstance(name, str) or not isinstance(values, dict):
            raise ValueError("each collection must have a string name and a mapping")
        paths = {}
        for key in (("catalog", "target", "source") if build else ("catalog", "target")):
            value = values.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: {key} must be a non-empty local path")
            path = Path(value).expanduser()
            # Resolve configured roots, but preserve catalog paths lexically.
            paths[key] = (config_path.parent / path).absolute()
            if key != "catalog":
                paths[key] = paths[key].resolve()
        if not str(paths["catalog"]).endswith(".csv.gz"):
            raise ValueError(f"{name}: catalog must be a local .csv.gz file")
        if build and paths["source"] == paths["target"]:
            raise ValueError(f"{name}: source and target must be different directories")
        result.append((name, paths))
    return result


def destination_stat(root, relative):
    """Reject destination symlinks, including dangling links and parent links."""
    current = root
    for part in (None, *relative.parts[:-1]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"destination parent is not a real directory: {current}")
    try:
        info = (root / relative).lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("destination exists but is not a regular file (symlinks forbidden)")
    return info


def same_file(first, second):
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def process_row(paths, relative, size, stats, *, build, apply):
    destination = paths["target"] / relative
    try:
        existing = destination_stat(paths["target"], relative)
    except (ValueError, NotADirectoryError) as exc:
        stats.conflicts += 1
        LOG.error("conflict %s: %s", destination, exc)
        return
    if not build:
        if existing is None:
            stats.missing += 1
            LOG.error("missing destination: %s", destination)
        elif existing.st_size != size:
            stats.size_mismatches += 1
            LOG.error("destination size mismatch %s: expected=%d actual=%d",
                      destination, size, existing.st_size)
        else:
            stats.verified += 1
        return

    source = paths["source"] / relative
    try:
        source = source.resolve(strict=True)
        source_info = source.stat()
    except FileNotFoundError:
        stats.missing += 1
        LOG.error("missing source: %s", source)
        return
    if not stat.S_ISREG(source_info.st_mode):
        stats.conflicts += 1
        LOG.error("source is not a regular file: %s", source)
        return
    if source_info.st_size != size:
        stats.size_mismatches += 1
        LOG.error("source size mismatch %s: expected=%d actual=%d",
                  source, size, source_info.st_size)
        return
    if source == destination:
        stats.conflicts += 1
        LOG.error("source resolves to destination; no independent link: %s", source)
        return
    if existing is not None:
        if same_file(existing, source_info) and existing.st_size == size:
            stats.existing += 1
        else:
            stats.conflicts += 1
            LOG.error("conflict: destination is not the expected hardlink: %s", destination)
        return
    if not apply:
        # Inspect the nearest existing ancestor without creating directories.
        ancestor = destination.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if ancestor.stat().st_dev != source_info.st_dev:
            stats.hardlink_failures += 1
            LOG.error("hardlink requires the same filesystem: %s -> %s", source, destination)
        else:
            stats.planned += 1
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after mkdir; link itself never replaces an existing name.
        destination_stat(paths["target"], relative)
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            concurrent = destination_stat(paths["target"], relative)
            if concurrent is not None and same_file(concurrent, source_info) and concurrent.st_size == size:
                stats.existing += 1
                return
            raise ValueError("destination appeared and is not the expected hardlink")
        linked = destination.lstat()
        if not stat.S_ISREG(linked.st_mode) or not same_file(linked, source_info) or linked.st_size != size:
            raise ValueError("new link failed inode/device/size validation; inspect destination")
        stats.created += 1
    except (OSError, ValueError) as exc:
        stats.hardlink_failures += 1
        LOG.error("hardlink failed %s -> %s: %s", source, destination, exc)


def process_catalog(name, paths, *, build, apply, progress_every):
    stats = Stats()
    last_report = time.monotonic()
    try:
        with gzip.open(paths["catalog"], "rt", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            required = {"path", "size", "mip_era"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("catalog requires path, size and mip_era columns")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("catalog has duplicate column names")
            for row in reader:
                stats.rows += 1
                try:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("row does not match catalog header")
                    relative = relative_path(row["path"])
                    if not row["size"].isascii() or not row["size"].isdigit():
                        raise ValueError("size must be a non-negative integer in bytes")
                    size = int(row["size"])
                except ValueError as exc:
                    stats.invalid += 1
                    LOG.error("%s row %d: invalid catalog entry: %s", name, stats.rows, exc)
                else:
                    stats.logical_bytes += size
                    try:
                        process_row(paths, relative, size, stats, build=build, apply=apply)
                    except (OSError, RuntimeError) as exc:
                        stats.errors += 1
                        LOG.error("%s row %d (%s): %s", name, stats.rows, relative, exc)
                now = time.monotonic()
                if stats.rows % progress_every == 0 or now - last_report >= 30:
                    stats.report(name, "progress")
                    last_report = now
        if stats.rows == 0:
            raise ValueError("catalog has no file rows")
    except (OSError, EOFError, UnicodeError, csv.Error, ValueError, zlib.error) as exc:
        stats.errors += 1
        LOG.error("%s: catalog failed: %s", name, exc)
    stats.report(name, "summary")
    return stats


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--config", required=True, type=Path)
        sub.add_argument("--collection", action="append", help="select a collection (repeatable)")
        sub.add_argument("--progress-every", type=positive_int, default=10000, metavar="ROWS")
        if command == "build":
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument("--apply", action="store_true", help="create directories and hardlinks")
            mode.add_argument("--dry-run", action="store_true", help="inspect only (default)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build = args.command == "build"
    apply = build and args.apply
    try:
        collections = load_config(args.config, args.collection, build)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        LOG.error("configuration failed: %s", exc)
        return 2
    LOG.info("mode=%s", "apply" if apply else ("dry-run" if build else "verify"))
    failed = False
    total = Stats()
    try:
        for name, paths in collections:
            stats = process_catalog(name, paths, build=build, apply=apply,
                                    progress_every=args.progress_every)
            failed |= stats.failed
            for key, value in vars(stats).items():
                setattr(total, key, getattr(total, key) + value)
    except KeyboardInterrupt:
        LOG.error("interrupted; existing links are retained, rerun to resume")
        return 130
    total.report("all collections", "summary")
    return 1 if failed else 0
