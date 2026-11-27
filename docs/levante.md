# Batch jobs on Levante

From the repository root on a login node, submit the
[batch script](../scripts/levante-copy.sbatch):

```sh
# Dry-run (default).
sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6
# Create independent copies.
sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6 --apply
sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6-decadal --apply
squeue -u "$USER"
# Replace JOB_ID with the number returned by sbatch.
tail -F logs/c3s-cmip6-apply-batch-JOB_ID.log
```

Both scripts accept `[COLLECTION] [--config FILE] [--apply|--dry-run]` and optional
`--verbose`, `--silent` or `--progress`. They share the same argument parser.
The default config is `config/dkrz.toml` and the default collection is `c3s-cmip6`.
For example, append `--config config/custom.toml` to select another config.

Both scripts default to dry-run; add `--apply` explicitly to create files.
`--dry-run` is also accepted explicitly. They run with `--batch` (silent by
default), and each requests one CPU for 24 hours.
Replace `ACCOUNT` with an authorized Slurm allocation account, such as `bk1088`;
this is not your login username or necessarily the storage project `ik1017`.
Neither script hardcodes an account. Pass `--account` before the script path so
Slurm handles it at submission. Review the config before submission. Conda must already
be installed in `.conda-env`. Slurm runs the job on a compute node; you can log out
without tmux. Slurm output goes to `c3s-copy-JOB_ID.out` in the repository root.

Each submission keeps one detailed log named `logs/COLLECTION-MODE-batch-JOB_ID.log`,
where `MODE` is `dry-run` or `apply`. The log includes progress, errors and the
selected copy/hardlink method. To extract failures from a session:

```sh
grep ' ERROR ' logs/c3s-cmip6-apply-batch-JOB_ID.log
```

Resubmit with `--apply` after an interruption to skip existing files with matching sizes. After
a successful build, run `verify` for that collection before removing sources.

For hardlinks, use the same arguments as for copies:

```sh
sbatch --account=ACCOUNT scripts/levante-hardlink.sbatch c3s-cmip6
sbatch --account=ACCOUNT scripts/levante-hardlink.sbatch c3s-cmip6 --apply
tail -F logs/c3s-cmip6-apply-batch-JOB_ID.log
```

The hardlink script also requests one CPU for 24 hours and
uses `--batch` to run without prompting or console progress. Slurm
output goes to `c3s-hardlink-JOB_ID.out`. Both scripts keep detailed logs in
`logs/`; append `--verbose` to the submission arguments to also include detailed
logs in its Slurm output.
Use your own TOML configs and collection names for CMIP5, CORDEX or Atlas.
To retain only catalog-listed files, choose a separate, empty target on the same
filesystem. The script creates hardlinks and leaves all source files and any
existing target files untouched; it does not prune an existing pool. Your account
must have permission to create the source hardlinks and write the target.
Verify the new pool and switch consumers before separately retiring the old pool.

## Check completion and verify

```sh
sacct -j JOB_ID --format=JobID,State,ExitCode,Elapsed
.conda-env/bin/c3s-data-pool verify --config config/dkrz.toml \
  --collection c3s-cmip6 --collection c3s-cmip6-decadal \
  --log-file logs/c3s-verify.log
```

Keep original data until the builds and verification succeed. Verify checks
file types and sizes, not checksums. After a failed or timed-out job, resolve
errors and resubmit with `--apply`; completed files are retained.
