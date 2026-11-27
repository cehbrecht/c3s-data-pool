#!/bin/bash
#SBATCH --job-name=c3s-copy
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=1-00:00:00
#SBATCH --output=c3s-copy-%j.out

# Submit from the repository root; both scripts accept the same arguments:
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6 --apply
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip6-decadal --apply
# Other collections (add entries to config/dkrz.toml first):
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cmip5 --apply
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-cordex --apply
# sbatch --account=ACCOUNT scripts/levante-copy.sbatch c3s-atlas --apply
# Optional config: append --config config/custom.toml
# ACCOUNT is a Slurm allocation account (e.g. bk1088), not a username.
# Defaults: c3s-cmip6, config/dkrz.toml, dry-run and silent output.
# Hardlinks require the source and target to be on the same filesystem.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
source scripts/levante-build.sh copy "$@"
