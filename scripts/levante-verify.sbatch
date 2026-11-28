#!/bin/bash
#SBATCH --job-name=c3s-verify
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=04:00:00
#SBATCH --output=c3s-verify-%j.out

# Submit from the repository root; one collection per job:
# sbatch --account=ACCOUNT scripts/levante-verify.sbatch c3s-cmip6
# sbatch --account=ACCOUNT scripts/levante-verify.sbatch c3s-cmip6-decadal
# Optional config: append --config config/custom.toml
# ACCOUNT is a Slurm allocation account (e.g. bk1088), not a username.
# Defaults: c3s-cmip6, config/dkrz.toml and silent output (--batch).
# Checks destination file types and sizes, without checksums or source access.
# No --apply is needed or accepted; verification never creates data files.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
source scripts/levante-build.sh verify "$@"
