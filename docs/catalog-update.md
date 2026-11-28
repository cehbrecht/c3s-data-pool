# Update an existing catalog

`update-catalog` enriches an existing catalog rather than discovering files by
scanning a directory. Use it for catalogs with missing or stale file sizes or a
missing `mip_era` column, such as the published CMIP5 catalog.

Run on a host that can read the source pool. The source may be mounted read-only;
only the output directory, local cache and log must be writable.

```sh
catalog_url="https://raw.githubusercontent.com/cp4cds/c3s_34g_manifests/refs/heads/master/intake/catalogs/c3s-cmip5/c3s-cmip5_v20240711.csv.gz"

.conda-env/bin/c3s-data-pool update-catalog \
  --catalog "$catalog_url" \
  --source /work/ik1017/C3SCMIP5/data/c3s-cmip5 \
  --output catalogs/c3s-cmip5_updated.csv.gz \
  --mip-era CMIP5 \
  --log-file logs/cmip5-catalog-update.log \
  --progress
```

Local `.csv` and `.csv.gz` inputs are also supported. Remote catalogs use the
existing cache; use `--refresh-catalog` to refresh it. CLI paths are relative to
the working directory. Output may be `.csv` or `.csv.gz`.

The command:

- Requires a `path` column and validates every relative file path.
- Follows source symlinks and checks that each source is a regular file.
- Makes one source `stat` call per row, without reading data-file contents.
- Replaces every `size` with the actual size in bytes, including valid zero-byte files.
- Sets every `mip_era` to the explicit supplied value; it does not infer it.
- Preserves other column values, column order, row order and duplicate entries.
  Missing `size` and `mip_era` columns are appended.
- Writes a temporary catalog and publishes it only after every row succeeds.
  Existing output files, including the original input, are never overwritten.

Failures are logged as `ERROR` and later rows are still checked. Any failure
returns non-zero and removes the temporary output; no incomplete final catalog is
published. Resolve missing files or catalog errors and rerun. Interruption also
removes the temporary catalog; an uncatchable termination may leave a hidden
`.c3s-catalog-*.part` file. Data files and the input catalog are not modified.

File logs, timed heartbeats, `--progress`, `--verbose`, `--silent` and `--batch`
work as for other commands. `checked` counts successfully updated rows and volume
is the sum of their actual file sizes. `--output` explicitly authorizes writing
the new catalog; this command has no dry-run or `--apply` mode.

## Run on Levante with Slurm

From the repository root, with an existing local input catalog:

```sh
sbatch --account=ACCOUNT --partition=shared --cpus-per-task=1 \
  --time=1-00:00:00 --job-name=c3s-catalog-update \
  --output=c3s-catalog-update-%j.out \
  --wrap='.conda-env/bin/c3s-data-pool update-catalog --catalog catalogs/c3s-cmip5_v20240711.csv.gz --source /work/ik1017/C3SCMIP5/data/c3s-cmip5 --output catalogs/c3s-cmip5_updated.csv.gz --mip-era CMIP5 --batch --log-file logs/cmip5-catalog-update.log'
```

Replace `ACCOUNT` with an authorized Slurm allocation account. You can use the
HTTPS catalog URL as `--catalog` instead. Keep the completed output as a reviewed
snapshot and point the pool config's `catalog` at it before building hardlinks or
copies. Verification then uses the sizes recorded in that snapshot.
