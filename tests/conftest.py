"""
Pytest fixtures: spec (loaded v2), api_client, test_data (discovery), generated_cases.
"""
import os
import pytest
from pathlib import Path


# Resolve spec path relative to project root
def _spec_path():
    root = Path(__file__).resolve().parent.parent
    return root / "spec" / "v2.yaml"


@pytest.fixture(scope="session")
def spec_path():
    return _spec_path()


@pytest.fixture(scope="session")
def spec(spec_path):
    from sts_test_framework.loader import load_spec
    if not spec_path.exists():
        pytest.skip(f"Spec not found: {spec_path}")
    return load_spec(spec_path)


@pytest.fixture(scope="session")
def base_url():
    return os.getenv("STS_BASE_URL", "https://sts.cancer.gov/v2")


@pytest.fixture(scope="session")
def api_client(base_url):
    from sts_test_framework.client import APIClient
    return APIClient(base_url)


@pytest.fixture(scope="session")
def test_data(api_client):
    from sts_test_framework.discover import discover
    return discover(api_client)


@pytest.fixture(scope="session")
def generated_cases(spec, test_data):
    from sts_test_framework.generator import generate_cases
    return generate_cases(spec, test_data, include_negative=True)
