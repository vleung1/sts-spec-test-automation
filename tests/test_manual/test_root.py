"""
Manual test: GET root (health). Base URL ends with /v2 so path / or empty hits base.
"""
import pytest


def test_root_returns_200(api_client):
    """GET / should return 200."""
    response = api_client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.body[:200]}"
