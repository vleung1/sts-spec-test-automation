#!/usr/bin/env bash
# Run all manual pytest tests with an HTML report.
# Extra arguments are forwarded to pytest (e.g. -m nullcde, -k some_test).
#
# After pytest, optionally runs parser_agent (Bedrock summaries on failures) only when
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION are all set and non-empty.
#
# Usage (from project root):
#   bash scripts/run_manual_tests.sh
#   bash scripts/run_manual_tests.sh -m nullcde
#   bash scripts/run_manual_tests.sh -k test_model_pvs
set -uo pipefail

_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=parser_agent_hook.sh
source "$_SCRIPT_DIR/parser_agent_hook.sh"

REPO_ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

parser_agent_print_preamble "run_manual_tests.sh" "after pytest"

mkdir -p logs
LOGFILE="logs/manual_$(date +%Y-%m-%dT%H-%M-%S).log"

pytest tests/test_manual/ -v \
  --html=reports/manual_tests.html \
  --self-contained-html \
  "$@" 2>&1 | tee "$LOGFILE"
rc=${PIPESTATUS[0]}

parser_agent_run_if_ok "$REPO_ROOT" "$LOGFILE"

exit "$rc"
