"""
Performance report writers: JSON and HTML for ``run_perf_tests`` output.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runners.performance import PerfResult, PerfStats


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def write_perf_json_report(
    stats: "PerfStats",
    raw_results: list["PerfResult"],
    out_path: str | Path,
) -> None:
    """Write machine-readable JSON with all stats and raw per-request timings."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "summary": {
            "total_requests": stats.total_requests,
            "error_count": stats.error_count,
            "error_rate_pct": stats.error_rate_pct,
            "throughput_rps": stats.throughput_rps,
            "wall_time_s": stats.wall_time_s,
            "concurrency": stats.concurrency,
            "iterations": stats.iterations,
            "perf_threshold_ms": stats.perf_threshold_ms,
            "slow_count": stats.slow_count,
            "latency": {
                "min_ms": stats.min_ms,
                "avg_ms": stats.avg_ms,
                "p50_ms": stats.p50_ms,
                "p90_ms": stats.p90_ms,
                "p95_ms": stats.p95_ms,
                "p99_ms": stats.p99_ms,
                "max_ms": stats.max_ms,
            },
        },
        "by_endpoint": [
            {
                "operation_id": e.operation_id,
                "count": e.count,
                "error_count": e.error_count,
                "min_ms": e.min_ms,
                "avg_ms": e.avg_ms,
                "p50_ms": e.p50_ms,
                "p90_ms": e.p90_ms,
                "p95_ms": e.p95_ms,
                "p99_ms": e.p99_ms,
                "max_ms": e.max_ms,
            }
            for e in stats.by_endpoint
        ],
        "slowest_10": [
            {
                "operation_id": r.operation_id,
                "path": r.path,
                "iteration": r.iteration,
                "status_code": r.status_code,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in stats.slowest
        ],
        "raw_results": [
            {
                "operation_id": r.operation_id,
                "path": r.path,
                "iteration": r.iteration,
                "status_code": r.status_code,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in raw_results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def write_perf_html_report(
    stats: "PerfStats",
    raw_results: list["PerfResult"],
    out_path: str | Path,
    base_url: str | None = None,
    model_handle: str | None = None,
    model_version: str | None = None,
) -> None:
    """Write a self-contained HTML performance report."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = _perf_template(stats, raw_results, base_url=base_url,
                          model_handle=model_handle, model_version=model_version)
    path.write_text(html, encoding="utf-8")


def _fmt(value: float | None, unit: str = "ms") -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f} {unit}"


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


def _latency_histogram(raw_results: list["PerfResult"]) -> str:
    """Build a simple SVG bar chart of response time buckets."""
    buckets = [
        ("0–100 ms",   0,     100),
        ("100–500 ms", 100,   500),
        ("500ms–1s",   500,   1000),
        ("1–2 s",      1000,  2000),
        ("2–5 s",      2000,  5000),
        ("5 s+",       5000,  float("inf")),
    ]
    counts = [0] * len(buckets)
    for r in raw_results:
        d = r.duration_ms
        for i, (_, lo, hi) in enumerate(buckets):
            if lo <= d < hi:
                counts[i] += 1
                break

    total = sum(counts) or 1
    max_count = max(counts) or 1
    bar_max_w = 300

    rows = ""
    colors = ["#4ade80", "#86efac", "#fbbf24", "#fb923c", "#f87171", "#ef4444"]
    for i, ((label, _, _), count) in enumerate(zip(buckets, counts)):
        bar_w = int(count / max_count * bar_max_w)
        pct = f"{count / total * 100:.1f}%"
        rows += (
            f'<tr>'
            f'<td class="bucket-label">{_esc(label)}</td>'
            f'<td><div class="bar" style="width:{bar_w}px;background:{colors[i]}"></div></td>'
            f'<td class="bucket-count">{count} ({pct})</td>'
            f'</tr>'
        )
    return f'<table class="histogram">{rows}</table>'


def _perf_template(
    stats: "PerfStats",
    raw_results: list["PerfResult"],
    base_url: str | None = None,
    model_handle: str | None = None,
    model_version: str | None = None,
) -> str:
    title = "STS v2 Performance Report"
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    meta_parts = []
    if model_handle:
        label = model_handle
        if model_version:
            label += f" / {model_version}"
        meta_parts.append(f"<strong>Model:</strong> {_esc(label)}")
    if base_url:
        meta_parts.append(f"<strong>URL:</strong> <code>{_esc(base_url)}</code>")
    meta_parts.append(f"<strong>Concurrency:</strong> {stats.concurrency} threads")
    meta_parts.append(f"<strong>Iterations:</strong> {stats.iterations}")
    meta_parts.append(f"<strong>Slow threshold:</strong> {stats.perf_threshold_ms} ms")
    meta_html = " &nbsp;|&nbsp; ".join(meta_parts)

    # Overall stats cards
    error_class = "stat-bad" if stats.error_rate_pct > 0 else "stat-good"
    slow_class = "stat-warn" if stats.slow_count > 0 else "stat-good"
    stats_cards = f"""
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Total Requests</div>
            <div class="stat-value">{stats.total_requests:,}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Wall Time</div>
            <div class="stat-value">{stats.wall_time_s:.1f} s</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Throughput</div>
            <div class="stat-value">{stats.throughput_rps:.1f} req/s</div>
        </div>
        <div class="stat-card {error_class}">
            <div class="stat-label">Errors</div>
            <div class="stat-value">{stats.error_count} ({stats.error_rate_pct:.1f}%)</div>
        </div>
        <div class="stat-card {slow_class}">
            <div class="stat-label">Slow (&gt;{stats.perf_threshold_ms} ms)</div>
            <div class="stat-value">{stats.slow_count}</div>
        </div>
    </div>
    """

    # Latency percentiles
    latency_cards = f"""
    <div class="stats-grid latency-grid">
        <div class="stat-card"><div class="stat-label">Min</div><div class="stat-value">{_fmt(stats.min_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">Avg</div><div class="stat-value">{_fmt(stats.avg_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">P50</div><div class="stat-value">{_fmt(stats.p50_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">P90</div><div class="stat-value">{_fmt(stats.p90_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">P95</div><div class="stat-value">{_fmt(stats.p95_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">P99</div><div class="stat-value">{_fmt(stats.p99_ms)}</div></div>
        <div class="stat-card"><div class="stat-label">Max</div><div class="stat-value">{_fmt(stats.max_ms)}</div></div>
    </div>
    """

    # Per-endpoint table (sorted by P95 desc — slowest first)
    endpoint_rows = "".join(
        f"<tr>"
        f"<td><code>{_esc(e.operation_id)}</code></td>"
        f"<td>{e.count}</td>"
        f"<td>{e.error_count}</td>"
        f"<td>{e.min_ms:.1f}</td>"
        f"<td>{e.avg_ms:.1f}</td>"
        f"<td>{e.p50_ms:.1f}</td>"
        f"<td>{e.p90_ms:.1f}</td>"
        f'<td class="{"p95-slow" if e.p95_ms > stats.perf_threshold_ms else ""}">{e.p95_ms:.1f}</td>'
        f"<td>{e.p99_ms:.1f}</td>"
        f"<td>{e.max_ms:.1f}</td>"
        f"</tr>"
        for e in stats.by_endpoint
    )

    # Slowest 10 requests
    slowest_rows = "".join(
        f"<tr>"
        f"<td><code>{_esc(r.operation_id)}</code></td>"
        f"<td><code>{_esc(r.path)}</code></td>"
        f"<td>{r.iteration}</td>"
        f"<td>{r.status_code}</td>"
        f"<td>{r.duration_ms:.1f} ms</td>"
        f"<td>{_esc(r.error or '')}</td>"
        f"</tr>"
        for r in stats.slowest
    )

    histogram_html = _latency_histogram(raw_results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{_esc(title)}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 1rem 2rem; color: #222; }}
        h1 {{ margin-bottom: 0.2rem; }}
        h2 {{ margin: 1.5rem 0 0.5rem; font-size: 1.05rem; color: #444; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }}
        .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1.25rem; }}
        .meta code {{ background: #f0f0f0; padding: 0.1rem 0.35rem; border-radius: 3px; }}
        .stats-grid {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; }}
        .stat-card {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 0.6rem 1rem; min-width: 120px; }}
        .stat-label {{ font-size: 0.75rem; color: #666; text-transform: uppercase; letter-spacing: 0.04em; }}
        .stat-value {{ font-size: 1.4rem; font-weight: 700; color: #222; margin-top: 0.1rem; }}
        .stat-good .stat-value {{ color: #155724; }}
        .stat-warn .stat-value {{ color: #856404; }}
        .stat-bad .stat-value {{ color: #721c24; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; font-size: 0.88rem; }}
        th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.65rem; text-align: left; }}
        th {{ background: #f5f5f5; font-size: 0.82rem; }}
        .p95-slow {{ background: #fff3cd; color: #856404; font-weight: 600; }}
        .histogram {{ border: none; width: auto; }}
        .histogram td {{ border: none; padding: 0.2rem 0.5rem; }}
        .bucket-label {{ font-size: 0.82rem; color: #444; white-space: nowrap; }}
        .bucket-count {{ font-size: 0.82rem; color: #555; }}
        .bar {{ height: 18px; border-radius: 3px; min-width: 2px; }}
    </style>
</head>
<body>
    <h1>{_esc(title)}</h1>
    <p class="meta">Generated {generated} &nbsp;|&nbsp; {meta_html}</p>

    <h2>Run Summary</h2>
    {stats_cards}

    <h2>Latency Percentiles</h2>
    {latency_cards}

    <h2>Latency Distribution</h2>
    {histogram_html}

    <h2>Per-Endpoint Breakdown (sorted by P95, slowest first)</h2>
    <table>
        <thead>
            <tr>
                <th>Operation</th>
                <th>Count</th>
                <th>Errors</th>
                <th>Min (ms)</th>
                <th>Avg (ms)</th>
                <th>P50 (ms)</th>
                <th>P90 (ms)</th>
                <th>P95 (ms)</th>
                <th>P99 (ms)</th>
                <th>Max (ms)</th>
            </tr>
        </thead>
        <tbody>{endpoint_rows}</tbody>
    </table>

    <h2>Slowest 10 Requests</h2>
    <table>
        <thead>
            <tr>
                <th>Operation</th>
                <th>Path</th>
                <th>Iteration</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Error</th>
            </tr>
        </thead>
        <tbody>{slowest_rows}</tbody>
    </table>
</body>
</html>
"""
