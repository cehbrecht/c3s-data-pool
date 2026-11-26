#!/bin/bash
#SBATCH --job-name=c3s-copy
#SBATCH --account=bk1088
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=1-00:00:00
#SBATCH --output=c3s-copy-%j.out

# Submit from the repository root: sbatch scripts/levante-copy.sbatch
# Optional collection: sbatch scripts/levante-copy.sbatch c3s-cmip6-decadal
# Submitting this script explicitly authorizes the --apply --copy operation.
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
collection="${1:-c3s-cmip6}"
mkdir -p logs
log_file="logs/${collection}-copy-${SLURM_JOB_ID}.log"

# Answer the CLI confirmation; pipefail preserves a failed build's exit status.
printf 'y\n' | .conda-env/bin/c3s-data-pool build \
    --config config/dkrz.toml \
    --collection "$collection" \
    --apply --copy \
    --log-file "$log_file"
