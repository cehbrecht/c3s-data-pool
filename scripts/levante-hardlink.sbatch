#!/bin/bash
#SBATCH --job-name=c3s-hardlink
#SBATCH --account=bk1088
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=1-00:00:00
#SBATCH --output=c3s-hardlink-%j.out

# Submit from the repository root, providing a config and collection:
# sbatch scripts/levante-hardlink.sbatch config/dkrz.toml c3s-cmip6
# Dry-run is the default. Create hardlinks only with an explicit --apply:
# sbatch scripts/levante-hardlink.sbatch config/dkrz.toml c3s-cmip6 --apply
# Other collections (add their entries to config/dkrz.toml first):
# sbatch scripts/levante-hardlink.sbatch config/dkrz.toml c3s-cmip5
# sbatch scripts/levante-hardlink.sbatch config/dkrz.toml c3s-cordex
# sbatch scripts/levante-hardlink.sbatch config/dkrz.toml c3s-atlas
# Both arguments are required; the collection must be defined in that config.
# Append --apply to the examples above to create hardlinks; --dry-run is also accepted.
# Source and target must be on the same filesystem. No files are pruned.
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: sbatch scripts/levante-hardlink.sbatch CONFIG COLLECTION [--apply|--dry-run]" >&2
    exit 2
fi

config="$1"
collection="$2"
shift 2
mode="dry-run"
case "$*" in
    ""|--dry-run) ;;
    --apply) mode="apply" ;;
    *)
        echo "Usage: sbatch scripts/levante-hardlink.sbatch CONFIG COLLECTION [--apply|--dry-run]" >&2
        exit 2
        ;;
esac

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
mkdir -p logs
log_file="logs/${collection}-${mode}-batch-${SLURM_JOB_ID}.log"

# Keep detailed progress in the job log, without a prompt or console output.
exec .conda-env/bin/c3s-data-pool build \
    --config "$config" \
    --collection "$collection" \
    "--$mode" --hardlink --batch \
    --log-file "$log_file"
