"""
OpenAPI-driven test case generation for STS v2.
Builds positive (200) and negative (404/422) test cases from spec and discovery data.
"""
from urllib.parse import quote

from .loader import get_paths, load_spec, normalize_path_for_base


def _path_params_from_spec(operation: dict) -> list[dict]:
    """Extract path parameters from operation."""
    params = operation.get("parameters") or []
    return [p for p in params if isinstance(p, dict) and p.get("in") == "path"]


def _query_params_from_spec(operation: dict) -> list[dict]:
    """Extract query parameters from operation."""
    params = operation.get("parameters") or []
    return [p for p in params if isinstance(p, dict) and p.get("in") == "query"]


def _response_codes(operation: dict) -> set[int]:
    """Return set of documented response status codes."""
    responses = operation.get("responses") or {}
    return {int(k) for k in responses if str(k).isdigit()}


def _fill_path_template(template: str, path_param_values: dict[str, str], base_path: str = "/v2") -> str:
    """Replace {param} in template with values. Template may be /v2/...; return path relative to base."""
    path = template
    for key, value in path_param_values.items():
        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    return normalize_path_for_base(path, base_path)


def _get_schema_ref(operation: dict) -> str | None:
    """Get response schema $ref for 200 if present (first from anyOf/oneOf)."""
    responses = operation.get("responses") or {}
    r200 = responses.get("200") or responses.get(200)
    if not r200 or not isinstance(r200, dict):
        return None
    content = r200.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema")
    if not schema or not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if ref:
        return ref.split("/")[-1]
    any_of = schema.get("anyOf") or schema.get("oneOf")
    if any_of and isinstance(any_of, list) and len(any_of) > 0:
        first = any_of[0]
        if isinstance(first, dict) and first.get("$ref"):
            return first["$ref"].split("/")[-1]
    return None


def generate_cases(
    spec: dict,
    test_data: dict,
    base_path: str = "/v2",
    tag_filter: list[str] | None = None,
    include_negative: bool = True,
) -> list[dict]:
    """
    Generate test cases from spec and discovery data.
    Each case: {
        "path": str (path relative to base_url),
        "params": dict | None (query params),
        "expected_status": int,
        "operation_id": str,
        "summary": str,
        "tag": str | None,
        "negative": bool,
        "response_schema_ref": str | None,
    }
    """
    paths = get_paths(spec)
    cases = []

    for path_template, method, op in _iter_ops(spec, tag_filter):
        if method != "get":
            continue

        path_params = _path_params_from_spec(op)
        query_params = _query_params_from_spec(op)
        response_codes = _response_codes(op)
        operation_id = op.get("operationId") or f"{method}_{path_template}"
        summary = op.get("summary") or ""
        tags = op.get("tags") or []
        tag = tags[0] if tags else None
        schema_ref = _get_schema_ref(op)

        # Positive case: 200 with discovered or default values
        path_values = _resolve_path_params(path_template, path_params, test_data)
        if path_values is not None:
            path_str = _fill_path_template(path_template, path_values, base_path)
            query_vals = _default_query_params(query_params)
            # Optional: add discovery query params where they matter (e.g. version)
            query_vals = _resolve_query_params(path_template, op, query_params, query_vals, test_data)
            cases.append({
                "path": path_str,
                "params": query_vals if query_vals else None,
                "expected_status": 200,
                "operation_id": operation_id,
                "summary": summary,
                "tag": tag,
                "negative": False,
                "response_schema_ref": schema_ref,
            })

        # Negative cases
        if include_negative and (404 in response_codes or 422 in response_codes):
            expected = 404 if 404 in response_codes else 422
            neg_path_values = _negative_path_params(path_template, path_params, test_data)
            if neg_path_values is not None:
                path_str = _fill_path_template(path_template, neg_path_values, base_path)
                cases.append({
                    "path": path_str,
                    "params": None,
                    "expected_status": expected,
                    "operation_id": operation_id,
                    "summary": f"{summary} (invalid param)",
                    "tag": tag,
                    "negative": True,
                    "response_schema_ref": None,
                })

    return cases


def _iter_ops(spec: dict, tag_filter: list[str] | None):
    """Iterate (path_template, method, operation) from spec."""
    paths = get_paths(spec)
    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            if tag_filter:
                op_tags = op.get("tags") or []
                if not set(op_tags) & set(tag_filter):
                    continue
            yield path_template, method, op


def _resolve_path_params(path_template: str, path_params: list[dict], test_data: dict) -> dict | None:
    """Resolve path parameter values from test_data. Return None if cannot resolve."""
    if not path_params:
        return {}
    values = {}
    for p in path_params:
        name = p.get("name")
        if not name:
            continue
        # Map spec param names to discovery keys
        if name == "id":
            for k in ("prop_nanoid", "node_nanoid", "tag_nanoid", "model_nanoid"):
                if test_data.get(k):
                    values[name] = test_data[k]
                    break
            if name not in values:
                return None
            continue
        if name == "modelHandle":
            if not test_data.get("model_handle"):
                return None
            values[name] = test_data["model_handle"]
            continue
        if name == "versionString":
            if not test_data.get("model_version"):
                return None
            values[name] = test_data["model_version"]
            continue
        if name == "nodeHandle":
            if not test_data.get("node_handle"):
                return None
            values[name] = test_data["node_handle"]
            continue
        if name == "propHandle":
            if not test_data.get("prop_handle"):
                return None
            values[name] = test_data["prop_handle"]
            continue
        if name == "termValue":
            if not test_data.get("term_value"):
                return None
            values[name] = test_data["term_value"]
            continue
        if name == "key":
            if not test_data.get("tag_key"):
                return None
            values[name] = test_data["tag_key"]
            continue
        if name == "value":
            if "tag_value" not in test_data:
                return None
            values[name] = test_data["tag_value"]
            continue
        if name == "model":
            if not test_data.get("model_handle"):
                return None
            values[name] = test_data["model_handle"]
            continue
        if name == "property":
            if not test_data.get("prop_handle"):
                return None
            values[name] = test_data["prop_handle"]
            continue
        if name == "version":
            # Used in terms/cde-pvs; may not be in discovery
            if test_data.get("model_version"):
                values[name] = test_data["model_version"]
            else:
                values[name] = "1.0"
            continue
    return values if len(values) == len(path_params) else None


def _negative_path_params(path_template: str, path_params: list[dict], test_data: dict) -> dict | None:
    """Return path param values that should yield 404/422 (e.g. invalid id)."""
    if not path_params:
        return {}
    # Use a single invalid value for path params that look like ids/handles
    invalid = "invalid_nonexistent_xyz"
    values = {}
    for p in path_params:
        name = p.get("name")
        if not name:
            continue
        if name in ("id", "modelHandle", "versionString", "nodeHandle", "propHandle", "termValue", "key", "value", "model", "property", "version"):
            values[name] = invalid
        else:
            if name == "id" and test_data.get("model_nanoid"):
                values[name] = invalid
            else:
                values[name] = invalid
    return values


def _default_query_params(query_params: list[dict]) -> dict:
    """Default values for query params (e.g. skip=0, limit=10)."""
    out = {}
    for p in query_params:
        name = p.get("name")
        schema = p.get("schema") or {}
        default = schema.get("default")
        if default is not None:
            out[name] = default
        else:
            if schema.get("type") == "integer":
                out[name] = 0 if "skip" in (name or "").lower() else 10
            elif schema.get("type") == "boolean":
                out[name] = schema.get("default", False)
    return out


def _resolve_query_params(path_template: str, op: dict, query_params: list[dict], current: dict, test_data: dict) -> dict:
    """Add discovery-based query params (e.g. version for model-pvs)."""
    if "/terms/model-pvs/" in path_template and "version" in [p.get("name") for p in query_params]:
        if test_data.get("model_version"):
            current["version"] = test_data["model_version"]
    return current
