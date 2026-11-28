"""Build and verify local data pools, and update existing CSV catalogs."""

import argparse
import logging
import sys
from pathlib import Path

from .catalog import process_catalog
from .catalog_update import update_catalog
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
    for command in ("build", "verify", "update-catalog"):
        sub = commands.add_parser(command)
        if command == "update-catalog":
            sub.add_argument("--catalog", required=True, help="existing local or HTTPS CSV catalog")
            sub.add_argument("--source", required=True, type=Path, help="source data pool root")
            sub.add_argument(
                "--output", required=True, type=Path, help="new .csv or .csv.gz catalog"
            )
            sub.add_argument("--mip-era", required=True, help="value to set in every output row")
        else:
            sub.add_argument("--config", required=True, type=Path)
        sub.add_argument(
            "--log-file",
            type=Path,
            help="detailed log file (default: ~/.local/state/c3s-data-pool/logs, respecting XDG_STATE_HOME)",
        )
        if command != "update-catalog":
            sub.add_argument(
                "--collection", action="append", help="select a collection (repeatable)"
            )
        verbosity = sub.add_mutually_exclusive_group()
        verbosity.add_argument(
            "--progress", action="store_true", help="show a progress bar on an interactive terminal"
        )
        verbosity.add_argument(
            "--verbose",
            action="store_true",
            help="print detailed console logs (default without --batch)",
        )
        verbosity.add_argument(
            "--silent",
            action="store_true",
            help="suppress console progress and final status; keep logs",
        )
        sub.add_argument(
            "--batch",
            action="store_true",
            help="run unattended and default to silent; builds still require --apply to write data",
        )
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
    if args.command == "update-catalog" and args.log_file is not None:
        log_path = args.log_file.expanduser()
        protected = [args.output]
        if not args.catalog.startswith("https://"):
            protected.append(Path(args.catalog))
        try:
            for path in protected:
                if log_path.resolve() == path.expanduser().resolve() or (
                    log_path.exists()
                    and path.expanduser().exists()
                    and log_path.samefile(path.expanduser())
                ):
                    parser.error("log file must differ from the input and output catalogs")
        except (OSError, RuntimeError) as exc:
            parser.error(str(exc))
    verbose = args.verbose or (not args.batch and not args.silent and not args.progress)
    try:
        output = RunOutput(
            args.log_file, args.command, verbose=verbose, silent=not verbose and not args.progress
        )
    except OSError as exc:
        print(f"Cannot open log file: {exc}", file=sys.stderr)
        return 2
    mode = (
        "Update catalog"
        if args.command == "update-catalog"
        else ("Verify" if args.command == "verify" else ("Apply" if args.apply else "Dry-run"))
    )
    with output:
        try:
            code = _run(args, output.console)
        except KeyboardInterrupt:
            if args.command == "update-catalog":
                LOG.error("catalog update interrupted; input is unchanged, rerun to retry")
            else:
                LOG.error("interrupted; completed files are retained, rerun to resume")
            code = 130
        output.finish(code, mode)
    return code


def _run(args, console):
    if args.command == "update-catalog":
        stats = update_catalog(
            args.catalog,
            args.source,
            args.output,
            args.mip_era,
            progress_every=args.progress_every,
            cache_dir=args.cache_dir,
            refresh=args.refresh_catalog,
            heartbeat_seconds=args.heartbeat_seconds,
            console=console,
        )
        return 1 if stats.failed else 0
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
    if apply and args.batch:
        LOG.info("batch mode: apply confirmation skipped")
    if apply and not args.batch:
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
    except KeyboardInterrupt:
        LOG.error("interrupted; completed files are retained, rerun to resume")
        return 130
    total.report("all collections", "summary")
    return 1 if failed else 0
