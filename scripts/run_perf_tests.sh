#!/usr/bin/env bash
# Run performance tests for all data models (one run per model, sequential).
#
# Reuses the STS_BASE_URL and STS_MODELS environment variables from the
# rest of the framework.  All extra arguments are forwarded to perf_cli
# (e.g. --concurrency, --iterations, --perf-threshold-ms, --fail-on-error-rate).
#
# Usage (from project root):
#   bash scripts/run_perf_tests.sh
#   bash scripts/run_perf_tests.sh --concurrency 10 --iterations 3
#   STS_BASE_URL=https://sts-stage.cancer.gov/v2 bash scripts/run_perf_tests.sh
#   STS_MODELS=CCDI,C3DC bash scripts/run_perf_tests.sh --concurrency 5
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

DEFAULT_MODELS="CDS CCDI CCDI-DCC ICDC CTDC C3DC PSDC mCODE PDC CRDC CRDCSearch CRDCSubmission"

if [ -n "${STS_MODELS:-}" ]; then
    IFS=',' read -ra MODEL_LIST <<< "$STS_MODELS"
else
    read -ra MODEL_LIST <<< "$DEFAULT_MODELS"
fi

mkdir -p logs
LOGFILE="logs/perf_$(date +%Y-%m-%dT%H-%M-%S).log"

failures=()
count=0

echo "=== STS v2 Performance Tests ==="
echo "Models: ${MODEL_LIST[*]}"
echo "Extra args: $*"
echo ""

for model in "${MODEL_LIST[@]}"; do
    count=$((count + 1))
    echo "--- [$count/${#MODEL_LIST[@]}] $model ---"
    if python3 -m sts_test_framework.perf_cli \
        --model "$model" \
        --release \
        "$@" 2>&1 | tee -a "$LOGFILE"; then
        echo "  $model: OK"
    else
        echo "  $model: FAILED" >&2
        failures+=("$model")
    fi
    echo ""
done

echo "=== Summary: ${#MODEL_LIST[@]} model(s) run, ${#failures[@]} failed ==="
if [ "${#failures[@]}" -gt 0 ]; then
    printf '  FAILED: %s\n' "${failures[@]}" >&2
    exit 1
fi
echo "All performance runs completed."
echo "Reports: reports/perf/<model>/"
exit 0
