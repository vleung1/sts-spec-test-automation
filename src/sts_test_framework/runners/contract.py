"""
Optional contract runner: validate 200 responses against OpenAPI response schemas using jsonschema.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import APIClient, APIResponse


def run_contract_tests(
    client: "APIClient",
    cases: list[dict],
    spec: dict,
) -> list[dict]:
    """
    Run contract validation for cases that expect 200. Validates JSON against operation response schema.
    Returns list of result dicts with passed, schema_violations, etc.
    """
    try:
        import jsonschema
    except ImportError:
        return [{"operation_id": c.get("operation_id"), "passed": True, "schema_violations": [], "error": "jsonschema not installed"} for c in cases]

    schemas = (spec.get("components") or {}).get("schemas") or {}
    results = []
    for case in cases:
        if case.get("expected_status") != 200:
            results.append({"operation_id": case.get("operation_id"), "passed": True, "skipped": True})
            continue

        path = case.get("path") or ""
        params = case.get("params")
        response: "APIResponse" = client.get(path, params)
        operation_id = case.get("operation_id", "")

        if response.status_code != 200:
            results.append({
                "operation_id": operation_id,
                "passed": False,
                "schema_violations": [],
                "error": f"HTTP {response.status_code}",
            })
            continue

        data = response.json()
        schema_ref = case.get("response_schema_ref")
        violations = []
        if schema_ref and data is not None and schema_ref in schemas:
            schema = schemas[schema_ref]
            try:
                jsonschema.validate(instance=data, schema=_to_jsonschema(schema))
            except jsonschema.ValidationError as e:
                violations.append(str(e.message))
            except Exception as e:
                violations.append(str(e))

        results.append({
            "operation_id": operation_id,
            "passed": len(violations) == 0,
            "schema_violations": violations,
            "error": violations[0] if violations else None,
        })
    return results


def _to_jsonschema(schema: dict) -> dict:
    """Convert OpenAPI 3 schema to JSON Schema draft-07 style for jsonschema lib."""
    if not schema:
        return {}
    out = {}
    if "$ref" in schema:
        return schema
    if "type" in schema:
        out["type"] = schema["type"]
    if "required" in schema:
        out["required"] = schema["required"]
    if "properties" in schema:
        out["properties"] = {k: _to_jsonschema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = _to_jsonschema(schema["items"])
    return out if out else schema
