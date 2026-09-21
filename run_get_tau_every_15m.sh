#!/usr/bin/env bash

set -u

readonly INTERVAL_SECONDS=900
readonly CLEANUP_INTERVAL_SECONDS=86400
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PYTHON_BIN="${PYTHON_BIN:-python3}"
readonly PLOT_DIR="$SCRIPT_DIR/plots"

last_cleanup=$(date +%s)

trap 'printf "[%s] Stopping scheduler.\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 0' INT TERM

cd "$SCRIPT_DIR"


cleanup_plots() {
    printf '[%s] Cleaning old plots...\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Get all timestamped plot files, sorted newest first.
    files=( "$PLOT_DIR"/tau_last_48h_*.png )

    # If there are no matching files, do nothing.
    if [ ! -e "${files[0]}" ]; then
        return
    fi

    declare -A days_seen

    # Sort newest -> oldest.
    while IFS= read -r file; do

        basename="$(basename "$file")"

        # Extract YYYYMMDD from:
        # tau_last_48h_YYYYMMDDTHHMMSSZ.png
        date_part="${basename#tau_last_48h_}"
        day="${date_part:0:8}"

        if [[ -n "${days_seen[$day]+x}" ]]; then
            # Already kept a newer plot from this day.
            rm -- "$file"
        else
            # Keep the newest plot from this day.
            days_seen[$day]=1
        fi

    done < <(printf '%s\n' "${files[@]}" | sort -r)

    printf '[%s] Plot cleanup complete.\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}


while true; do

    printf '[%s] Starting get_tau_last_24h.py\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if "$PYTHON_BIN" -u "$SCRIPT_DIR/get_tau_last_24h.py"; then
        printf '[%s] Run completed successfully.\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    else
        status=$?
        printf '[%s] Run failed with exit status %d; retrying in 15 minutes.\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" >&2
    fi


    # Clean up plots once every 24 hours.
    now=$(date +%s)

    if (( now - last_cleanup >= CLEANUP_INTERVAL_SECONDS )); then
        cleanup_plots
        last_cleanup=$now
    fi


    sleep "$INTERVAL_SECONDS" &
    wait $!

done