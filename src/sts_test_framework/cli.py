"""
Command-line entry: load spec, discover live data, generate cases, run GET tests, write reports.

Pipeline: ``load_spec`` → ``discover`` → ``generate_cases`` → ``run_functional_tests``
→ JSON + HTML reports. Exit code 1 if any case fails.
"""
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def main() -> None:
    """
    Parse argv, run the full STS v2 functional suite, print pass/fail summary.

    Environment: ``STS_BASE_URL``, ``REPORT_DIR``, ``STS_SSL_VERIFY`` (via client).
    """
    import argparse

    from .config import DEFAULT_STS_BASE_URL, bundled_spec_path, sts_base_url

    parser = argparse.ArgumentParser(description="STS v2 API Test Framework")
    parser.add_argument("--spec", default=None, help="Path to OpenAPI spec (v2.json)")
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"STS base URL (default: STS_BASE_URL or {DEFAULT_STS_BASE_URL})",
    )
    parser.add_argument("--report", default=None, help="Report output directory (default: REPORT_DIR or reports/)")
    parser.add_argument("--tags", default=None, help="Comma-separated tags to run (default: all)")
    parser.add_argument("--no-negative", action="store_true", help="Skip negative test cases")
    parser.add_argument("--quiet", action="store_true", help="Minimal output: only run count, report paths, and result")
    parser.add_argument("--model", default=None, help="Model handle to test (e.g. C3DC). If omitted, first model from /models/ is used.")
    parser.add_argument("--release", action="store_true", help="Use latest release version (no hyphen) for the model; otherwise first version.")
    args = parser.parse_args()

    base_url = args.base_url or sts_base_url()
    report_dir = args.report or os.getenv("REPORT_DIR", "reports")
    spec_path = args.spec
    if not spec_path:
        spec_path = bundled_spec_path()
    spec_path = Path(spec_path)
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None
    quiet = args.quiet

    def log(msg: str) -> None:
        """Print progress line unless ``--quiet`` (then only critical lines go to stdout)."""
        if not quiet:
            print(msg, flush=True)

    from .loader import load_spec, get_paths
    from .client import APIClient
    from .discover import discover
    from .generator import generate_cases
    from .runners.functional import run_functional_tests
    from .reporters.report import aggregate_results, write_json_report
    from .reporters.html_report import write_html_report

    # Step 1: Load spec
    log(f"Loading spec from {spec_path}...")
    spec = load_spec(spec_path)
    paths = get_paths(spec)
    log(f"Spec loaded: {len(paths)} paths.")

    # Step 2: Create client
    log(f"Client created: base_url={base_url}")
    client = APIClient(base_url)

    # Step 3: Discovery
    log("Running discovery...")
    test_data = discover(
        client,
        model_handle=args.model.strip() if args.model else None,
        use_release_version=args.release,
    )
    discovery_info = None
    if test_data:
        # Summary of what was found (keys only; optional 1–2 example values)
        parts = []
        discovery_info = {}
        for key in ("model_handle", "model_version", "node_handle", "prop_handle", "term_value", "tag_key", "tag_value"):
            if key in test_data:
                v = test_data[key]
                if isinstance(v, str) and len(v) > 20:
                    v = v[:17] + "..."
                parts.append(f"{key}={v!r}")
                discovery_info[key] = v
        log(f"Discovery: {', '.join(parts)}")
    else:
        log("Discovery: no data (API may be unreachable or returned no models).")

    # Step 4: Generate cases
    cases = generate_cases(spec, test_data, include_negative=not args.no_negative, tag_filter=tag_filter)
    if not cases:
        print("No test cases generated (check discovery and tag filter)", file=sys.stderr)
        sys.exit(0)

    n_positive = sum(1 for c in cases if not c.get("negative"))
    n_negative = len(cases) - n_positive
    log(f"Generated {len(cases)} cases ({n_positive} positive, {n_negative} negative).")
    if not quiet:
        by_tag = Counter(c.get("tag") or "unknown" for c in cases)
        tag_parts = [f"{tag}={count}" for tag, count in sorted(by_tag.items())]
        log(f"By tag: {', '.join(tag_parts)}.")

    # Step 5: Run
    def on_case_done(result: dict) -> None:
        """Per-case callback: log Pass/Fail with path and duration (non-quiet mode)."""
        status = "Pass" if result.get("passed") else "Fail"
        path = result.get("path_display") or result.get("path", "")
        duration = result.get("duration")
        duration_ms = f"{duration * 1000:.0f} ms" if duration is not None else "?"
        note = result.get("pagination_pair_display_note")
        suffix = f" — {note}" if note else ""

        if result.get("passed"):
            log(f"  [Pass] GET {path} ({duration_ms}){suffix}")
        else:
            err = (result.get("error") or "")[:80]
            log(f"  [Fail] GET {path} ({duration_ms}) - {err}")

    if quiet:
        print(f"Running {len(cases)} test cases...", flush=True)
    else:
        log(f"Running {len(cases)} test cases...")
    results = run_functional_tests(client, cases, on_case_done=on_case_done if not quiet else None)
    summary = aggregate_results(results)

    # Step 6: Report (timestamped)
    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    report_basename = f"report_{run_id}"
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    json_path = Path(report_dir) / f"{report_basename}.json"
    html_path = Path(report_dir) / f"{report_basename}.html"
    write_json_report(summary, results, json_path)
    write_html_report(
        summary,
        results,
        html_path,
        base_url=base_url,
        model_handle=test_data.get("model_handle") if test_data else None,
        model_version=test_data.get("model_version") if test_data else None,
        discovery_info=discovery_info,
        cases_generated={"total": len(cases), "positive": n_positive, "negative": n_negative},
    )
    if quiet:
        print(f"Report written: {json_path}, {html_path}", flush=True)
    else:
        log(f"Report written: {json_path}, {html_path}")

    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    print(f"Result: {passed}/{total} passed", flush=True)
    if summary.get("failed", 0) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
