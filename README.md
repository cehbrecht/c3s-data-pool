# c3s-data-pool

Build and verify catalog-selected data pools using hardlinks or independent
copies. Designed for C3S migrations; works with any catalog using the same schema.

## Install

Requires Conda and Python 3.12 or newer:

```sh
make env
make install
conda activate ./.conda-env
```

The Conda environment is defined in [environment.yml](environment.yml); package
and development dependencies are in [pyproject.toml](pyproject.toml).
Make uses `.conda-env/bin/python` directly, so activation is optional.

## Configure

Edit [config/dkrz.toml](config/dkrz.toml). Each collection defines:

- `catalog`: HTTPS `.csv.gz` URL or local `.csv` / `.csv.gz` file.
- `source`: existing data pool root.
- `target`: retained pool root, outside the source cleanup scope.

Catalog rows require `path`, `size` (bytes) and `mip_era`. Paths are relative to
source/target roots and include dataset versions. Local config paths are relative
to the config directory. Adjust data roots to match your host's mounts.

Check versions in the [main Intake catalog](https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s.yaml).
For migrations, use fixed local snapshots or URLs pinned to a Git commit.
Remote catalogs are cached locally and streamed row by row.

## Update an existing catalog

Add or refresh `size` from actual source-file metadata and set `mip_era`, preserving
the existing paths, row order and other columns:

```sh
c3s-data-pool update-catalog \
  --catalog c3s-cmip5_v20240711.csv.gz \
  --source /work/ik1017/C3SCMIP5/data/c3s-cmip5 \
  --output catalogs/c3s-cmip5_updated.csv.gz \
  --mip-era CMIP5 --progress
```

The input can also be an HTTPS `.csv.gz` URL. A new output path is required;
the input is never modified. No output is published if any file or row fails.
See [catalog update details](docs/catalog-update.md), including running on Slurm.

## Build and verify

```sh
# Dry-run: check source existence, regular-file type and actual size.
c3s-data-pool build --config config/dkrz.toml

# Create hardlinks after confirming the displayed roots.
c3s-data-pool build --config config/dkrz.toml --apply

# Alternatively, create independent copies (requires additional storage).
c3s-data-pool build --config config/dkrz.toml --copy --apply

# Verify retained files without requiring the original source.
c3s-data-pool verify --config config/dkrz.toml
```

Add `--collection NAME` to select a collection; repeat it to select several.
Hardlink is the default; `--hardlink` makes it explicit. Both build methods
continue after file errors, preserve completed files and return non-zero if
anything failed. Existing data files are never overwritten, modified or deleted.

Console output is verbose by default. Use `--progress` for an interactive progress
bar or `--silent` for no console progress/status. `--batch` skips confirmation and
defaults to silent; writes still require `--apply`. Explicit console options
override defaults. All modes keep detailed timestamped file logs, including
heartbeats during slow filesystem calls. Use `--log-file PATH` to choose the log.

See [catalog and file-handling details](docs/behavior.md) for caching, counters,
copy publication and error behavior. For unattended jobs, see
[Slurm batch instructions for Levante](docs/levante.md).

## Migration

1. Review roots and catalog versions, then run a dry-run. Dry-run does not check
   destination conflicts or write permissions.
2. Build with `--apply`, then verify against the same catalogs. Require exit `0`.
3. Switch CDS/Rook or other consumers to the retained roots and check access.
4. Coordinate removal of original paths only after these checks.

Hardlinks require the same filesystem and sufficient permissions. They survive
removal of original paths, but in-place changes affect all links. Copies are
independent. Verification checks types and sizes, not checksums.
There is no pruning or synchronization; files absent from a catalog remain.

## Develop

```sh
make develop             # Editable install with test and lint dependencies
make check               # Lint, formatting checks and all tests
make format              # Format Python code
make test-integration    # Synthetic CMIP6 and decadal pool tests
```

Tests need no climate data or Lustre access. GitHub CI runs lint and tests.
Use `make help` for development targets; run pool operations through the CLI.
