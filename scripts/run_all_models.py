#!/usr/bin/env python3
"""
Run STS test framework CLI once per data model.

Usage (from project root):
    STS_BASE_URL=https://sts-qa.cancer.gov/v2 python scripts/run_all_models.py
    python scripts/run_all_models.py

Reports are written to reports/<model>/report_<timestamp>.html (and .json).
Exits with 1 if any model run fails.
"""
import os
import subprocess
import sys
from pathlib import Path

# Default list of data models to test
DEFAULT_MODELS = [
    "CDS",
    "CCDI",
    "CCDI-DCC",
    "ICDC",
    "CTDC",
    "C3DC",
    "PSDC",
    "mCODE",
    "PDC",
    "CRDC",
    "CRDCSearch",
    "CRDCSubmission"
]

# Base URL for STS API (override with STS_BASE_URL env)
DEFAULT_BASE_URL = "https://sts-qa.cancer.gov/v2"

# Base directory for reports; each model gets a subdir reports/<model>/
REPORT_BASE = "reports"


def main() -> None:
    models = os.getenv("STS_MODELS")
    if models:
        model_list = [m.strip() for m in models.split(",") if m.strip()]
    else:
        model_list = DEFAULT_MODELS

    base_url = os.getenv("STS_BASE_URL", DEFAULT_BASE_URL)
    project_root = Path(__file__).resolve().parent.parent

    failed = []
    for model in model_list:
        report_dir = str(Path(REPORT_BASE) / model)
        print(f"Running for model {model}...", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sts_test_framework.cli",
                "--base-url",
                base_url,
                "--report",
                report_dir,
                "--model",
                model,
                "--release",
            ],
            cwd=project_root,
            env=os.environ,
        )
        if result.returncode != 0:
            failed.append(model)

    if failed:
        print(f"Failed models: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    print("All models completed successfully.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
