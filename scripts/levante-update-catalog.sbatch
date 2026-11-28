#!/bin/bash
#SBATCH --job-name=c3s-catalog-update
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=1-00:00:00
#SBATCH --output=c3s-catalog-update-%j.out

# Submit from the repository root; ACCOUNT is your Slurm allocation account:
# sbatch --account=ACCOUNT scripts/levante-update-catalog.sbatch c3s-cmip5 \
#   --catalog catalogs/c3s-cmip5_v20240711.csv.gz \
#   --source /work/ik1017/C3SCMIP5/data/c3s-cmip5 \
#   --output catalogs/c3s-cmip5_v20240711_v2.csv.gz --mip-era CMIP5
# --catalog also accepts an HTTPS .csv.gz URL. Append --verbose for console logs.
# The collection argument labels the log; all remaining arguments go to update-catalog.
# No --apply: --output explicitly requests a new catalog. Existing files are never replaced.
set -euo pipefail

if [[ $# -lt 1 || -z "$1" || "$1" == -* || "$1" == */* ]]; then
    echo "Usage: sbatch --account=ACCOUNT scripts/levante-update-catalog.sbatch COLLECTION --catalog INPUT --source ROOT --output NEW_CATALOG --mip-era VALUE [OPTIONS]" >&2
    exit 2
fi
collection="$1"
shift

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
mkdir -p logs
log_file="logs/${collection}-catalog-update-batch-${SLURM_JOB_ID}.log"

exec .conda-env/bin/c3s-data-pool update-catalog "$@" --batch --log-file "$log_file"
