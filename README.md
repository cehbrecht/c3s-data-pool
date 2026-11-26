# c3s-data-pool

Build, maintain and verify local data pools using hardlinks to files listed in
published compressed CSV catalogs. Designed to retain the CMIP6 and CMIP6 decadal
files used by CDS/Rook before the shared DKRZ pool is archived; the implementation
works with any catalog using the same schema.

## Installation

Requires Python 3.10 or newer and PyYAML. From this checkout:

```sh
conda create --prefix ./.conda-env -c conda-forge python=3.12 pip
conda activate ./.conda-env
python -m pip install -e .
```

Dependencies, test extras and the CLI entry point are defined in `pyproject.toml`.
For development, install `python -m pip install -e '.[test]'` and run `pytest`
inside the Conda environment.
GitHub Actions runs synthetic-file tests; no climate data or Lustre is required.

## Common development tasks

The Makefile uses `.conda-env/bin/python` by default, so activation is optional:

```sh
make help                # Show available tasks (also the default for make)
make env                 # Create the Conda environment
make install             # Install the package
make develop             # Editable install with test dependencies
make test                # All tests
make test-integration    # Dummy CMIP6 and decadal pool tests
make build               # Package wheel in dist/
make dry-run             # Inspect pools configured in config/dkrz.yml
make apply               # Confirm, then create directories and hardlinks
make verify              # Verify destination pools
```

Use `make test TEST_ARGS="-v"` for verbose tests, or `make test PYTHON=python`
to use an already activated environment. `ENV_PREFIX` and `PYTHON_VERSION` can
be overridden when creating an environment. Pool tasks accept `CONFIG` and
additional CLI arguments, for example:

```sh
make dry-run CONFIG=config/dkrz.yml ARGS="--collection c3s-cmip6"
```

## Catalogs and configuration

Configure a direct HTTPS `.csv.gz` URL from the
[published catalogs](https://github.com/cp4cds/c3s_34g_manifests/tree/master/intake/catalogs).
The [main Intake catalog](https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s.yaml)
identifies the versions. Alternatively, clone the repository manually and point
`catalog` to a local `.csv.gz` or uncompressed `.csv` file. Both options stream one row at a time without
loading a whole catalog into memory. Remote catalogs are read directly on each
run, with a 30-second socket timeout and no local cache. No Intake dependency is
needed; HTTP/network failures produce a non-zero exit code.

Small, readable synthetic catalogs for CMIP6 and decadal are in `tests/fixtures/`.
The integration tests build both collections in a temporary DKRZ-style directory
tree, check repeat builds and collection selection, and verify retained files
after removing the originals. They exercise both plain and gzipped CSVs.

Each CSV must have `path`, `size` and `mip_era` columns. `size` is an integer number
of bytes; `path` is relative to the configured source/target root and includes the
dataset version. Extra columns are ignored. `mip_era` is required as a column but
does not change path handling: it is not prepended to `path`.

[config/dkrz.yml](config/dkrz.yml) contains both DKRZ collections:

```yaml
collections:
  c3s-cmip6:
    catalog: https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s-cmip6/c3s-cmip6_v20260203.csv.gz
    source: /work/ik1017/CMIP6/data/CMIP6
    target: /work/ik1017/C3SCMIP6/data/c3s-cmip6

  c3s-cmip6-decadal:
    catalog: https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s-cmip6-decadal/c3s-cmip6-decadal_v20231102.csv.gz
    source: /work/ik1017/CMIP6/data/CMIP6
    target: /work/ik1017/C3SCMIP6_DECADAL/data/c3s-cmip6-decadal
```

To use a manually cloned repository instead, replace a collection's `catalog`:

```yaml
catalog: ../c3s_34g_manifests/intake/catalogs/c3s-cmip6/c3s-cmip6_v20260203.csv.gz
```

Absolute local paths also work. Relative catalog, source and target paths are
interpreted relative to the YAML file's directory, independent of the current
working directory. Remote URLs are used as configured. Direct catalog links:

- [c3s-cmip6_v20260203.csv.gz](https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s-cmip6/c3s-cmip6_v20260203.csv.gz)
- [c3s-cmip6-decadal_v20231102.csv.gz](https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s-cmip6-decadal/c3s-cmip6-decadal_v20231102.csv.gz)

On Rook VMs, use `/mnt/lustre/work/...` instead of `/work/...` for source and
target. Dry-run and verification work through the read-only mount, including when
the target does not exist. Run `--apply` on a host with writable Lustre access.
Hardlinks require the resolved source and target to be on the same filesystem;
there is no copy fallback. The source can resolve through symlinks to real files
outside its configured root.

## Usage

```sh
# Both commands only inspect; no directories, links or log files are created.
c3s-data-pool build --config config/dkrz.yml
c3s-data-pool build --config config/dkrz.yml --dry-run

# Confirm the displayed source/target roots, then create directories and hardlinks.
c3s-data-pool build --config config/dkrz.yml --apply

# Restrict either command to one or more named collections.
c3s-data-pool build --config config/dkrz.yml --collection c3s-cmip6
c3s-data-pool verify --config config/dkrz.yml
```

Dry-run remains the default. `--apply` (including `make apply`) displays the
selected collections and source/target roots, then asks `Continue? [y/N]:` before
reading catalogs or creating anything. Only `y` or `yes` confirms, ignoring case
and surrounding whitespace. Enter, `no`, any other answer, or unavailable stdin
cancels with exit code `1`; Ctrl-C exits `130`. Dry-run and verify never prompt.

`--collection` can be repeated. `--progress-every ROWS` changes the default 10,000
row interval; progress is also emitted after a row when 30 seconds have elapsed.
Logs and per-collection/overall summaries go to stderr. Summaries include rows,
catalog logical bytes/TiB, created/planned/existing/verified files, missing files,
size mismatches, conflicts, invalid entries, hardlink failures and other errors.
Logical volume sums valid catalog rows (including missing files and duplicate
rows); it is not newly allocated disk space or deduplicated storage usage.

Build checks the source's existence, regular-file type and size, resolves source
symlinks, and validates existing destination files by inode **and** device number.
A same-size independent copy is a conflict. Builds can be rerun after an error or
interruption; correct existing hardlinks are retained. No existing data file is
overwritten, deleted, copied, chmodded or opened for writing. Failed applies may
leave newly created empty directories and successfully created links.

Absolute CSV row paths, traversal, dot/empty path components, backslashes and NULs
are rejected. Destination symlinks and non-directory parents below the configured
target root are conflicts. Configured roots themselves are resolved, so an
explicitly configured root alias is supported. Use trusted configuration and
keep source files and directory trees stable during the run: the tool is not a
lock or a defense against concurrent directory/symlink replacement.

Verification checks only destination regular files and catalog sizes. It needs
neither source access nor a `source` configuration key. It cannot prove historical
hardlink identity or detect same-size content corruption without checksums.
Hardlinks share an inode: subsequent in-place writes through any link affect all
links, so retained data must remain immutable.

Exit codes: `0` means all rows passed (or all missing links were planned in a
dry-run), `1` means cancellation, an incomplete pool or catalog/operation failure, `2` means a
CLI/configuration error, and `130` means an interrupted processing run. A successful
dry-run is a plan, not proof of a complete pool or of write permissions/quota.

## Migration procedure

1. Use GitHub URLs pinned to a commit (replace `refs/heads/master` with a commit
   SHA), or retain exact local catalog snapshots for the migration. Review the
   configured roots and ensure each target is outside the shared pool's archive
   or removal scope and on the same filesystem as the resolved source data.
2. Run the default dry-run for both collections. Review the summaries and resolve
   missing files, size mismatches, invalid paths and conflicts. Confirm filesystem
   identity and the writable host/account intended for the actual build.
3. Run `build --apply` on DKRZ with writable Lustre access, review the displayed
   source/target roots and answer `yes` to proceed. Keep the output, for
   example with shell stderr redirection to a migration log. Resolve reported
   failures and rerun the same command until it exits `0`.
4. Run `verify` against the same catalog snapshots and require exit `0` for both
   collections. Also check representative CDS/Rook accesses using the new roots.
5. Coordinate archival/removal of the old pool only after these checks. Removing
   original directory entries preserves the target hardlinks and their data;
   in-place truncation or modification of the shared inodes does not. Keep the
   new roots outside any cleanup operation and confirm the archive procedure
   removes names rather than modifying file contents.
6. Point consumers to the retained roots (or their Rook mount equivalents), then
   run `verify` again after the original paths disappear. Verification remains
   independent of the old pool.

Maintenance consists of explicitly choosing a catalog and rerunning build/verify.
There is no pruning, synchronization, database or download cache; files absent
from a later catalog are left untouched.
