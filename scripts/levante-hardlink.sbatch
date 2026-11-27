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
# Other collections (create the corresponding TOML config first):
# sbatch scripts/levante-hardlink.sbatch config/cmip5.toml c3s-cmip5
# sbatch scripts/levante-hardlink.sbatch config/cordex.toml c3s-cordex
# sbatch scripts/levante-hardlink.sbatch config/atlas.toml c3s-atlas
# Both arguments are required; the collection must be defined in that config.
# Submitting this script explicitly authorizes the --apply --hardlink operation.
# Source and target must be on the same filesystem. No files are pruned.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: sbatch scripts/levante-hardlink.sbatch CONFIG COLLECTION" >&2
    exit 2
fi

cd "${SLURM_SUBMIT_DIR:?Submit this script using sbatch from the repository root}"
config="$1"
collection="$2"
mkdir -p logs
log_file="logs/c3s-hardlink-${SLURM_JOB_ID}.log"

# Answer the CLI confirmation; pipefail preserves a failed build's exit status.
printf 'y\n' | .conda-env/bin/c3s-data-pool build \
    --config "$config" \
    --collection "$collection" \
    --apply --hardlink \
    --log-file "$log_file"
