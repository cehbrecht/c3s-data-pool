#!/bin/bash
# Shared implementation sourced by the Slurm copy and hardlink scripts.
method="$1"
shift
config="config/dkrz.toml"
collection="c3s-cmip6"
collection_set=false
mode="dry-run"
mode_set=false
console_option=""

usage() {
    echo "Usage: sbatch --account=ACCOUNT scripts/levante-${method}.sbatch [COLLECTION] [--config FILE] [--apply|--dry-run] [--verbose|--silent|--progress]" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || usage
            config="$2"
            shift 2
            ;;
        --apply|--dry-run)
            [[ "$mode_set" == false ]] || usage
            mode="${1#--}"
            mode_set=true
            shift
            ;;
        --verbose|--silent|--progress)
            [[ -z "$console_option" ]] || usage
            console_option="$1"
            shift
            ;;
        --*) usage ;;
        *)
            [[ "$collection_set" == false && -n "$1" && "$1" != */* ]] || usage
            collection="$1"
            collection_set=true
            shift
            ;;
    esac
done

mkdir -p logs
log_file="logs/${collection}-${mode}-batch-${SLURM_JOB_ID}.log"

set -- build \
    --config "$config" \
    --collection "$collection" \
    "--$mode" "--$method" --batch
if [[ -n "$console_option" ]]; then
    set -- "$@" "$console_option"
fi
exec .conda-env/bin/c3s-data-pool "$@" --log-file "$log_file"
