"""
HTML report: table of endpoints, status, duration, errors (api-tester style).
"""
from pathlib import Path
from datetime import datetime


def write_html_report(
    summary: dict,
    results: list[dict],
    out_path: str | Path,
    title: str = "STS v2 API Test Report",
) -> None:
    """Generate HTML report with coverage table and summary."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in results:
        status = "Pass" if r.get("passed") else "Fail"
        duration = r.get("duration")
        duration_str = f"{duration * 1000:.0f} ms" if duration is not None else "-"
        rows.append({
            "operation_id": r.get("operation_id", ""),
            "summary": r.get("summary", ""),
            "path": r.get("path", ""),
            "status": status,
            "expected": r.get("expected_status"),
            "actual": r.get("actual_status"),
            "duration": duration_str,
            "error": r.get("error") or "",
        })

    html = _template(title, summary, rows)
    path.write_text(html, encoding="utf-8")


def _template(title: str, summary: dict, rows: list[dict]) -> str:
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    p95 = summary.get("p95_ms")
    p95_str = f"{p95} ms" if p95 is not None else "N/A"

    rows_html = "".join(
        f"""
        <tr>
            <td>{_esc(r['operation_id'])}</td>
            <td>{_esc(r['summary'])}</td>
            <td><code>{_esc(r['path'])}</code></td>
            <td class="status-{r['status'].lower()}">{r['status']}</td>
            <td>{r['expected']}</td>
            <td>{r['actual']}</td>
            <td>{_esc(r['duration'])}</td>
            <td>{_esc(r['error'][:200] if r['error'] else '')}</td>
        </tr>
        """
        for r in rows
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{_esc(title)}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 1rem 2rem; }}
        h1 {{ margin-bottom: 0.25rem; }}
        .meta {{ color: #666; margin-bottom: 1.5rem; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }}
        th {{ background: #f5f5f5; }}
        .status-pass {{ color: green; }}
        .status-fail {{ color: #c00; }}
        .summary {{ margin-bottom: 1.5rem; }}
        .summary span {{ margin-right: 1.5rem; }}
    </style>
</head>
<body>
    <h1>{_esc(title)}</h1>
    <p class="meta">Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
    <div class="summary">
        <span><strong>Total:</strong> {total}</span>
        <span><strong>Passed:</strong> {passed}</span>
        <span><strong>Failed:</strong> {failed}</span>
        <span><strong>P95 response:</strong> {p95_str}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>Operation ID</th>
                <th>Summary</th>
                <th>Path</th>
                <th>Status</th>
                <th>Expected</th>
                <th>Actual</th>
                <th>Duration</th>
                <th>Error</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</body>
</html>
"""


def _esc(s: str) -> str:
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
