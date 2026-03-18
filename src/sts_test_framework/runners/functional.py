"""
Functional test runner: execute generated cases, assert status and basic shape, record results.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import APIClient

from ..client import APIResponse


def run_functional_tests(
    client: "APIClient",
    cases: list[dict],
) -> list[dict]:
    """
    Run functional tests for each case. Each case has path, params, expected_status, operation_id, etc.
    Returns list of result dicts: { operation_id, path, expected_status, actual_status, passed, duration, error? }
    """
    results = []
    for case in cases:
        path = case.get("path") or ""
        params = case.get("params")
        expected_status = case.get("expected_status", 200)
        operation_id = case.get("operation_id", "")
        summary = case.get("summary", "")

        response: APIResponse = client.get(path, params)

        passed = response.status_code == expected_status
        error = None
        if not passed:
            error = f"Expected {expected_status}, got {response.status_code}"
            if response.body:
                error += f": {response.body[:200]}"

        # Optional: basic shape check for 200
        if passed and expected_status == 200 and response.json() is not None:
            shape_ok, shape_error = _check_basic_shape(response, case)
            if not shape_ok:
                passed = False
                error = shape_error

        results.append({
            "operation_id": operation_id,
            "summary": summary,
            "path": path,
            "params": params,
            "expected_status": expected_status,
            "actual_status": response.status_code,
            "passed": passed,
            "duration": response.duration,
            "error": error,
            "tag": case.get("tag"),
            "negative": case.get("negative", False),
        })
    return results


def _check_basic_shape(response: APIResponse, case: dict) -> tuple[bool, str | None]:
    """Basic response shape: array or object, and required top-level keys if schema ref known."""
    data = response.json()
    if data is None:
        return True, None  # No shape check if not JSON
    schema_ref = case.get("response_schema_ref")
    if not schema_ref:
        return True, None

    if schema_ref in ("Entity", "Term", "Model", "Node", "PropertyResponse", "Tag"):
        if not isinstance(data, dict):
            return False, f"Expected object for {schema_ref}, got {type(data).__name__}"
        if "nanoid" in ("Entity", "Term", "Node", "PropertyResponse", "Tag") and schema_ref != "Model":
            if "nanoid" not in data and "value" not in data and "key" not in data:
                return False, f"Expected nanoid/value/key in {schema_ref}"
        return True, None

    if isinstance(data, list):
        return True, None
    if isinstance(data, dict):
        return True, None
    if isinstance(data, int):
        return True, None  # count endpoints
    return True, None
