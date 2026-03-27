"""
Manual tests: **resolve by id** — ``GET /id/{nanoid}`` returns the right entity **type**.

================================================================================
WHAT THIS IS (plain English)
================================================================================

STS stores entities (models, nodes, properties, terms, etc.) with **stable string ids** (nanoids in
these tests). The **/id** endpoint lets a client fetch **one** object if they only know that id.
We verify the API returns **HTTP 200** and a JSON body whose ``type`` field matches what we expect
for that id (e.g. ``"Model"``, ``"Term"``).

**Why it matters:** Wrong ``type`` would break generic clients that branch on type after resolution.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- **Fixed ids:** ``ID_BY_TYPE`` — pairs ``(expected_type, nanoid)`` chosen so each nanoid maps to a
  known entity of that type on the **target STS** (typically QA). If data is re-seeded and an id
  disappears, this test will fail until ids are updated.

- **Endpoint:** ``GET /id/{nanoid}`` — no query parameters.

**Covered types:** Model, Node, Property, Term, Tag, Concept, Relationship, ValueSet (see list in
``ID_BY_TYPE``).

================================================================================
TESTS IN THIS FILE (summary)
================================================================================

**``test_id_endpoint_returns_200_and_type``** (parametrized over ``ID_BY_TYPE``)

- **Passes** if: status is 200, body parses as JSON, and ``data["type"] == expected_type``.
- **Fails** otherwise with an assertion message naming the path and expected vs actual type.

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_id_by_type.py -v

Uses ``api_client`` (``STS_BASE_URL``).
"""
import pytest

# (expected_type, nanoid) for each entity type
ID_BY_TYPE = [
    ("Model", "BXqzSM"),
    ("Node", "VTUKex"),
    ("Property", "dWCGhx"),
    ("Term", "sEzEfS"),
    ("Tag", "5kc0G6"),
    ("Concept", "hXZyty"),
    ("Relationship", "ueqz5Y"),
    ("ValueSet", "QGBE31"),
    #("Origin", "oHBbMJ"), # Origin test is turned off for now because of bug DATATEAM-430 -- uncomment when fixed
]


@pytest.mark.parametrize("expected_type, nanoid", ID_BY_TYPE)
def test_id_endpoint_returns_200_and_type(api_client, expected_type, nanoid):
    """
    Resolve a known nanoid and assert the JSON ``type`` matches the expected STS entity kind.

    See module docstring for why each pair in ``ID_BY_TYPE`` exists and how to run.
    """
    path = f"/id/{nanoid}"
    response = api_client.get(path)
    assert response.status_code == 200, (
        f"GET {path}: expected 200, got {response.status_code}"
    )
    data = response.json()
    assert data is not None, f"GET {path}: response body is not JSON"
    assert data.get("type") == expected_type, (
        f"GET {path}: expected type {expected_type!r}, got {data.get('type')!r}"
    )
