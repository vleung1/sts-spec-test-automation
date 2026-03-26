"""
OpenAPI-driven test case generation for STS v2.

Builds positive (200) and negative (404/422) test cases from spec and discovery data.

Special case — property terms count (invalid path params):
    Most paths ending in ``/count`` return HTTP 200 with body ``0`` when path segments
    refer to missing resources. The endpoint
    ``.../node/{nodeHandle}/property/{propHandle}/terms/count`` is different: the API
    returns **404** for invalid/missing path context instead of 200+0. The generator
    treats any path ending in ``/terms/count`` as that exception; see
    ``_is_terms_property_count_path`` and the invalid-param branch in ``generate_cases``.

Special case — CDE PVs by id+version (invalid path params):
    GET ``.../terms/cde-pvs/{id}/{version}/pvs`` returns **200** with body **[]** for
    invalid id/version instead of 404; see ``_is_cde_pvs_by_id_pvs_path``.

Special case — skip past end (huge ``skip`` query param):
    Default ``__skip_oob`` expects **404** + ``{"detail": "Not found."}``. Exceptions:
    ``GET .../terms/cde-pvs/.../pvs`` expects **200** + ``[]``; ``GET .../terms/model-pvs/...``
    expects **200** + **non-empty** array of objects with empty ``permissibleValues``; see
    ``_is_cde_pvs_by_id_pvs_path``, ``_is_terms_model_pvs_path``.
"""
from urllib.parse import quote

from .loader import get_paths, load_spec, normalize_path_for_base

# Synthetic skip for "past end of paginated collection" (STS returns 404 + detail JSON).
SKIP_OOB = 9_999_999


def _path_params_from_spec(operation: dict) -> list[dict]:
    """
    Extract OpenAPI ``parameters`` entries with ``in: path`` from a single operation.

    Returns:
        List of parameter dicts (name, schema, etc.) used to build URL path segments.
    """
    params = operation.get("parameters") or []
    return [p for p in params if isinstance(p, dict) and p.get("in") == "path"]


def _query_params_from_spec(operation: dict) -> list[dict]:
    """
    Extract OpenAPI ``parameters`` with ``in: query`` (e.g. skip, limit, version).

    Used to generate default query strings and optional bad-query negative cases.
    """
    params = operation.get("parameters") or []
    return [p for p in params if isinstance(p, dict) and p.get("in") == "query"]


def _response_codes(operation: dict) -> set[int]:
    """
    Collect numeric HTTP status codes declared under ``operation.responses``.

    Drives whether we emit 404-style vs 422-style negatives and bad-query cases.
    """
    responses = operation.get("responses") or {}
    return {int(k) for k in responses if str(k).isdigit()}


def _fill_path_template(template: str, path_param_values: dict[str, str], base_path: str = "/v2") -> str:
    """
    Substitute ``{paramName}`` placeholders with URL-encoded values.

    After substitution, strips a leading ``base_path`` (e.g. ``/v2``) so the result
    matches paths relative to ``APIClient.base_url`` (which already includes ``/v2``).
    """
    path = template
    for key, value in path_param_values.items():
        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    return normalize_path_for_base(path, base_path)


def _integer_skip_limit_names(query_params: list[dict]) -> set[str]:
    """
    Names of query parameters named ``skip`` or ``limit`` whose schema type is integer.

    Only those params are eligible for synthetic bad-query cases (e.g. skip=-1).
    """
    out = set()
    for p in query_params:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if name not in ("skip", "limit"):
            continue
        schema = p.get("schema") or {}
        if schema.get("type") == "integer":
            out.add(name)
    return out


def _has_integer_skip_or_limit(query_params: list[dict]) -> bool:
    """Whether the operation has at least one integer ``skip`` or ``limit`` query param."""
    return bool(_integer_skip_limit_names(query_params))


def _get_schema_ref(operation: dict) -> str | None:
    """
    Resolve the components schema name for a successful (200) JSON response.

    Follows ``application/json.schema.$ref`` or the first entry in ``anyOf``/``oneOf``.
    Used by the functional runner for light shape checks (entity vs list vs int).
    """
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
    Generate one positive GET case per operation (when discovery can fill path params),
    plus optional positives: ``__pagination_positive`` (``skip=0``, ``limit=1`` when both
    params exist), ``__pagination_pair`` (two GETs: ``skip=0,limit=0`` then ``skip=1,limit=1``,
    assert ``B[0]==A[1]`` when ``len(A)>=2``; excludes terms model-pvs / cde-pvs), optional
    negatives: bad ``skip``/``limit``, huge ``skip`` (``__skip_oob``),
    and invalid path params.

    Args:
        spec: Parsed OpenAPI document.
        test_data: Keys from ``discover()`` (model_handle, node_handle, etc.).
        base_path: Prefix stripped from spec paths (default ``/v2``).
        tag_filter: If set, only operations whose tags overlap this list.
        include_negative: If False, skip bad-query, skip-OOB, and invalid-path cases.

    Returns:
        List of case dicts, each with:
        ``path``, ``params``, ``expected_status``, ``operation_id``, ``summary``,
        ``tag``, ``negative``, ``response_schema_ref``, optional ``expected_json``, and
        optional ``skip_oob_assert`` (e.g. model-pvs empty permissible values), and
        optional ``pagination_assert_max_items`` for ``__pagination_positive`` cases, and
        optional ``pagination_pair_assert`` with ``pagination_pair_params_a`` / ``_b`` for
        ``__pagination_pair`` cases.
    """
    paths = get_paths(spec)
    cases = []

    for path_template, method, op in _iter_ops(spec, tag_filter):
        if path_template == "/":
            continue  # Root endpoint excluded from suite
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

            # Positive pagination: explicit skip=0, limit=1; runner asserts len(list) <= limit
            skip_limit_names_pos = _integer_skip_limit_names(query_params)
            if (
                200 in response_codes
                and "skip" in skip_limit_names_pos
                and "limit" in skip_limit_names_pos
            ):
                pag_q = dict(query_vals) if query_vals else {}
                pag_q["skip"] = 0
                pag_q["limit"] = 1
                cases.append({
                    "path": path_str,
                    "params": pag_q,
                    "expected_status": 200,
                    "operation_id": f"{operation_id}__pagination_positive",
                    "summary": f"{summary} (pagination: skip=0, limit=1)",
                    "tag": tag,
                    "negative": False,
                    "response_schema_ref": schema_ref,
                    "pagination_assert_max_items": 1,
                })

            # Pagination pair: A = skip=0, limit=0; B = skip=1, limit=1; assert B[0]==A[1] if len(A)>=2
            if (
                200 in response_codes
                and "skip" in skip_limit_names_pos
                and "limit" in skip_limit_names_pos
                and not _is_terms_model_pvs_path(path_template)
                and not _is_cde_pvs_by_id_pvs_path(path_template)
            ):
                pair_a = dict(query_vals) if query_vals else {}
                pair_a["skip"] = 0
                pair_a["limit"] = 0
                pair_b = dict(query_vals) if query_vals else {}
                pair_b["skip"] = 1
                pair_b["limit"] = 1
                cases.append({
                    "path": path_str,
                    "params": pair_a,
                    "expected_status": 200,
                    "operation_id": f"{operation_id}__pagination_pair",
                    "summary": (
                        f"{summary} (pagination pair: A skip=0 limit=0, B skip=1 limit=1)"
                    ),
                    "tag": tag,
                    "negative": False,
                    "response_schema_ref": schema_ref,
                    "pagination_pair_assert": True,
                    "pagination_pair_params_a": pair_a,
                    "pagination_pair_params_b": pair_b,
                })

            # Bad query param cases (422): valid path, invalid skip/limit
            if include_negative and 422 in response_codes and _has_integer_skip_or_limit(query_params):
                base_q = dict(query_vals) if query_vals else {}
                skip_limit_names = _integer_skip_limit_names(query_params)
                if "skip" in skip_limit_names:
                    bad_skip_params = {**base_q, "skip": -1}
                    cases.append({
                        "path": path_str,
                        "params": bad_skip_params,
                        "expected_status": 422,
                        "operation_id": f"{operation_id}__bad_query_skip",
                        "summary": f"{summary} (bad query: skip=-1)",
                        "tag": tag,
                        "negative": True,
                        "response_schema_ref": None,
                    })
                if "limit" in skip_limit_names:
                    bad_limit_params = {**base_q, "limit": "not_a_number"}
                    if "skip" not in bad_limit_params:
                        bad_limit_params["skip"] = 0
                    cases.append({
                        "path": path_str,
                        "params": bad_limit_params,
                        "expected_status": 422,
                        "operation_id": f"{operation_id}__bad_query_limit",
                        "summary": f"{summary} (bad query: limit=not_a_number)",
                        "tag": tag,
                        "negative": True,
                        "response_schema_ref": None,
                    })

            # Huge skip (past end): default 404 + detail; /terms/model-pvs and /terms/cde-pvs/.../pvs → 200
            if include_negative:
                skip_limit_names_oob = _integer_skip_limit_names(query_params)
                if "skip" in skip_limit_names_oob and (
                    404 in response_codes
                    or _is_terms_model_pvs_path(path_template)
                    or _is_cde_pvs_by_id_pvs_path(path_template)
                ):
                    base_oob = dict(query_vals) if query_vals else {}
                    oob_params = {**base_oob, "skip": SKIP_OOB}
                    oob_common = {
                        "path": path_str,
                        "params": oob_params,
                        "operation_id": f"{operation_id}__skip_oob",
                        "tag": tag,
                        "response_schema_ref": None,
                    }
                    if _is_cde_pvs_by_id_pvs_path(path_template):
                        cases.append({
                            **oob_common,
                            "expected_status": 200,
                            "summary": f"{summary} (skip past end: cde-pvs returns [])",
                            "negative": False,
                            "expected_json": [],
                        })
                    elif _is_terms_model_pvs_path(path_template):
                        cases.append({
                            **oob_common,
                            "expected_status": 200,
                            "summary": (
                                f"{summary} (skip past end: model-pvs empty permissibleValues)"
                            ),
                            "negative": False,
                            "skip_oob_assert": "model_pvs_empty_permissible_values",
                        })
                    elif 404 in response_codes:
                        cases.append({
                            **oob_common,
                            "expected_status": 404,
                            "summary": f"{summary} (skip past end: expect 404 Not found)",
                            "negative": True,
                            "expected_json": {"detail": "Not found."},
                        })

        # --- Negative: invalid path parameters ---
        # Only emit when the op has path params; otherwise the "negative" URL equals the
        # positive one (e.g. GET /models/) and expecting 404 would be wrong.
        if include_negative and path_params and (404 in response_codes or 422 in response_codes):
            # Expected status for "all path segments replaced with garbage":
            #
            # - Default for most routes: 404 if spec documents 404, else 422.
            # - Paths ending in /count (e.g. .../nodes/count): STS returns 200 with body 0
            #   for missing resources — so we expect 200, not 404.
            # - EXCEPTION — .../terms/count (property term count): unlike other *count*
            #   endpoints, this route returns 404 for invalid path context. We must NOT
            #   apply the 200+0 rule here; see _is_terms_property_count_path().
            # - EXCEPTION — GET .../terms/cde-pvs/{id}/{version}/pvs: returns 200 with
            #   body [] for invalid id/version; expect 200, not 404. See _is_cde_pvs_by_id_pvs_path().
            use_200_for_invalid_path = (
                _is_count_path(path_template) and not _is_terms_property_count_path(path_template)
            ) or _is_cde_pvs_by_id_pvs_path(path_template)
            expected = 200 if use_200_for_invalid_path else (404 if 404 in response_codes else 422)
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


def _is_count_path(path_template: str) -> bool:
    """
    True if the path template ends with ``/count`` (after trimming trailing slash).

    Includes both e.g. ``.../nodes/count`` and ``.../terms/count``. The latter is
    further classified by ``_is_terms_property_count_path`` for expectation logic.
    """
    return path_template.rstrip("/").endswith("/count")


def _is_terms_property_count_path(path_template: str) -> bool:
    """
    True for the property-level term **count** route only: ``.../terms/count``.

    Operation id in spec:
    ``model_..._property_..._terms_count_get``. For invalid path params, the API
    responds with **404**, not **200** with integer ``0`` like other ``*count``
    endpoints. This function excludes that path from the "count => expect 200" rule.
    """
    return path_template.rstrip("/").endswith("/terms/count")


def _is_cde_pvs_by_id_pvs_path(path_template: str) -> bool:
    """
    True for GET ``.../terms/cde-pvs/{id}/{version}/pvs`` only.

    For invalid id/version the API returns **200** with body **[]** (empty array)
    instead of 404. We expect 200 so the invalid-path negative case passes.
    """
    p = path_template.rstrip("/")
    return "terms/cde-pvs" in p and p.endswith("/pvs")


def _is_terms_model_pvs_path(path_template: str) -> bool:
    """
    True for GET ``.../terms/model-pvs/{model}/{property}``.

    With huge ``skip``, STS returns **200** with a JSON array of objects whose
    ``permissibleValues`` are ``[]`` (not 404 + detail).
    """
    p = path_template.rstrip("/")
    return (
        "terms/model-pvs" in p
        and "{model}" in path_template
        and "{property}" in path_template
    )


def _iter_ops(spec: dict, tag_filter: list[str] | None):
    """
    Yield ``(path_template, http_method, operation_dict)`` for every operation.

    Optionally filters by OpenAPI ``tags``. Used internally by ``generate_cases``.
    """
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
    """
    Map discovery dict to path parameter names (modelHandle, nodeHandle, id, etc.).

    Returns:
        Dict of param name -> value for the positive case, or ``None`` if any required
        value is missing so the operation is skipped for positive generation.
    """
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
    """
    Build path values using a fixed invalid string for every path param.

    Intended to produce a request the server treats as non-existent or invalid.
    """
    if not path_params:
        return {}
    invalid = "invalid_nonexistent_xyz"
    values = {}
    for p in path_params:
        name = p.get("name")
        if not name:
            continue
        values[name] = invalid
    return values


def _default_query_params(query_params: list[dict]) -> dict:
    """
    Sensible defaults for optional query params so list endpoints return a page.

    Uses schema ``default`` when present; integers default to 0 for skip-like names
    and 10 otherwise; booleans default to False.
    """
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
    """
    Merge discovery-derived query params into ``current`` for specific routes.

    Example: ``/terms/model-pvs/...`` needs ``version`` from discovered model version.
    """
    if "/terms/model-pvs/" in path_template and "version" in [p.get("name") for p in query_params]:
        if test_data.get("model_version"):
            current["version"] = test_data["model_version"]
    return current
