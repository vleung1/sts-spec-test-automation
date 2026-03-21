"""
STS environment defaults and bundled OpenAPI spec path (project root).

Single source of truth for ``STS_BASE_URL`` when unset, aligned with CLI and tests.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_STS_BASE_URL = "https://sts-qa.cancer.gov/v2"


def sts_base_url() -> str:
    """STS API root including ``/v2`` (``STS_BASE_URL`` or :data:`DEFAULT_STS_BASE_URL`)."""
    return os.getenv("STS_BASE_URL", DEFAULT_STS_BASE_URL)


def bundled_spec_path() -> Path:
    """Path to ``spec/v2.yaml`` at the project root (sibling of ``src/``)."""
    root = Path(__file__).resolve().parent.parent.parent
    return root / "spec" / "v2.yaml"
