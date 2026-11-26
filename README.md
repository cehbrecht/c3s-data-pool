# c3s-data-pool

Retain catalog-listed files in separate local data pools using hardlinks, without
duplicating their contents. Built for the C3S CMIP6 and decadal migration at DKRZ;
also works with other catalogs using the same schema.

## Install

Requires Conda and Python 3.10 or newer. From this checkout:

```sh
make env
make install
conda activate ./.conda-env
```

## Configure

Edit [config/dkrz.toml](config/dkrz.toml), which includes both C3S collections:

- `catalog`: a direct HTTPS `.csv.gz` URL, or a local `.csv.gz` / `.csv` file.
- `source`: the existing data pool root.
- `target`: the new pool root, outside the old pool's cleanup scope.

Relative local paths are resolved from the config file's directory. On Rook VMs,
use [config/rook.toml](config/rook.toml), with `/mnt/lustre/work/...` paths. Run builds with `--apply` on a host
with writable Lustre access; dry-run and verify work on read-only mounts.

TOML uses Python's built-in reader on 3.11+ (`tomli` on 3.10).

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
# Inspect first: dry-run is the default; only the local catalog cache is written.
c3s-data-pool build --config config/dkrz.toml

# Review the displayed roots and answer yes to create hardlinks.
c3s-data-pool build --config config/dkrz.toml --apply

# Check retained files, independently of the original source pool.
c3s-data-pool verify --config config/dkrz.toml
```

Add `--collection c3s-cmip6` or `--collection c3s-cmip6-decadal` to select a
collection. Apply requires `y` or `yes`; Enter or unavailable stdin cancels.
Dry-run never creates data pool directories or hardlinks. Its catalog cache must
be writable; keep it on the VM's local disk rather than read-only Lustre.

Builds check source sizes, resolve source symlinks and check existing hardlinks
by inode and device. Correct links are skipped, so interrupted builds can be
rerun. Existing data files are never overwritten, deleted or copied.

Progress and summaries go to stderr with local timestamps and UTC offsets,
including logical catalog volume in decimal GB/TB and errors. Exact bytes are
used internally for file-size checks.
`files` counts processed catalog entries, including duplicates and invalid rows.
`datasets` counts distinct parent directories of valid entries per collection;
different versions count separately. Totals sum across collections.
Exit `0` means success; non-zero means cancellation, an error or an incomplete
pool. A successful dry-run describes a plan; use verify to check a built pool.

## Migrate safely

1. Review the config and run a dry-run. Resolve missing files, size mismatches
   and conflicts.
2. Run with `--apply`, then verify both collections using the same catalogs.
   Require exit `0` and check CDS/Rook access through the new roots.
3. Coordinate removal of the old paths only after these checks. Source and
   target must be on the same filesystem. Hardlinks survive removal of the
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
