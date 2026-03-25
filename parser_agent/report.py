"""Write an AI-generated failure summary to a timestamped Markdown report."""

from datetime import datetime, timezone
from pathlib import Path

from .config import BEDROCK_MODEL_ID, SUMMARY_DIR


def write_summary_report(
    summary_markdown: str,
    *,
    script_name: str,
    failure_count: int,
    timestamp: str | None = None,
) -> Path:
    """Write *summary_markdown* to ``reports/agent-summaries/summary_<ts>.md``.

    Returns the path of the written file.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    header = (
        f"# Test Failure Summary\n"
        f"- **Run:** {script_name}\n"
        f"- **Timestamp:** {timestamp}\n"
        f"- **Failures detected:** {failure_count}\n"
        f"- **Model:** {BEDROCK_MODEL_ID}\n"
    )

    report_path = SUMMARY_DIR / f"summary_{timestamp}.md"
    report_path.write_text(f"{header}\n{summary_markdown}\n")
    return report_path
