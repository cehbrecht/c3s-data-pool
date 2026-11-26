"""Build and verify local hardlink data pools from CSV catalogs."""

import argparse
import logging
import sys
from pathlib import Path

from .catalog import process_catalog
from .config import load_config
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def confirm_apply(collections):
    """Require explicit confirmation for the selected source/target pairs."""
    print("Apply will create directories and hardlinks for:", file=sys.stderr)
    for name, paths in collections:
        print(f"  {name}: {paths['source']} -> {paths['target']}", file=sys.stderr)
    print("Continue? [y/N]: ", end="", file=sys.stderr, flush=True)
    try:
        return input().strip().lower() in {"y", "yes"}
    except (EOFError, OSError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--config", required=True, type=Path)
        sub.add_argument("--collection", action="append", help="select a collection (repeatable)")
        sub.add_argument("--progress-every", type=positive_int, default=10000, metavar="ROWS")
        sub.add_argument(
            "--heartbeat-seconds",
            type=positive_int,
            default=15,
            metavar="SECONDS",
            help="activity heartbeat interval, including during slow filesystem calls (default: 15)",
        )
        sub.add_argument(
            "--cache-dir",
            type=Path,
            help="local catalog cache (default: ~/.cache/c3s-data-pool, respecting XDG_CACHE_HOME)",
        )
        sub.add_argument(
            "--refresh-catalog",
            action="store_true",
            help="download a fresh copy of remote catalogs",
        )
        if command == "build":
            sub.add_argument(
                "--quick",
                action="store_true",
                help="read-only source existence/size scan; skip destination and hardlink checks",
            )
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument(
                "--apply",
                action="store_true",
                help="create directories and hardlinks after confirmation",
            )
            mode.add_argument("--dry-run", action="store_true", help="inspect only (default)")
    args = parser.parse_args(argv)
    if args.command == "build" and args.quick and args.apply:
        parser.error("--quick cannot be combined with --apply")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %z",
    )
    build = args.command == "build"
    apply = build and args.apply
    quick = build and args.quick
    try:
        collections = load_config(args.config, args.collection, build, resolve_roots=not quick)
    except (OSError, ValueError, RuntimeError) as exc:
        LOG.error("configuration failed: %s", exc)
        return 2
    LOG.info(
        "mode=%s", "quick" if quick else ("apply" if apply else ("dry-run" if build else "verify"))
    )
    if quick:
        LOG.info(
            "quick scan checks all source files for existence, regular-file type and size; "
            "destination conflicts, filesystem compatibility and hardlink identity are not checked"
        )
    if apply:
        try:
            confirmed = confirm_apply(collections)
        except KeyboardInterrupt:
            LOG.error("interrupted before applying; no changes made")
            return 130
        if not confirmed:
            LOG.info("apply cancelled; no changes made")
            return 1
    failed = False
    total = Stats()
    try:
        for name, paths in collections:
            stats = process_catalog(
                name,
                paths,
                build=build,
                apply=apply,
                progress_every=args.progress_every,
                cache_dir=args.cache_dir,
                refresh=args.refresh_catalog,
                quick=quick,
                heartbeat_seconds=args.heartbeat_seconds,
            )
            failed |= stats.failed
            for key, value in vars(stats).items():
                setattr(total, key, getattr(total, key) + value)
    except KeyboardInterrupt:
        LOG.error("interrupted; existing links are retained, rerun to resume")
        return 130
    total.report("all collections", "quick summary" if quick else "summary")
    return 1 if failed else 0
