"""Build and verify local data pools from CSV catalogs."""

import argparse
import logging
import sys
from pathlib import Path

from .catalog import process_catalog
from .config import load_config
from .output import RunOutput
from .stats import Stats

LOG = logging.getLogger("c3s-data-pool")


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def confirm_apply(collections, method="hardlink"):
    """Require explicit confirmation for the selected source/target pairs."""
    action = "hardlinks" if method == "hardlink" else "independent file copies"
    print(f"Apply will create directories and {action} for:", file=sys.stderr)
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
        sub.add_argument(
            "--log-file",
            type=Path,
            help="detailed log file (default: ~/.local/state/c3s-data-pool/logs, respecting XDG_STATE_HOME)",
        )
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
            method = sub.add_mutually_exclusive_group()
            method.add_argument(
                "--hardlink",
                dest="method",
                action="store_const",
                const="hardlink",
                default="hardlink",
                help="retain files using hardlinks (default)",
            )
            method.add_argument(
                "--copy",
                dest="method",
                action="store_const",
                const="copy",
                help="retain independent copies of file contents",
            )
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument(
                "--apply",
                action="store_true",
                help="create directories and data files using the selected method after confirmation",
            )
            mode.add_argument("--dry-run", action="store_true", help="inspect only (default)")
    args = parser.parse_args(argv)
    try:
        output = RunOutput(args.log_file, args.command)
    except OSError as exc:
        print(f"Cannot open log file: {exc}", file=sys.stderr)
        return 2
    mode = "Verify" if args.command == "verify" else ("Apply" if args.apply else "Dry-run")
    with output:
        try:
            code = _run(args, output.console)
        except KeyboardInterrupt:
            LOG.error("interrupted; completed files are retained, rerun to resume")
            code = 130
        output.finish(code, mode)
    return code


def _run(args, console):
    build = args.command == "build"
    apply = build and args.apply
    dry_run = build and not apply
    method = args.method if build else "hardlink"
    try:
        collections = load_config(args.config, args.collection, build, resolve_roots=not dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        LOG.error("configuration failed: %s", exc)
        return 2
    LOG.info("mode=%s", "apply" if apply else ("dry-run" if build else "verify"))
    LOG.info("config=%s", args.config.absolute())
    if build:
        LOG.info("method=%s", method)
        if method == "copy":
            LOG.info(
                "copy mode duplicates file contents; existing regular files are accepted "
                "by catalog size, without checksum validation"
            )
    if dry_run:
        LOG.info(
            "dry-run checks all source files for existence, regular-file type and size; "
            "destination conflicts, filesystem compatibility and hardlink identity are not checked"
        )
    if apply:
        try:
            confirmed = confirm_apply(collections, method)
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
            LOG.info(
                "%s: catalog=%s source=%s target=%s",
                name,
                paths["catalog"],
                paths.get("source", "-"),
                paths["target"],
            )
            stats = process_catalog(
                name,
                paths,
                build=build,
                apply=apply,
                progress_every=args.progress_every,
                cache_dir=args.cache_dir,
                refresh=args.refresh_catalog,
                heartbeat_seconds=args.heartbeat_seconds,
                console=console,
                method=method,
            )
            failed |= stats.failed
            for key, value in vars(stats).items():
                setattr(total, key, getattr(total, key) + value)
            if apply and stats.failed:
                LOG.error("apply stopped; remaining collections were not processed")
                break
    except KeyboardInterrupt:
        LOG.error("interrupted; completed files are retained, rerun to resume")
        return 130
    total.report("all collections", "summary")
    return 1 if failed else 0
