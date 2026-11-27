#!/bin/bash
#SBATCH --job-name=c3s-copy
#SBATCH --account=bk1088
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=1-00:00:00
#SBATCH --output=c3s-copy-%j.out

# Submit from the repository root; dry-run is the default:
# sbatch scripts/levante-copy.sbatch c3s-cmip6
# Create copies only with an explicit --apply:
# sbatch scripts/levante-copy.sbatch c3s-cmip6 --apply
# sbatch scripts/levante-copy.sbatch c3s-cmip6-decadal --apply
# Omitting the collection selects c3s-cmip6. --dry-run is also accepted explicitly.
set -euo pipefail

collection="c3s-cmip6"
if [[ $# -gt 0 && "$1" != --* ]]; then
    collection="$1"
    shift
fi
mode="dry-run"
case "$*" in
    ""|--dry-run) ;;
    --apply) mode="apply" ;;
    *)
        echo "Usage: sbatch scripts/levante-copy.sbatch [COLLECTION] [--apply|--dry-run]" >&2
        exit 2
        ;;
esac

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
mkdir -p logs
log_file="logs/${collection}-${mode}-batch-${SLURM_JOB_ID}.log"

# Keep detailed progress in the job log, without a prompt or console output.
exec .conda-env/bin/c3s-data-pool build \
    --config config/dkrz.toml \
    --collection "$collection" \
    "--$mode" --copy --batch \
    --log-file "$log_file"
