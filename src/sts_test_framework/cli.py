"""
CLI entry: run test suite with --spec, --base-url, --report, --tags.
"""
import os
import sys
from pathlib import Path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="STS v2 API Test Framework")
    parser.add_argument("--spec", default=None, help="Path to OpenAPI spec (v2.yaml)")
    parser.add_argument("--base-url", default=None, help="STS base URL (default: STS_BASE_URL or https://sts.cancer.gov/v2)")
    parser.add_argument("--report", default=None, help="Report output directory (default: REPORT_DIR or reports/)")
    parser.add_argument("--tags", default=None, help="Comma-separated tags to run (default: all)")
    parser.add_argument("--no-negative", action="store_true", help="Skip negative test cases")
    args = parser.parse_args()

    base_url = args.base_url or os.getenv("STS_BASE_URL", "https://sts.cancer.gov/v2")
    report_dir = args.report or os.getenv("REPORT_DIR", "reports")
    spec_path = args.spec
    if not spec_path:
        spec_path = Path(__file__).resolve().parent.parent.parent / "spec" / "v2.yaml"
    spec_path = Path(spec_path)
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None

    from .loader import load_spec
    from .client import APIClient
    from .discover import discover
    from .generator import generate_cases
    from .runners.functional import run_functional_tests
    from .reporters.report import aggregate_results, write_json_report
    from .reporters.html_report import write_html_report

    spec = load_spec(spec_path)
    client = APIClient(base_url)
    test_data = discover(client)
    cases = generate_cases(spec, test_data, include_negative=not args.no_negative, tag_filter=tag_filter)

    if not cases:
        print("No test cases generated (check discovery and tag filter)")
        sys.exit(0)

    print(f"Running {len(cases)} test cases...")
    results = run_functional_tests(client, cases)
    summary = aggregate_results(results)

    Path(report_dir).mkdir(parents=True, exist_ok=True)
    write_json_report(summary, results, Path(report_dir) / "report.json")
    write_html_report(summary, results, Path(report_dir) / "report.html")
    print(f"Report written to {report_dir}/")

    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    print(f"Result: {passed}/{total} passed")
    if summary.get("failed", 0) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
