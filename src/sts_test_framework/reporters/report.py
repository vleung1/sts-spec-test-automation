"""
Roll up per-case results into summary stats and emit machine-readable JSON reports.
"""
import statistics
from pathlib import Path


def aggregate_results(results: list[dict], perf_threshold_ms: int | None = None) -> dict:
    """
    Compute totals, per-tag pass counts, per-operation last result, P95 latency, error list.

    Returns:
        Dict suitable for embedding in JSON/HTML reports.
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    by_tag = {}
    by_operation = {}
    durations = [r.get("duration", 0) for r in results if r.get("duration") is not None]
    errors = [r.get("error") for r in results if r.get("error")]

    for r in results:
        tag = r.get("tag") or "unknown"
        by_tag[tag] = by_tag.get(tag, {"total": 0, "passed": 0})
        by_tag[tag]["total"] += 1
        if r.get("passed"):
            by_tag[tag]["passed"] += 1

        op = r.get("operation_id") or "unknown"
        by_operation[op] = {"passed": r.get("passed"), "duration": r.get("duration"), "error": r.get("error")}

    sorted_dur = sorted(durations)
    n = len(sorted_dur)

    def _percentile(pct: float) -> float | None:
        if not sorted_dur:
            return None
        idx = min(int(n * pct), n - 1)
        return round(sorted_dur[idx] * 1000, 2)

    p50_ms = _percentile(0.50)
    p90_ms = _percentile(0.90)
    p95_ms = _percentile(0.95)
    avg_ms = round(statistics.mean(sorted_dur) * 1000, 2) if sorted_dur else None

    threshold = perf_threshold_ms if perf_threshold_ms is not None else 2000
    slow_requests = []
    for r in results:
        d = r.get("duration")
        if d is not None and d * 1000 > threshold:
            slow_requests.append({
                "operation_id": r.get("operation_id", ""),
                "path": r.get("path_display") or r.get("path", ""),
                "duration_ms": round(d * 1000, 2),
            })
    slow_count = len(slow_requests)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "by_tag": by_tag,
        "by_operation": by_operation,
        "durations_ms": [round(d * 1000, 2) for d in durations],
        "avg_ms": avg_ms,
        "p50_ms": p50_ms,
        "p90_ms": p90_ms,
        "p95_ms": p95_ms,
        "perf_threshold_ms": threshold,
        "slow_count": slow_count,
        "slow_requests": slow_requests,
        "errors": [e for e in errors if e],
    }


def write_json_report(summary: dict, results: list[dict], out_path: str | Path) -> None:
    """Serialize ``{"summary": ..., "results": [...]}`` to ``out_path`` (UTF-8, indented)."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "results": results}
    path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
