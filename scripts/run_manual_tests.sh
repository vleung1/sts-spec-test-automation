#!/usr/bin/env bash
# Run all manual pytest tests with an HTML report.
# Extra arguments are forwarded to pytest (e.g. -m nullcde, -k some_test).
#
# Usage (from project root):
#   bash scripts/run_manual_tests.sh
#   bash scripts/run_manual_tests.sh -m nullcde
#   bash scripts/run_manual_tests.sh -k test_model_pvs
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p logs
LOGFILE="logs/manual_$(date +%Y-%m-%dT%H-%M-%S).log"

pytest tests/test_manual/ -v \
  --html=reports/manual_tests.html \
  --self-contained-html \
  "$@" 2>&1 | tee "$LOGFILE"
rc=${PIPESTATUS[0]}

python3 parser_agent/main.py "$LOGFILE"
exit "$rc"
