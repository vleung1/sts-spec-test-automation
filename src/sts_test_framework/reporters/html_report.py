"""
Generate a static HTML table: operation id, summary, path, expected/actual status, errors.
"""
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def _environment_label(host_or_env: str) -> str:
    """Map hostname or URL to friendly environment name: QA, Stage, or Prod."""
    s = (host_or_env or "").lower()
    if "qa" in s:
        return "QA"
    if "stage" in s or "staging" in s:
        return "Stage"
    if "prod" in s or s == "sts.cancer.gov" or s.startswith("sts.cancer.gov"):
        return "Prod"
    return host_or_env or ""


def write_html_report(
    summary: dict,
    results: list[dict],
    out_path: str | Path,
    title: str = "STS v2 API Test Report",
    base_url: str | None = None,
    environment: str | None = None,
    model_handle: str | None = None,
    model_version: str | None = None,
    discovery_info: dict | None = None,
    cases_generated: dict | None = None,
) -> None:
    """Build rows from ``results``, render via ``_template``, write UTF-8 HTML to disk.

    discovery_info: optional dict of discovery keys/values (e.g. model_handle, node_handle, ...).
    cases_generated: optional dict with keys total, positive, negative (counts of generated cases).
    """
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in results:
        status = "Pass" if r.get("passed") else "Fail"
        duration = r.get("duration")
        duration_str = f"{duration * 1000:.0f} ms" if duration is not None else "-"
        note = r.get("pagination_pair_display_note")
        if note:
            # Do not escape here: the full cell is passed through _esc() in _template.
            # Escaping the note twice turns "<2" into visible "&lt;2" in the browser.
            duration_str = f"{duration_str} — {note}"
        path_raw = r.get("path_display") or r.get("path", "")
        path_cell = f"<code>{_esc(path_raw)}</code>"
        rows.append({
            "operation_id": r.get("operation_id", ""),
            "summary": r.get("summary", ""),
            "path": path_cell,
            "status": status,
            "expected": r.get("expected_status"),
            "actual": r.get("actual_status"),
            "duration": duration_str,
            "perf_warning": bool(r.get("perf_warning")),
            "error": r.get("error") or "",
        })

    if environment is None and base_url:
        try:
            environment = urlparse(base_url).netloc or base_url
        except Exception:
            environment = base_url

    environment_label = _environment_label(environment) if environment else environment
    html = _template(
        title, summary, rows,
        base_url=base_url,
        environment=environment_label,
        model_handle=model_handle,
        model_version=model_version,
        discovery_info=discovery_info,
        cases_generated=cases_generated,
    )
    path.write_text(html, encoding="utf-8")


def _template(
    title: str,
    summary: dict,
    rows: list[dict],
    base_url: str | None = None,
    environment: str | None = None,
    model_handle: str | None = None,
    model_version: str | None = None,
    discovery_info: dict | None = None,
    cases_generated: dict | None = None,
) -> str:
    """Assemble full HTML document string with inline CSS and result table rows."""
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    p50 = summary.get("p50_ms")
    p90 = summary.get("p90_ms")
    p95 = summary.get("p95_ms")
    avg = summary.get("avg_ms")
    p95_str = f"{p95} ms" if p95 is not None else "N/A"
    slow_count = summary.get("slow_count", 0)
    slow_requests = summary.get("slow_requests", [])
    perf_threshold = summary.get("perf_threshold_ms", 2000)

    env_block = ""
    env_lines = []
    if environment is not None:
        env_lines.append(f"<strong>Environment:</strong> {_esc(environment)}")
    if base_url is not None:
        env_lines.append(f"<strong>URL:</strong> <code>{_esc(base_url)}</code>")
    if model_handle is not None or model_version is not None:
        data_model = _esc(model_handle or "")
        if model_version:
            data_model = f"{data_model} / {_esc(model_version)}" if data_model else _esc(model_version)
        if data_model:
            env_lines.append(f"<strong>Data model:</strong> {data_model}")
    if env_lines:
        env_block = '<div class="env">' + " &nbsp;|&nbsp; ".join(env_lines) + "</div>"

    discovery_block = ""
    if discovery_info:
        parts = [f"{k}={_esc(repr(v))}" for k, v in discovery_info.items()]
        discovery_block = '<div class="discovery"><strong>Discovery:</strong> ' + " ".join(parts) + "</div>"
    cases_block = ""
    if cases_generated:
        t = cases_generated.get("total", 0)
        pos = cases_generated.get("positive", 0)
        neg = cases_generated.get("negative", 0)
        cases_block = f'<div class="cases-generated"><strong>Generated cases:</strong> {t} total ({pos} positive, {neg} negative).</div>'

    # Performance summary block
    perf_stats_html = (
        f"<span><strong>Avg:</strong> {avg} ms</span>"
        f"<span><strong>P50:</strong> {p50} ms</span>"
        f"<span><strong>P90:</strong> {p90} ms</span>"
        f"<span><strong>P95:</strong> {p95_str}</span>"
    ) if p95 is not None else ""

    if slow_count > 0:
        slow_rows_html = "".join(
            f"<tr><td><code>{_esc(s['operation_id'])}</code></td>"
            f"<td><code>{_esc(s['path'])}</code></td>"
            f"<td>{_esc(str(s['duration_ms']))} ms</td></tr>"
            for s in slow_requests
        )
        slow_detail = (
            f'<details><summary>{slow_count} slow request(s) above {perf_threshold} ms — click to expand</summary>'
            f'<table class="slow-table"><thead><tr><th>Operation</th><th>Path</th><th>Duration</th></tr></thead>'
            f'<tbody>{slow_rows_html}</tbody></table></details>'
        )
    else:
        slow_detail = f'<span class="perf-ok">No requests exceeded the {perf_threshold} ms threshold.</span>'

    perf_block = (
        f'<div class="perf-summary">'
        f'<strong>Performance:</strong>&nbsp; {perf_stats_html} &nbsp;|&nbsp; '
        f'<strong>Slow (&gt;{perf_threshold} ms):</strong> {slow_count}'
        f'</div>'
        f'<div class="perf-detail">{slow_detail}</div>'
    ) if perf_stats_html else ""

    rows_html = "".join(
        f"""
        <tr>
            <td>{_esc(r['operation_id'])}</td>
            <td>{_esc(r['summary'])}</td>
            <td class="path-col">{r['path']}</td>
            <td class="status-{r['status'].lower()}">{r['status']}</td>
            <td>{r['expected']}</td>
            <td>{r['actual']}</td>
            <td class="{'duration-slow' if r['perf_warning'] else ''}">{_esc(r['duration'])}</td>
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
        .meta {{ color: #666; margin-bottom: 0.5rem; }}
        .env {{ color: #444; margin-bottom: 0.5rem; font-size: 0.95rem; }}
        .env code {{ background: #f0f0f0; padding: 0.15rem 0.4rem; border-radius: 3px; }}
        .discovery, .cases-generated {{ color: #444; margin-bottom: 0.5rem; font-size: 0.9rem; font-family: ui-monospace, monospace; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }}
        th {{ background: #f5f5f5; }}
        .status-pass {{ background: #d4edda; color: #155724; font-weight: 600; }}
        .status-fail {{ background: #f8d7da; color: #721c24; font-weight: 600; }}
        .duration-slow {{ background: #fff3cd; color: #856404; font-weight: 600; }}
        .summary {{ margin-bottom: 0.75rem; }}
        .summary span {{ margin-right: 1.5rem; }}
        .perf-summary {{ color: #444; margin-bottom: 0.4rem; font-size: 0.9rem; }}
        .perf-summary span {{ margin-right: 1.2rem; }}
        .perf-detail {{ margin-bottom: 1.25rem; font-size: 0.88rem; color: #555; }}
        .perf-ok {{ color: #155724; }}
        .slow-table {{ border-collapse: collapse; margin-top: 0.5rem; width: 100%; }}
        .slow-table th, .slow-table td {{ border: 1px solid #ddd; padding: 0.3rem 0.6rem; text-align: left; font-size: 0.85rem; }}
        .slow-table th {{ background: #f5f5f5; }}
        details summary {{ cursor: pointer; color: #856404; font-weight: 600; }}
    </style>
</head>
<body>
    <h1>{_esc(title)}</h1>
    <p class="meta">Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
    {env_block}
    {discovery_block}
    {cases_block}
    <div class="summary">
        <span><strong>Total:</strong> {total}</span>
        <span><strong>Passed:</strong> {passed}</span>
        <span><strong>Failed:</strong> {failed}</span>
        <span><strong>P95 response:</strong> {p95_str}</span>
    </div>
    {perf_block}
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
    """Escape HTML special characters for safe insertion in templates."""
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
