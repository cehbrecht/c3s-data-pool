"""Build and verify local hardlink data pools from compressed CSV catalogs."""

import argparse
import logging
from pathlib import Path

import yaml

from .catalog import process_catalog
from .config import load_config
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


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
