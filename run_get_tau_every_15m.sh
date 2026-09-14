#!/usr/bin/env bash

set -u

readonly INTERVAL_SECONDS=900
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PYTHON_BIN="${PYTHON_BIN:-python3}"

trap 'printf "[%s] Stopping scheduler.\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 0' INT TERM

cd "$SCRIPT_DIR"

while true; do
    printf '[%s] Starting get_tau_last_24h.py\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if "$PYTHON_BIN" -u "$SCRIPT_DIR/get_tau_last_24h.py"; then
        printf '[%s] Run completed successfully.\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    else
        status=$?
        printf '[%s] Run failed with exit status %d; retrying in 15 minutes.\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" >&2
    fi

    sleep "$INTERVAL_SECONDS" &
    wait $!
done
