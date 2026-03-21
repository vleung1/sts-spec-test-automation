"""
Parametrized tests: one pytest case per generated GET (collection-time case generation).
"""
import pytest

from sts_test_framework.config import bundled_spec_path, sts_base_url


def _get_generated_cases():
    """Build case list when pytest collects tests (no fixture dependency at collection)."""
    from sts_test_framework.loader import load_spec
    from sts_test_framework.discover import discover
    from sts_test_framework.generator import generate_cases
    from sts_test_framework.client import APIClient
    spec_path = bundled_spec_path()
    if not spec_path.exists():
        return []
    spec = load_spec(spec_path)
    client = APIClient(sts_base_url())
    test_data = discover(client)
    return generate_cases(spec, test_data, include_negative=True)


def pytest_generate_tests(metafunc):
    """Inject ``case`` parameter and ids from ``operation_id`` for each generated row."""
    if "case" in metafunc.fixturenames:
        cases = _get_generated_cases()
        ids = [c.get("operation_id") or str(i) for i, c in enumerate(cases)]
        metafunc.parametrize("case", cases, ids=ids)


def test_generated_case(api_client, case):
    """Assert HTTP status matches case; run body checks like the CLI (200 shape or expected_json)."""
    from sts_test_framework.runners.functional import (
        check_pagination_pair_for_case,
        check_response_body_for_case,
    )

    if case.get("pagination_pair_assert"):
        ok, err = check_pagination_pair_for_case(api_client, case)
        assert ok, err
        return

    path = case.get("path", "")
    params = case.get("params")
    expected = case.get("expected_status", 200)
    response = api_client.get(path, params)
    assert response.status_code == expected, (
        f"Expected {expected}, got {response.status_code}: {response.body[:200] if response.body else ''}"
    )
    if (
        expected == 200
        or case.get("expected_json") is not None
        or case.get("skip_oob_assert")
        or case.get("pagination_assert_max_items") is not None
    ):
        ok, err = check_response_body_for_case(response, case)
        assert ok, err
