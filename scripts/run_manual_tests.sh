#!/usr/bin/env bash
# Run all manual pytest tests with an HTML report.
# Extra arguments are forwarded to pytest (e.g. -m nullcde, -k some_test).
#
# Usage (from project root):
#   bash scripts/run_manual_tests.sh
#   bash scripts/run_manual_tests.sh -m nullcde
#   bash scripts/run_manual_tests.sh -k test_model_pvs
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

exec pytest tests/test_manual/ -v \
  --html=reports/manual_tests.html \
  --self-contained-html \
  "$@"
