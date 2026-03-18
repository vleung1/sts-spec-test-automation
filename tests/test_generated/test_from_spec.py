"""
Dynamic tests from OpenAPI spec: one test per generated case.
"""
import os
import pytest
from pathlib import Path


def _get_generated_cases():
    """Load spec, discover, generate cases (used at collection time)."""
    from sts_test_framework.loader import load_spec
    from sts_test_framework.discover import discover
    from sts_test_framework.generator import generate_cases
    from sts_test_framework.client import APIClient
    spec_path = Path(__file__).resolve().parent.parent / "spec" / "v2.yaml"
    if not spec_path.exists():
        return []
    spec = load_spec(spec_path)
    base_url = os.getenv("STS_BASE_URL", "https://sts.cancer.gov/v2")
    client = APIClient(base_url)
    test_data = discover(client)
    return generate_cases(spec, test_data, include_negative=True)


def pytest_generate_tests(metafunc):
    """Parametrize test_generated_case by generated cases."""
    if "case" in metafunc.fixturenames:
        cases = _get_generated_cases()
        ids = [c.get("operation_id") or str(i) for i, c in enumerate(cases)]
        metafunc.parametrize("case", cases, ids=ids)


def test_generated_case(api_client, case):
    """One assertion per generated case (status and basic shape for 200)."""
    path = case.get("path", "")
    params = case.get("params")
    expected = case.get("expected_status", 200)
    response = api_client.get(path, params)
    assert response.status_code == expected, (
        f"Expected {expected}, got {response.status_code}: {response.body[:200] if response.body else ''}"
    )
    if expected == 200 and response.json() is not None:
        data = response.json()
        assert isinstance(data, (list, dict, int)), f"Unexpected type {type(data)}"
