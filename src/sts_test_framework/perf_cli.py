"""
Performance test CLI for the STS v2 API.

Reuses the existing spec-loading, discovery, and case-generation pipeline but
runs requests concurrently and writes a dedicated performance report.

Usage (from project root, with venv active):

    python -m sts_test_framework.perf_cli --model CCDI --release
    python -m sts_test_framework.perf_cli --model C3DC --concurrency 10 --iterations 3
    python -m sts_test_framework.perf_cli --model CCDI --fail-on-error-rate 5.0

Exit codes:
    0  All done (even if slow requests were found — slowness is informational)
    1  HTTP error rate exceeded ``--fail-on-error-rate`` threshold
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    import argparse

    from .config import DEFAULT_STS_BASE_URL, bundled_spec_path, sts_base_url

    parser = argparse.ArgumentParser(
        description="STS v2 API Performance Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # -- target --
    parser.add_argument("--spec", default=None, help="Path to OpenAPI spec (v2.json)")
    parser.add_argument(
        "--base-url", default=None,
        help=f"STS base URL including /v2 (default: STS_BASE_URL or {DEFAULT_STS_BASE_URL})",
    )
    parser.add_argument("--model", default=None,
                        help="Model handle to test (e.g. CCDI). Omit to use first model.")
    parser.add_argument("--release", action="store_true",
                        help="Use latest release version (no hyphen) for the model.")
    parser.add_argument("--tags", default=None,
                        help="Comma-separated tags to include (default: all)")
    parser.add_argument("--report", default=None,
                        help="Output directory for reports (default: reports/perf/<model>/)")

    # -- perf config --
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Number of concurrent request threads.")
    parser.add_argument("--iterations", type=int, default=1,
                        help="How many times to repeat each test case.")
    parser.add_argument("--ramp-up", type=float, default=0.0,
                        help="Stagger thread starts over this many seconds (0 = no ramp-up).")
    parser.add_argument("--perf-threshold-ms", type=int, default=2000,
                        help="Requests above this duration are highlighted as slow in the report.")
    parser.add_argument("--fail-on-error-rate", type=float, default=None, metavar="PCT",
                        help="Exit 1 if HTTP error rate (5xx or network failures) exceeds PCT %%. "
                             "Slowness alone never causes failure.")

    args = parser.parse_args()

    base_url = (args.base_url or sts_base_url()).rstrip("/")
    spec_path = Path(args.spec) if args.spec else bundled_spec_path()
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None

    from .loader import load_spec, get_paths
    from .client import APIClient
    from .discover import discover
    from .generator import generate_cases
    from .runners.performance import run_perf_tests
    from .reporters.perf_report import write_perf_html_report, write_perf_json_report

    # Step 1: Load spec
    print(f"Loading spec: {spec_path}", flush=True)
    spec = load_spec(spec_path)
    paths = get_paths(spec)
    print(f"Spec loaded: {len(paths)} paths.", flush=True)

    # Step 2: Discovery
    client = APIClient(base_url)
    print("Running discovery...", flush=True)
    test_data = discover(
        client,
        model_handle=args.model.strip() if args.model else None,
        use_release_version=args.release,
    )
    if not test_data:
        print("Discovery returned no data. Check that STS is reachable and the model exists.",
              file=sys.stderr)
        sys.exit(1)

    model_handle = test_data.get("model_handle", args.model or "unknown")
    model_version = test_data.get("model_version", "")
    print(f"Model: {model_handle} / {model_version}", flush=True)

    # Step 3: Generate positive-only cases
    cases = generate_cases(spec, test_data, include_negative=False, tag_filter=tag_filter)
    if not cases:
        print("No test cases generated. Check discovery and tag filter.", file=sys.stderr)
        sys.exit(1)
    print(f"Generated {len(cases)} positive cases.", flush=True)

    # Step 4: Determine report output dir
    if args.report:
        report_dir = Path(args.report)
    else:
        report_dir = Path("reports") / "perf" / model_handle
    report_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    json_path = report_dir / f"perf_{run_id}.json"
    html_path = report_dir / f"perf_{run_id}.html"

    total_work = len(cases) * args.iterations
    print(
        f"Running {len(cases)} cases × {args.iterations} iteration(s) "
        f"= {total_work} requests with {args.concurrency} thread(s)...",
        flush=True,
    )

    completed = [0]

    def _on_done(result) -> None:
        completed[0] += 1
        if completed[0] % 50 == 0 or completed[0] == total_work:
            print(f"  {completed[0]}/{total_work} requests done...", flush=True)

    # Step 5: Run
    raw_results, stats = run_perf_tests(
        client=client,
        cases=cases,
        concurrency=args.concurrency,
        iterations=args.iterations,
        ramp_up_seconds=args.ramp_up,
        perf_threshold_ms=args.perf_threshold_ms,
        on_request_done=_on_done,
    )

    # Step 6: Report
    write_perf_json_report(stats, raw_results, json_path)
    write_perf_html_report(
        stats, raw_results, html_path,
        base_url=base_url,
        model_handle=model_handle,
        model_version=model_version,
    )

    # Step 7: Summary
    print("", flush=True)
    print(f"--- Performance Results: {model_handle} ---", flush=True)
    print(f"  Total requests : {stats.total_requests}", flush=True)
    print(f"  Wall time      : {stats.wall_time_s:.1f}s", flush=True)
    print(f"  Throughput     : {stats.throughput_rps:.1f} req/s", flush=True)
    print(f"  Errors         : {stats.error_count} ({stats.error_rate_pct:.1f}%)", flush=True)
    print(f"  Slow (>{args.perf_threshold_ms}ms): {stats.slow_count}", flush=True)
    print(f"  Latency        : avg={stats.avg_ms} p50={stats.p50_ms} p90={stats.p90_ms} "
          f"p95={stats.p95_ms} p99={stats.p99_ms} max={stats.max_ms} (ms)", flush=True)
    print(f"  Reports        : {html_path}, {json_path}", flush=True)

    if args.fail_on_error_rate is not None and stats.error_rate_pct > args.fail_on_error_rate:
        print(
            f"\nFAIL: error rate {stats.error_rate_pct:.1f}% exceeds threshold "
            f"{args.fail_on_error_rate:.1f}%",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nDone.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
