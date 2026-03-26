"""
Functional runner: for each generated case, GET the path and compare status to ``expected_status``.

Successful 200 responses may be checked for coarse JSON shape (object vs list vs int).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..client import APIClient

from ..client import APIResponse, _build_query_string

_TERMS_NO_VALUE_SET_DETAIL = "Property exists, but does not use an acceptable value set."


def _is_acceptable_terms_no_value_set_404(path: str, response: APIResponse) -> bool:
    """
    True when ``path`` is a property ``/terms`` or ``/terms/count`` endpoint and the API
    returns 404 with the standard \"no acceptable value set\" detail (same as single GET).
    """
    path_no_query = path.split("?")[0].rstrip("/")
    if not (path_no_query.endswith("/terms") or path_no_query.endswith("/terms/count")):
        return False
    if response.status_code != 404:
        return False
    data = response.json()
    return isinstance(data, dict) and data.get("detail") == _TERMS_NO_VALUE_SET_DETAIL


def _special_expected_terms_404_error(response: APIResponse) -> str:
    """Human-readable error string for an acceptable terms 404 (matches single-request case)."""
    if response.body:
        return f"Special expected 404: {response.body}"
    return (
        "Acceptable 404 but response body was empty without detail message — "
        "unexpected; please investigate."
    )


@dataclass(frozen=True)
class PaginationPairOutcome:
    """Result of ``_pagination_pair_check`` (two-request pagination slice)."""

    ok: bool
    error: str | None
    duration_total: float
    actual_status: int
    b_executed: bool
    duration_a: float
    duration_b: float


def _pagination_pair_check(client: "APIClient", case: dict) -> PaginationPairOutcome:
    """
    Two GETs: A with ``pagination_pair_params_a``, B with ``pagination_pair_params_b``.

    If A is a JSON list with ``len >= 2``, require B to be 200 with a list where
    ``B[0] == A[1]``. Otherwise pass (skip compare).

    ``b_executed`` is True when the second GET was performed. ``duration_a`` / ``duration_b``
    are per-request durations (``duration_b`` is 0 when B was not called).
    """
    path = case.get("path") or ""
    params_a = case.get("pagination_pair_params_a")
    params_b = case.get("pagination_pair_params_b")
    if params_a is None or params_b is None:
        return PaginationPairOutcome(
            ok=False,
            error="pagination_pair: missing pagination_pair_params_a or _b",
            duration_total=0.0,
            actual_status=0,
            b_executed=False,
            duration_a=0.0,
            duration_b=0.0,
        )

    resp_a = client.get(path, params_a)
    dur_a = resp_a.duration
    if resp_a.status_code != 200:
        if _is_acceptable_terms_no_value_set_404(path, resp_a):
            return PaginationPairOutcome(
                ok=True,
                error=_special_expected_terms_404_error(resp_a),
                duration_total=dur_a,
                actual_status=resp_a.status_code,
                b_executed=False,
                duration_a=dur_a,
                duration_b=0.0,
            )
        return PaginationPairOutcome(
            ok=False,
            error=(
                f"pagination_pair A: expected 200, got {resp_a.status_code}"
                + (f": {resp_a.body[:200]}" if resp_a.body else "")
            ),
            duration_total=dur_a,
            actual_status=resp_a.status_code,
            b_executed=False,
            duration_a=dur_a,
            duration_b=0.0,
        )

    data_a = resp_a.json()
    if not isinstance(data_a, list) or len(data_a) < 2:
        return PaginationPairOutcome(
            ok=True,
            error=None,
            duration_total=dur_a,
            actual_status=resp_a.status_code,
            b_executed=False,
            duration_a=dur_a,
            duration_b=0.0,
        )

    resp_b = client.get(path, params_b)
    dur_b = resp_b.duration
    dur_total = dur_a + dur_b
    if resp_b.status_code != 200:
        if _is_acceptable_terms_no_value_set_404(path, resp_b):
            return PaginationPairOutcome(
                ok=True,
                error=_special_expected_terms_404_error(resp_b),
                duration_total=dur_total,
                actual_status=resp_b.status_code,
                b_executed=True,
                duration_a=dur_a,
                duration_b=dur_b,
            )
        return PaginationPairOutcome(
            ok=False,
            error=(
                f"pagination_pair B: expected 200, got {resp_b.status_code}"
                + (f": {resp_b.body[:200]}" if resp_b.body else "")
            ),
            duration_total=dur_total,
            actual_status=resp_b.status_code,
            b_executed=True,
            duration_a=dur_a,
            duration_b=dur_b,
        )

    data_b = resp_b.json()
    if not isinstance(data_b, list) or len(data_b) < 1:
        return PaginationPairOutcome(
            ok=False,
            error=f"pagination_pair B: expected non-empty JSON list, got {data_b!r}",
            duration_total=dur_total,
            actual_status=resp_b.status_code,
            b_executed=True,
            duration_a=dur_a,
            duration_b=dur_b,
        )
    if data_b[0] != data_a[1]:
        return PaginationPairOutcome(
            ok=False,
            error=f"pagination_pair: B[0] != A[1]: {data_b[0]!r} vs {data_a[1]!r}",
            duration_total=dur_total,
            actual_status=resp_b.status_code,
            b_executed=True,
            duration_a=dur_a,
            duration_b=dur_b,
        )
    return PaginationPairOutcome(
        ok=True,
        error=None,
        duration_total=dur_total,
        actual_status=resp_b.status_code,
        b_executed=True,
        duration_a=dur_a,
        duration_b=dur_b,
    )


def _path_with_query(path: str, params: dict | None) -> str:
    """Append URL-encoded query string to path for human-readable report columns."""
    return path + _build_query_string(params)


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

        if case.get("pagination_pair_assert"):
            pair_out = _pagination_pair_check(client, case)
            params_a = case.get("pagination_pair_params_a")
            params_b = case.get("pagination_pair_params_b")
            path_a = _path_with_query(path, params_a) if params_a is not None else _path_with_query(path, params)
            path_b = _path_with_query(path, params_b) if params_b is not None else path_a
            # Display row focuses on request B when it ran; otherwise B URL + note (skip) or A URL (A failed first).
            display_note = None
            if pair_out.b_executed:
                path_display = path_b
                display_duration = pair_out.duration_b
            elif pair_out.ok:
                err = pair_out.error or ""
                if err.startswith("Special expected 404"):
                    path_display = path_a
                    display_duration = pair_out.duration_a
                    display_note = None
                else:
                    path_display = path_b
                    display_duration = pair_out.duration_a
                    display_note = "B not run (A had <2 items)"
            else:
                path_display = path_a
                display_duration = pair_out.duration_a
            result = {
                "operation_id": operation_id,
                "summary": summary,
                "path": path,
                "path_display": path_display,
                "pagination_pair_display_note": display_note,
                "pagination_pair_b_executed": pair_out.b_executed,
                "pagination_pair_wall_time": pair_out.duration_total,
                "duration_pair_a": pair_out.duration_a,
                "duration_pair_b": pair_out.duration_b,
                "params": params,
                "expected_status": expected_status,
                "actual_status": pair_out.actual_status,
                "passed": pair_out.ok,
                "duration": display_duration,
                "error": pair_out.error,
                "tag": case.get("tag"),
                "negative": case.get("negative", False),
            }
            results.append(result)
            if on_case_done:
                on_case_done(result)
            continue

        response: APIResponse = client.get(path, params)

        passed = response.status_code == expected_status
        error = None
        if not passed:
            error = f"Expected {expected_status}, got {response.status_code}"
            if response.body:
                error += f": {response.body[:200]}"
            # Property /terms and /terms/count: 404 with "Property exists, but does not use an acceptable value set." is expected when the property has no value set.
            if expected_status == 200 and response.status_code == 404:
                if _is_acceptable_terms_no_value_set_404(path, response):
                    passed = True
                    error = _special_expected_terms_404_error(response)

        # Optional: exact JSON, skip_oob_assert (model-pvs), pagination limit, or shape check for 200
        if passed and (
            expected_status == 200
            or case.get("expected_json") is not None
            or case.get("skip_oob_assert")
            or case.get("pagination_assert_max_items") is not None
        ):
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

    If ``case`` includes ``expected_json``, the body must match exactly (used for
    ``__skip_oob`` on 404, cde-pvs ``[]``, etc.); entity/list checks are skipped.

    If ``skip_oob_assert`` is ``model_pvs_empty_permissible_values``, the body must be a
    **non-empty** JSON array of objects each with ``permissibleValues == []``.

    If ``pagination_assert_max_items`` is set and the body is a JSON ``list``, its length
    must not exceed that value (enforces ``limit`` for ``__pagination_positive`` cases).

    Entity-like refs expect a dict with identifiers; lists and integers pass loosely
    (counts return int). Returns ``(True, None)`` if no ref or check skipped.
    """
    data = response.json()
    if case.get("expected_json") is not None:
        exp = case["expected_json"]
        if data is None:
            return False, f"Expected JSON {exp!r}, but response was not JSON or empty"
        if data != exp:
            return False, f"Expected JSON {exp!r}, got {data!r}"
        return True, None
    if case.get("skip_oob_assert") == "model_pvs_empty_permissible_values":
        if data is None:
            return False, "Expected JSON list for model-pvs skip_oob, but response was not JSON"
        if not isinstance(data, list):
            return False, f"Expected JSON array for model-pvs skip_oob, got {type(data).__name__}"
        if len(data) == 0:
            return (
                False,
                "Top-level JSON array is empty; expected at least one item with "
                "permissibleValues []. An empty response is unexpected for this scenario — "
                "please investigate.",
            )
        for i, item in enumerate(data):
            if not isinstance(item, dict) or item.get("permissibleValues") != []:
                return (
                    False,
                    f"Expected each item to have permissibleValues [], got {item!r} at index {i}",
                )
        return True, None
    max_items = case.get("pagination_assert_max_items")
    if max_items is not None and isinstance(data, list):
        if len(data) > max_items:
            return (
                False,
                f"Pagination: response list length {len(data)} exceeds limit "
                f"(expected at most {max_items})",
            )
    if data is None:
        return True, None  # No shape check if not JSON
    schema_ref = case.get("response_schema_ref")
    if not schema_ref:
        return True, None

    if schema_ref in ("Entity", "Term", "Model", "Node", "PropertyResponse", "Tag"):
        if not isinstance(data, dict):
            return False, f"Expected object for {schema_ref}, got {type(data).__name__}"
        if schema_ref in ("Entity", "Term", "Node", "PropertyResponse", "Tag") and schema_ref != "Model":
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


def check_response_body_for_case(response: APIResponse, case: dict) -> tuple[bool, str | None]:
    """
    Validate response body against ``case`` (``expected_json`` and/or schema shape for 200).

    Mirrors the CLI runner’s post-status checks; use from pytest so tests stay aligned.
    """
    return _check_basic_shape(response, case)


def check_pagination_pair_for_case(client: "APIClient", case: dict) -> tuple[bool, str | None]:
    """
    Run the two-request pagination pair check (same logic as the CLI functional runner).

    Use from pytest when ``case`` has ``pagination_pair_assert``; do not call after a
    single ``get`` for that case.
    """
    out = _pagination_pair_check(client, case)
    return out.ok, out.error
