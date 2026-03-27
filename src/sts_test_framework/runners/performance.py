"""
Concurrent performance runner for STS v2 API.

Reuses the existing ``APIClient`` and generated test cases; fires requests via
``ThreadPoolExecutor`` with configurable concurrency and per-case iteration count.
All results are informational -- slow requests never cause failures unless
``fail_on_error_rate`` is explicitly set.

Typical use via ``perf_cli.py``:

    python -m sts_test_framework.perf_cli --model CCDI --concurrency 10 --iterations 3
"""
from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..client import APIClient


@dataclass
class PerfResult:
    """Single request outcome from the perf runner."""

    operation_id: str
    path: str
    iteration: int
    status_code: int
    duration_ms: float
    error: str | None = None

    @property
    def is_error(self) -> bool:
        """True when status_code is 0 (network error) or >= 500."""
        return self.status_code == 0 or self.status_code >= 500


@dataclass
class EndpointStats:
    """Aggregated latency stats for one operation_id."""

    operation_id: str
    count: int
    error_count: int
    min_ms: float
    max_ms: float
    avg_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class PerfStats:
    """Overall run statistics returned by ``run_perf_tests``."""

    total_requests: int
    error_count: int
    error_rate_pct: float
    throughput_rps: float          # requests per second (wall clock)
    wall_time_s: float
    min_ms: float | None
    max_ms: float | None
    avg_ms: float | None
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    slowest: list[PerfResult]      # top-10 slowest individual requests
    by_endpoint: list[EndpointStats]
    perf_threshold_ms: int
    slow_count: int                # requests above threshold
    concurrency: int
    iterations: int


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    idx = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return round(sorted_values[idx], 2)


def _endpoint_stats(op_id: str, results: list[PerfResult]) -> EndpointStats:
    durations = sorted(r.duration_ms for r in results)
    errors = sum(1 for r in results if r.is_error)
    return EndpointStats(
        operation_id=op_id,
        count=len(results),
        error_count=errors,
        min_ms=round(min(durations), 2) if durations else 0.0,
        max_ms=round(max(durations), 2) if durations else 0.0,
        avg_ms=round(statistics.mean(durations), 2) if durations else 0.0,
        p50_ms=_percentile(durations, 0.50) or 0.0,
        p90_ms=_percentile(durations, 0.90) or 0.0,
        p95_ms=_percentile(durations, 0.95) or 0.0,
        p99_ms=_percentile(durations, 0.99) or 0.0,
    )


def run_perf_tests(
    client: "APIClient",
    cases: list[dict],
    concurrency: int = 2,
    iterations: int = 1,
    ramp_up_seconds: float = 0.0,
    perf_threshold_ms: int = 2000,
    on_request_done: Callable[[PerfResult], None] | None = None,
) -> tuple[list[PerfResult], PerfStats]:
    """
    Execute ``cases`` concurrently (``concurrency`` threads) repeated ``iterations`` times.

    Only positive cases (``negative=False``) are included.  Each request is fired
    independently -- no ordering guarantees between iterations.

    Args:
        client: Pre-configured ``APIClient``.
        cases: Generated test cases (negative cases are filtered out).
        concurrency: Max concurrent threads.
        iterations: How many times each case is repeated.
        ramp_up_seconds: If > 0, stagger thread starts evenly over this window.
        perf_threshold_ms: Threshold used to populate ``PerfStats.slow_count``.
        on_request_done: Optional callback fired after each request completes.

    Returns:
        ``(raw_results, stats)``
    """
    positive_cases = [c for c in cases if not c.get("negative", False)]
    if not positive_cases:
        empty_stats = PerfStats(
            total_requests=0, error_count=0, error_rate_pct=0.0,
            throughput_rps=0.0, wall_time_s=0.0,
            min_ms=None, max_ms=None, avg_ms=None,
            p50_ms=None, p90_ms=None, p95_ms=None, p99_ms=None,
            slowest=[], by_endpoint=[],
            perf_threshold_ms=perf_threshold_ms, slow_count=0,
            concurrency=concurrency, iterations=iterations,
        )
        return [], empty_stats

    # Build full work list: (case, iteration_number)
    work: list[tuple[dict, int]] = [
        (case, i + 1)
        for i in range(iterations)
        for case in positive_cases
    ]

    results: list[PerfResult] = []
    results_lock = threading.Lock()

    def _execute(case: dict, iteration: int, delay: float) -> PerfResult:
        if delay > 0:
            time.sleep(delay)
        path = case.get("path") or ""
        params = case.get("params")
        op_id = case.get("operation_id", "")
        response = client.get(path, params)
        r = PerfResult(
            operation_id=op_id,
            path=path,
            iteration=iteration,
            status_code=response.status_code,
            duration_ms=round(response.duration * 1000, 3),
            error=None if response.status_code not in (0,) else str(response.body)[:200],
        )
        return r

    # Compute per-thread ramp-up delay
    delays: list[float] = []
    if ramp_up_seconds > 0 and len(work) > 1:
        step = ramp_up_seconds / len(work)
        delays = [i * step for i in range(len(work))]
    else:
        delays = [0.0] * len(work)

    wall_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_execute, case, iteration, delay): (case, iteration)
            for (case, iteration), delay in zip(work, delays)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                case, iteration = futures[future]
                result = PerfResult(
                    operation_id=case.get("operation_id", ""),
                    path=case.get("path") or "",
                    iteration=iteration,
                    status_code=0,
                    duration_ms=0.0,
                    error=str(exc)[:200],
                )
            with results_lock:
                results.append(result)
            if on_request_done:
                on_request_done(result)

    wall_time = time.monotonic() - wall_start

    # Aggregate
    all_durations = sorted(r.duration_ms for r in results)
    error_count = sum(1 for r in results if r.is_error)
    total = len(results)
    error_rate = (error_count / total * 100) if total else 0.0
    throughput = total / wall_time if wall_time > 0 else 0.0

    by_op: dict[str, list[PerfResult]] = {}
    for r in results:
        by_op.setdefault(r.operation_id, []).append(r)
    endpoint_stats = sorted(
        [_endpoint_stats(op_id, op_results) for op_id, op_results in by_op.items()],
        key=lambda s: s.p95_ms,
        reverse=True,
    )

    slow_count = sum(1 for r in results if r.duration_ms > perf_threshold_ms)
    slowest_10 = sorted(results, key=lambda r: r.duration_ms, reverse=True)[:10]

    stats = PerfStats(
        total_requests=total,
        error_count=error_count,
        error_rate_pct=round(error_rate, 2),
        throughput_rps=round(throughput, 2),
        wall_time_s=round(wall_time, 2),
        min_ms=_percentile(all_durations, 0.0) if all_durations else None,
        max_ms=round(max(all_durations), 2) if all_durations else None,
        avg_ms=round(statistics.mean(all_durations), 2) if all_durations else None,
        p50_ms=_percentile(all_durations, 0.50),
        p90_ms=_percentile(all_durations, 0.90),
        p95_ms=_percentile(all_durations, 0.95),
        p99_ms=_percentile(all_durations, 0.99),
        slowest=slowest_10,
        by_endpoint=endpoint_stats,
        perf_threshold_ms=perf_threshold_ms,
        slow_count=slow_count,
        concurrency=concurrency,
        iterations=iterations,
    )

    return results, stats
