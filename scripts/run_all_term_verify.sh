#!/usr/bin/env bash
# Run every tests/term_verify/*_term_verify.py script sequentially.
# All CLI arguments (e.g. --limit 50, --warn-only) are forwarded to each script.
#
# Usage (from project root):
#   bash scripts/run_all_term_verify.sh
#   bash scripts/run_all_term_verify.sh --warn-only
#   bash scripts/run_all_term_verify.sh --limit 50
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

failed=()
count=0

for script in "$REPO_ROOT"/tests/term_verify/*_term_verify.py; do
  [ -f "$script" ] || continue
  name="$(basename "$script")"
  echo "=== Running $name ==="
  if python3 "$script" "$@"; then
    echo "=== $name finished (OK) ==="
  else
    echo "=== $name finished (FAILED) ==="
    failed+=("$name")
  fi
  count=$((count + 1))
  echo
done

if [ "$count" -eq 0 ]; then
  echo "No *_term_verify.py scripts found under tests/term_verify/." >&2
  exit 1
fi

echo "--- Summary: $count script(s) run, ${#failed[@]} failed ---"

if [ "${#failed[@]}" -gt 0 ]; then
  printf "  FAILED: %s\n" "${failed[@]}" >&2
  exit 1
fi

echo "All term-verify scripts completed successfully."
exit 0
