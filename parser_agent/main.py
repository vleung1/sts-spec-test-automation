#!/usr/bin/env python3
"""CLI entry point for the parser-agent.

Usage:
    python parser_agent/main.py <logfile>

Detects failures in the log file. If any are found, calls AWS Bedrock to
produce a summary and writes it to reports/agent-summaries/.
Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, and boto3.

Only invokes this when those three env vars are set.

Always exits 0 -- the agent is informational and should not block CI.
"""

import sys
import traceback
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from parser_agent.detect import detect_failures
from parser_agent.report import write_summary_report
from parser_agent.summarize import summarize_failures


def _run(log_path: str) -> None:
    result = detect_failures(log_path)

    if not result.has_failures:
        print("[parser-agent] No failures detected — skipping Bedrock call.")
        return

    print(
        f"[parser-agent] {len(result.matches)} failure(s) detected — "
        "calling Bedrock for summary..."
    )

    summary = summarize_failures(result)

    script_name = Path(log_path).stem
    report_path = write_summary_report(
        summary,
        script_name=script_name,
        failure_count=len(result.matches),
    )
    print(f"[parser-agent] Summary written to {report_path}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python parser_agent/main.py <logfile>", file=sys.stderr)
        sys.exit(0)

    log_path = sys.argv[1]
    try:
        _run(log_path)
    except Exception:
        print("[parser-agent] Error during analysis (non-blocking):", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
