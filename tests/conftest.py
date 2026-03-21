"""
Session-scoped pytest fixtures: loaded OpenAPI spec, HTTP client, discovery dict, generated cases.
"""
import pytest

from sts_test_framework.config import bundled_spec_path, sts_base_url


def pytest_report_header(config):
    """Add STS environment (base URL) to the pytest run header."""
    return f"STS environment: {sts_base_url()}"


@pytest.fixture(scope="session")
def spec_path():
    """Path object to OpenAPI spec file."""
    return bundled_spec_path()


@pytest.fixture(scope="session")
def spec(spec_path):
    """Parsed OpenAPI document (skipped if spec file missing)."""
    from sts_test_framework.loader import load_spec
    if not spec_path.exists():
        pytest.skip(f"Spec not found: {spec_path}")
    return load_spec(spec_path)


@pytest.fixture(scope="session")
def base_url():
    """STS API root including ``/v2`` (overridable via ``STS_BASE_URL``)."""
    return sts_base_url()


@pytest.fixture(scope="session")
def api_client(base_url):
    """Shared ``APIClient`` for discovery and tests."""
    from sts_test_framework.client import APIClient
    return APIClient(base_url)


@pytest.fixture(scope="session")
def test_data(api_client):
    """Discovery output used to parametrize positive paths."""
    from sts_test_framework.discover import discover
    return discover(api_client)


@pytest.fixture(scope="session")
def generated_cases(spec, test_data):
    """Full case list (positive + negatives) from ``generate_cases``."""
    from sts_test_framework.generator import generate_cases
    return generate_cases(spec, test_data, include_negative=True)
