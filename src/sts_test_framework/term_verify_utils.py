"""
Shared utility functions for all term-by-value verification pipelines.

These were previously embedded in ``ccdi_term_verify.py`` (and imported by other modules)
or duplicated across model-specific files. Centralizing them here removes the implicit
dependency on one model file and avoids duplication.
"""
from __future__ import annotations

from urllib.parse import quote

from .client import APIClient


def verify_row(
    client: APIClient,
    model_handle: str,
    version_string: str,
    node_handle: str,
    prop_handle: str,
    term_value: str,
) -> tuple[int, bool, str]:
    """
    GET the term-by-value endpoint and check the response.

    Calls::

        GET /model/{model_handle}/version/{version_string}/node/{node_handle}/
            property/{prop_handle}/term/{url_encoded_term_value}

    ``term_value`` must be the Term **value** field (what enrichment resolves from the YAML
    handle via ``/terms``), except for CDS which uses the YAML handle directly.

    Returns:
        ``(http_status, passed, notes)`` where ``passed`` means status 200 and the response
        JSON array contains at least one object with ``"value" == term_value``.
    """
    quoted_term = quote(str(term_value), safe="")
    path = (
        f"/model/{quote(model_handle, safe='')}/version/{quote(version_string, safe='')}"
        f"/node/{quote(node_handle, safe='')}/property/{quote(prop_handle, safe='')}"
        f"/term/{quoted_term}"
    )
    response = client.get(path)
    status = response.status_code
    body = response.json()

    if status != 200:
        body_note = body if isinstance(body, dict) else (response.body[:200] if response.body else "")
        return status, False, "non-200" if isinstance(body, dict) else str(body_note)
    if not isinstance(body, list):
        return status, False, "response not array"
    for item in body:
        if isinstance(item, dict) and item.get("value") == term_value:
            return status, True, ""
    return status, False, "no matching term value in response"


def strip_inline_yaml_comment(raw: str) -> str:
    """
    Drop YAML ``# comment`` suffix when the ``#`` starts a comment (not inside quotes).

    Handles lines like ``"Data Submitter" # these? ...`` producing ``"Data Submitter"``.
    """
    in_dq = False
    in_sq = False
    escape = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\" and in_dq:
            escape = True
            i += 1
            continue
        if c == '"' and not in_sq:
            in_dq = not in_dq
        elif c == "'" and not in_dq:
            in_sq = not in_sq
        elif c == "#" and not in_dq and not in_sq:
            return raw[:i].rstrip()
        i += 1
    return raw


def clean_enum_value(val: str) -> str:
    """
    Normalize one raw enum list item (ICDC style).

    Strips a trailing `` #...`` comment only when the value does **not** start with a quote
    (so values like ``"CD3/CD30 Cells, #, Blood"`` stay intact), then removes surrounding quotes.
    """
    val = val.strip()
    idx = val.find(" #")
    if idx != -1:
        val = val[:idx]
    val = val.strip()
    if len(val) >= 2:
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1].replace('\\"', '"').replace("\\'", "'")
    return val.strip()
