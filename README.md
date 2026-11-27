# c3s-data-pool

Retain catalog-listed files in separate local data pools using hardlinks by
default, or independent copies when explicitly selected. Built for the C3S CMIP6 and decadal migration at DKRZ;
also works with other catalogs using the same schema.

## Install

Requires Conda and Python 3.12 or newer. From this checkout:

```sh
make env
make install
conda activate ./.conda-env
```

`make env` creates `.conda-env` from [environment.yml](environment.yml).
Package and development dependencies stay in `pyproject.toml`, installed with
`make install` or `make develop`. Override `CONDA`, `ENV_PREFIX` or `ENV_FILE` as needed.

## Configure

Edit [config/dkrz.toml](config/dkrz.toml), which includes both C3S collections:

- `catalog`: a direct HTTPS `.csv.gz` URL, or a local `.csv.gz` / `.csv` file.
- `source`: the existing data pool root.
- `target`: the new pool root, outside the old pool's cleanup scope.

Relative local paths are resolved from the config file's directory. On Rook VMs,
use [config/rook.toml](config/rook.toml), with `/mnt/lustre/work/...` paths. Run builds with `--apply` on a host
with writable Lustre access; dry-run and verify work on read-only mounts.

TOML uses Python's built-in reader; the CLI has no third-party runtime dependencies.

Check catalog versions in the
[main Intake catalog](https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s.yaml).
For a migration, pin URLs to a Git commit or keep fixed local catalog snapshots.

Each CSV row needs `path`, `size` (bytes) and `mip_era`. Paths are relative to the
source/target roots and include the dataset version; `mip_era` is not prepended.
Catalogs are streamed row by row.
Each collection is read once to count file entries, then again to process them;
progress shows processed/total files and a percentage. Remote catalogs are
downloaded once and reused from `~/.cache/c3s-data-pool` (or
`$XDG_CACHE_HOME/c3s-data-pool`). Both passes use the same open local snapshot.
Use `--cache-dir PATH` to choose a writable local disk and `--refresh-catalog` to
replace cached snapshots. Failed downloads leave the previous cache intact and
return an error. Local catalogs are read directly.

## Build and verify

Run the CLI directly. Without activating Conda, use
`.conda-env/bin/c3s-data-pool` instead of `c3s-data-pool` below.

```sh
# Check source existence, type and size; only the local cache and log are written.
c3s-data-pool build --config config/rook.toml --log-file logs/cmip6-dry-run.log

# Review the displayed roots and answer yes to create hardlinks.
c3s-data-pool build --config config/dkrz.toml --apply

# Explicit alternative: copy file contents (requires additional storage/quota).
c3s-data-pool build --config config/dkrz.toml --copy --apply

# Check retained files, independently of the original source pool.
c3s-data-pool verify --config config/dkrz.toml
```

Add `--collection c3s-cmip6` or `--collection c3s-cmip6-decadal` to select a
collection. Apply requires `y` or `yes`; Enter or unavailable stdin cancels.
`--hardlink` is the default and can also be specified explicitly. `--copy` selects
independent copies; the two flags are mutually exclusive. There
is no automatic fallback to copying when a hardlink fails.
Dry-run never creates data pool directories or hardlinks. Keep its writable cache
and log on the VM's local disk rather than read-only Lustre.

Dry-run makes one stat call per source file and follows symlinks. That single
response provides existence, type and size; comparing the size costs no extra
filesystem request. Destination conflicts and filesystem compatibility are
checked during apply, so a successful dry-run cannot guarantee a successful
build.

The console shows an updating progress bar, then a short final status and log
path. Detailed messages go to `~/.local/state/c3s-data-pool/logs` (respecting
`XDG_STATE_HOME`), or the file chosen with `--log-file`. Explicit log files are
appended to. Redirected/non-interactive runs omit the bar.

The bar keeps animating during slow filesystem calls without extra filesystem
requests. Heartbeat log entries every 15 seconds include the current file and
elapsed time; use `--heartbeat-seconds 5` for more frequent log entries.

Apply resolves source symlinks and uses their metadata to check type and size.
With `--hardlink`, it prepares safe destination directories and attempts each hardlink directly,
without first probing the destination file or filesystem compatibility. If a
destination exists, its inode and device must match the source to be skipped.
Apply logs invalid entries, missing files, mismatches, conflicts and transfer
failures as `ERROR`, then continues with the remaining files and collections.
The final exit code is non-zero if any failed. An unreadable or malformed catalog
ends that collection; later collections are still processed. Successful files remain;
rerun after resolving the problems. Existing data files are never overwritten,
deleted or modified. Keep directory trees stable during a run; apply rechecks
destination directories before each transfer. Verify checks destination types and
sizes independently of the source and reports all failures.

Copy mode needs read access to sources and can copy across filesystems. It creates
new files owned by the running user, preserving source permission bits and
access/modification times, without copying ownership or ACLs. Existing regular files are skipped
if their catalog size matches; other destinations are conflicts. This is size
validation, not checksum validation, and does not convert existing hardlinks.

Copies are written to hidden temporary files beside their destinations and
validated before publication. Publication uses a hardlink from the new temporary
file owned by your account, which avoids the original source ownership restriction
and never overwrites a destination. The destination filesystem must support
hardlinks. Failed/interrupted copies remove their temporary files; an uncatchable
termination may leave `.c3s-copy-*.part` files, which reruns ignore.

Progress and summaries go to the log with local timestamps and UTC offsets,
including logical catalog volume in decimal GB/TB and errors. Exact bytes are
used internally for file-size checks.
`files` counts processed catalog entries, including duplicates and invalid rows.
`datasets` counts distinct parent directories of valid entries per collection;
different versions count separately. Totals sum across collections.
Exit `0` means success; non-zero means cancellation, an error or an incomplete
pool. `checked` counts source files that passed dry-run; `created` and `existing`
count apply results. Use verify to check a built pool.

## Copy on Levante with Slurm

From the repository root on a login node, submit the
[batch script](scripts/levante-copy.sbatch):

```sh
sbatch scripts/levante-copy.sbatch
squeue -u "$USER"
# Replace JOB_ID with the number returned by sbatch.
tail -F logs/c3s-cmip6-copy-JOB_ID.log
```

This explicitly applies copies for CMIP6 using `config/dkrz.toml`, automatically
answers the confirmation, and requests one CPU for 24 hours under `bk1088`.
Review the config and account before submission; override the account with
`sbatch --account=ACCOUNT scripts/levante-copy.sbatch` if needed. Conda must already
be installed in `.conda-env`. Slurm runs the job on a compute node; you can log out
without tmux. Slurm output goes to `c3s-copy-JOB_ID.out` in the repository root.

Each submission keeps one detailed log, including progress and errors. To extract
failures from a session:

```sh
grep ' ERROR ' logs/c3s-cmip6-copy-JOB_ID.log
```

To copy decadal instead, append `c3s-cmip6-decadal` to the submission command.
Resubmit after an interruption to skip existing files with matching sizes. After
a successful build, run `verify` for that collection before removing sources.

## Migrate safely

1. Review the config and run a dry-run. Resolve missing files and size mismatches.
2. Run with `--apply`, then verify both collections using the same catalogs.
   Require exit `0` and check CDS/Rook access through the new roots.
3. Coordinate removal of the old paths only after these checks. Source and
   target must be on the same filesystem for hardlink mode. Hardlinks survive removal of the
   original paths, but **in-place changes affect every link**: keep data immutable.
4. Point consumers to the retained roots and verify again after the old paths
   disappear. Verification checks regular files and sizes, not content checksums.

There is no pruning or synchronization. Files absent from a later catalog remain
untouched.

## Develop

```sh
make develop             # Editable install with test and lint dependencies
make check               # Ruff lint/format checks and all tests
make format              # Sort imports and format code
make test-integration    # Dummy CMIP6 and decadal pool tests
```

Tests use tiny synthetic files in temporary directories; no climate data or
Lustre access is needed. GitHub CI runs lint and tests. Use `make help` for all
development targets; Make uses `.conda-env/bin/python` without requiring
activation. `make build` packages a wheel; use the CLI for data pool operations.
