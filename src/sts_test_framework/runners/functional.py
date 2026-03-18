"""
Functional runner: for each generated case, GET the path and compare status to ``expected_status``.

Successful 200 responses may be checked for coarse JSON shape (object vs list vs int).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable
from urllib.parse import quote

if TYPE_CHECKING:
    from ..client import APIClient

from ..client import APIResponse


def _path_with_query(path: str, params: dict | None) -> str:
    """Append URL-encoded query string to path for human-readable report columns."""
    if not params:
        return path
    query_parts = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, list):
            for item in v:
                query_parts.append(f"{k}={quote(str(item), safe='')}")
        else:
            query_parts.append(f"{k}={quote(str(v), safe='')}")
    if not query_parts:
        return path
    return path + "?" + "&".join(query_parts)


def run_functional_tests(
    client: "APIClient",
    cases: list[dict],
    on_case_done: Callable[[dict], None] | None = None,
) -> list[dict]:
    """
    Execute every case in order via ``client.get``.

    Args:
        client: Base URL + SSL settings.
        cases: Generated dicts with ``path``, ``params``, ``expected_status``, etc.
        on_case_done: Optional callback after each case (CLI uses this for live log lines).

    Returns:
        List of result dicts (operation_id, path_display, passed, duration, error, ...).
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
            # Property /terms and /terms/count: 404 with "Property exists, but does not use an acceptable value set." is expected when the property has no value set.
            if expected_status == 200 and response.status_code == 404:
                path_no_query = path.split("?")[0].rstrip("/")
                if path_no_query.endswith("/terms") or path_no_query.endswith("/terms/count"):
                    data = response.json()
                    if isinstance(data, dict) and data.get("detail") == "Property exists, but does not use an acceptable value set.":
                        passed = True
                        error = f"Special expected 404: {response.body}" if response.body else "Acceptable 404 but response body was empty without detail message — unexpected; please investigate."

        # Optional: basic shape check for 200
        if passed and expected_status == 200 and response.json() is not None:
            shape_ok, shape_error = _check_basic_shape(response, case)
            if not shape_ok:
                passed = False
                error = shape_error

        path_display = _path_with_query(path, params)
        result = {
            "operation_id": operation_id,
            "summary": summary,
            "path": path,
            "path_display": path_display,
            "params": params,
            "expected_status": expected_status,
            "actual_status": response.status_code,
            "passed": passed,
            "duration": response.duration,
            "error": error,
            "tag": case.get("tag"),
            "negative": case.get("negative", False),
        }
        results.append(result)
        if on_case_done:
            on_case_done(result)
    return results


def _check_basic_shape(response: APIResponse, case: dict) -> tuple[bool, str | None]:
    """
    After status matches, optionally validate JSON kind vs ``response_schema_ref``.

    Entity-like refs expect a dict with identifiers; lists and integers pass loosely
    (counts return int). Returns ``(True, None)`` if no ref or check skipped.
    """
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
