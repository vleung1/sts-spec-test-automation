#!/usr/bin/env bash
# Optional parser_agent (Bedrock): shared env check, user messages, and guarded run.
# Source from project scripts after defining REPO_ROOT:
#   _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=parser_agent_hook.sh
#   source "$_SCRIPT_DIR/parser_agent_hook.sh"

parser_agent_env_ok() {
  [ -n "${AWS_ACCESS_KEY_ID:-}" ] \
    && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ] \
    && [ -n "${AWS_REGION:-}" ]
}

# Args: $1 = invoking script label (e.g. run_manual_tests.sh)
#       $2 = phrase inserted in success line, e.g. "after pytest"
parser_agent_print_preamble() {
  local script_name=$1
  local after_phrase=$2
  if ! parser_agent_env_ok; then
    echo "${script_name}: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION are not all set." >&2
    echo "  Optional parser agent will be skipped. Export all three (and install boto3) to enable Bedrock summaries." >&2
  else
    echo "${script_name}: AWS credentials set; parser agent will run ${after_phrase} if failures are detected."
  fi
}

# Args: $1 = repo root, $2 = log file path (absolute or relative to cwd before cd)
parser_agent_run_if_ok() {
  local root=$1
  local log=$2
  if parser_agent_env_ok; then
    ( cd "$root" && python3 parser_agent/main.py "$log" ) || true
  fi
}
