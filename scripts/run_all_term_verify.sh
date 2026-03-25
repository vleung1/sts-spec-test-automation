#!/usr/bin/env bash
# Run every tests/term_verify/*_term_verify.py script with limited parallelism (default: 2 at a time).
# All CLI arguments (e.g. --limit 50, --warn-only) are forwarded to each script.
#
# Environment:
#   STS_TERM_VERIFY_WORKERS  Max scripts to run at once (default: 2; set to 1 for sequential).
#
# Usage (from project root):
#   bash scripts/run_all_term_verify.sh
#   bash scripts/run_all_term_verify.sh --warn-only
#   bash scripts/run_all_term_verify.sh --limit 50
#   STS_TERM_VERIFY_WORKERS=1 bash scripts/run_all_term_verify.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=parser_agent_hook.sh
source "$_SCRIPT_DIR/parser_agent_hook.sh"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

parser_agent_print_preamble "run_all_term_verify.sh" "after term-verify scripts"

mkdir -p "$REPO_ROOT/logs"
LOGFILE="$REPO_ROOT/logs/term_verify_$(date +%Y-%m-%dT%H-%M-%S).log"

WORKERS="${STS_TERM_VERIFY_WORKERS:-2}"
case "$WORKERS" in
  '' | *[!0-9]*) WORKERS=2 ;;
esac
if [ "$WORKERS" -lt 1 ]; then
  WORKERS=1
fi

scripts=()
for f in "$REPO_ROOT"/tests/term_verify/*_term_verify.py; do
  [ -f "$f" ] || continue
  scripts+=("$f")
done

count=${#scripts[@]}
if [ "$count" -eq 0 ]; then
  echo "No *_term_verify.py scripts found under tests/term_verify/." >&2
  exit 1
fi

failfile=$(mktemp "${TMPDIR:-/tmp}/term_verify_fail.XXXXXX")
trap 'rm -f "$failfile"' EXIT
: >"$failfile"

# Log lines from parallel jobs may interleave; each block is still delimited by === lines.
# shellcheck disable=SC2016
printf '%s\0' "${scripts[@]}" | xargs -0 -n1 -P"$WORKERS" -I{} bash -c '
  script="$1"
  shift
  name="$(basename "$script")"
  echo "=== Running $name ==="
  if python3 "$script" "$@"; then
    echo "=== $name finished (OK) ==="
  else
    echo "=== $name finished (FAILED) ==="
    echo "$name" >>"'"$failfile"'"
  fi
  echo
' _ {} "$@" 2>&1 | tee "$LOGFILE"

xc=${PIPESTATUS[0]}

failed=()
if [ -s "$failfile" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] && failed+=("$line")
  done <"$failfile"
fi

echo "--- Summary: $count script(s) run, ${#failed[@]} failed ---"

final_rc=0
if [ "${#failed[@]}" -gt 0 ]; then
  printf '  FAILED: %s\n' "${failed[@]}" >&2
  final_rc=1
elif [ "$xc" -ne 0 ]; then
  echo "xargs exited with $xc" >&2
  final_rc="$xc"
else
  echo "All term-verify scripts completed successfully."
fi

# parser_agent reads LOGFILE only; lines above were printed after tee. Append the same summary so detection/Bedrock see failures.
{
  echo ""
  echo "--- Summary (appended for parser_agent; same as console above) ---"
  echo "--- Summary: $count script(s) run, ${#failed[@]} failed ---"
  if [ "${#failed[@]}" -gt 0 ]; then
    printf '  FAILED: %s\n' "${failed[@]}"
  fi
  if [ "$xc" -ne 0 ] && [ "${#failed[@]}" -eq 0 ]; then
    echo "xargs exited with $xc"
  fi
} >>"$LOGFILE"

parser_agent_run_if_ok "$REPO_ROOT" "$LOGFILE"
exit "$final_rc"
