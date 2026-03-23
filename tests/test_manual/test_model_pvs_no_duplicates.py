"""
Manual tests: no **duplicate** permissible values inside model-pvs responses.

================================================================================
WHAT THIS IS (plain English)
================================================================================

Each **permissible value** in a property’s list should appear **once** (for a given canonical
identity). If the same value appears twice in ``permissibleValues``, clients and validators can
double-count or show duplicate options — that was a real product bug.

These tests call ``GET /terms/model-pvs/{model}/{property}`` (with a pinned ``version``), walk the
JSON rows, and **fail** if any row’s ``permissibleValues`` array contains duplicates (by a stable
key: ``value`` / preferred name / etc.; see ``pv_key`` in this file).

**Port:** Evolved from ``endpoint_tests/verify_dedup_across_models.py``.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

1. **Discovery test** (``test_model_pvs_no_duplicate_permissible_values``)

   - **Models:** ``MAJOR_MODELS`` from ``conftest`` (C3DC, CCDI, CCDI-DCC, ICDC, CTDC, CDS, PSDC).
   - **Version:** ``get_latest_version`` — **release** version preferred; falls back to latest
     (including pre-release) when a model has no release.
   - **Which properties:** walks model nodes/properties via the API. ``STS_DEDUP_LIMIT`` is a **global**
     cap on discovered cases, **split across** ``len(MAJOR_MODELS)``: ``base = limit // n``,
     ``extra = limit % n`` — the first ``extra`` models (in list order) get ``base + 1`` properties
     each; the rest get ``base``. Adding models to ``MAJOR_MODELS`` scales automatically (no hardcoded count).

2. **Bug-ticket regression** (``test_model_pvs_no_duplicates_bug_ticket_endpoints``)

   - **Fixed tuples:** ``BUG_TICKET_MODEL_PVS_CASES`` — explicit ``model`` / ``property`` / ``version``
     from the original dedup ticket (always run; expects HTTP 200 and no duplicates).

**Environment:** ``STS_BASE_URL`` (current STS). ``STS_DEDUP_LIMIT`` — total discovered cases (default
**60**), **fairly split** across all major models; use e.g. **14** for a smaller run (with 7 models,
2 properties each when discovery succeeds).

================================================================================
TESTS IN THIS FILE (summary)
================================================================================

**``test_model_pvs_no_duplicate_permissible_values``**

- Discovers cases, then for each: ``GET .../model-pvs/{model}/{property}?version=...``.
- **Skips** individual cases that do not return 200 or a list (prints a line).
- **Fails** if any item’s ``permissibleValues`` has duplicate keys.

**``test_model_pvs_no_duplicates_bug_ticket_endpoints``**

- Same duplicate check on **fixed** paths only.
- **Fails** on non-200 or non-list (stricter than discovery test — ticket endpoints must work).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_model_pvs_no_duplicates.py -v

Optional: ``STS_DEDUP_LIMIT=14`` for a smaller total cap (e.g. 2 per model with 7 models).
"""
import json
import os
import pytest
from collections import Counter
from urllib.parse import quote

from sts_test_framework.discover import get_latest_version

from .conftest import MAJOR_MODELS

# Original bug ticket: regression coverage for specific model-pvs endpoints
BUG_TICKET_MODEL_PVS_CASES = [
    {"model": "CCDI-DCC", "property": "comorbidity", "version": "1.0.0"},
    {"model": "CCDI-DCC", "property": "medical_history_condition", "version": "1.0.0"},
    {"model": "CDS", "property": "file_type", "version": "11.0.0"},
]

# Default: 60 total discovered cases, split across len(MAJOR_MODELS) (fair remainder to first models).
# Override with STS_DEDUP_LIMIT.
def _dedup_limit():
    try:
        return int(os.getenv("STS_DEDUP_LIMIT", "140"))
    except ValueError:
        return 140


def _max_properties_for_model_index(max_total: int, n_models: int, model_index: int) -> int:
    """
    Fair split of max_total across n_models: first (max_total % n_models) models get one extra slot.

    Example: max_total=60, n=7 -> 9+9+9+9+8+8+8. Scales when MAJOR_MODELS grows (uses n_models, not 7).
    """
    if n_models <= 0 or max_total <= 0:
        return 0
    base = max_total // n_models
    extra = max_total % n_models
    return base + (1 if model_index < extra else 0)


def pv_key(pv):
    """Canonical key for a permissible value (string or dict)."""
    if isinstance(pv, str):
        return pv
    if isinstance(pv, dict):
        for k in ("value", "preferred_name", "preferredName"):
            if k in pv and pv[k] is not None:
                return pv[k]
        return json.dumps(pv, sort_keys=True)
    return json.dumps(pv, sort_keys=True, default=repr)


def has_duplicates(permissible_values):
    """Return (has_duplicates: bool, duplicate_values: list)."""
    if not isinstance(permissible_values, list) or len(permissible_values) <= 1:
        return False, []
    keys = [pv_key(pv) for pv in permissible_values]
    counts = Counter(keys)
    dups = [k for k, c in counts.items() if c > 1]
    return len(dups) > 0, dups


def item_signature(item):
    if not isinstance(item, dict):
        return None
    return (item.get("model"), item.get("property"), item.get("version"))


def discover_model_pvs_cases(client, major_models, max_total: int):
    """
    Discover (model, property, version) for major models; release preferred, fallback to latest-version
    endpoint when no release.

    ``max_total`` is a **global** cap split **across every** handle in ``major_models`` (see
    ``_max_properties_for_model_index``). No single model can consume the whole budget and skip
    later models.
    """
    out: list[dict] = []
    seen_pair: set[tuple[str, str]] = set()
    n = len(major_models)
    if n == 0 or max_total <= 0:
        return out

    for model_index, model_handle in enumerate(major_models):
        max_per_model = _max_properties_for_model_index(max_total, n, model_index)
        if max_per_model <= 0:
            continue
        ver = get_latest_version(client, model_handle)
        if not ver:
            continue
        taken = 0
        nodes_path = f"/model/{quote(model_handle, safe='')}/version/{quote(ver, safe='')}/nodes"
        nr = client.get(nodes_path)
        if nr.status_code != 200:
            continue
        nodes = nr.json()
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if taken >= max_per_model:
                break
            node_handle = node.get("handle")
            if not node_handle:
                continue
            props_path = (
                f"/model/{quote(model_handle, safe='')}/version/{quote(ver, safe='')}"
                f"/node/{quote(node_handle, safe='')}/properties"
            )
            pr = client.get(props_path)
            if pr.status_code != 200:
                continue
            props = pr.json()
            if not isinstance(props, list):
                continue
            for prop in props:
                if taken >= max_per_model:
                    break
                prop_handle = prop.get("handle")
                if prop_handle and (model_handle, prop_handle) not in seen_pair:
                    seen_pair.add((model_handle, prop_handle))
                    out.append({"model": model_handle, "property": prop_handle, "version": ver})
                    taken += 1
            if taken >= max_per_model:
                break
    return out


def test_model_pvs_no_duplicate_permissible_values(api_client):
    """
    Discover model/property/version cases from ``MAJOR_MODELS``, then assert no duplicate PV rows.

    See module docstring for discovery rules and ``STS_DEDUP_LIMIT``.
    """
    limit = _dedup_limit()
    cases = discover_model_pvs_cases(api_client, MAJOR_MODELS, max_total=limit)
    if not cases:
        pytest.skip("No model/property/version cases discovered (check API and major models)")

    print(f"\nmodel-pvs no-duplicates: testing {len(cases)} model/property/version combinations")
    for case in cases:
        print(f"  {case['model']}/{case['property']} (v{case['version']})")

    failures = []
    for case in cases:
        path = f"/terms/model-pvs/{quote(case['model'], safe='')}/{quote(case['property'], safe='')}"
        response = api_client.get(path, params={"version": case["version"]})
        if response.status_code != 200:
            print(f"  -> {case['model']}/{case['property']} v{case['version']}: skip (HTTP {response.status_code})")
            continue
        data = response.json()
        if not isinstance(data, list):
            print(f"  -> {case['model']}/{case['property']} v{case['version']}: skip (response not a list)")
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            pvs = item.get("permissibleValues", [])
            has_dup, dup_vals = has_duplicates(pvs)
            if has_dup:
                failures.append(
                    {
                        "model": case["model"],
                        "property": case["property"],
                        "version": case["version"],
                        "item": item_signature(item),
                        "duplicate_values": dup_vals,
                    }
                )
        if not any(f["model"] == case["model"] and f["property"] == case["property"] for f in failures):
            print(f"  -> {case['model']}/{case['property']} v{case['version']}: OK (no duplicates)")

    if failures:
        msg = "Duplicate permissible values found:\n"
        for f in failures:
            msg += f"  {f['model']}/{f['property']} v{f['version']} item={f['item']} dups={f['duplicate_values']}\n"
        pytest.fail(msg)


def test_model_pvs_no_duplicates_bug_ticket_endpoints(api_client):
    """
    Regression: fixed ``BUG_TICKET_MODEL_PVS_CASES`` must return 200 and contain no duplicate PVs.

    See module docstring for ticket context.
    """
    cases = BUG_TICKET_MODEL_PVS_CASES
    print(f"\nmodel-pvs bug-ticket endpoints: testing {len(cases)} combinations")
    for case in cases:
        print(f"  {case['model']}/{case['property']} (v{case['version']})")

    failures = []
    for case in cases:
        path = f"/terms/model-pvs/{quote(case['model'], safe='')}/{quote(case['property'], safe='')}"
        response = api_client.get(path, params={"version": case["version"]})
        if response.status_code != 200:
            pytest.fail(
                f"{case['model']}/{case['property']} v{case['version']}: "
                f"expected 200, got HTTP {response.status_code}"
            )
        data = response.json()
        if not isinstance(data, list):
            pytest.fail(
                f"{case['model']}/{case['property']} v{case['version']}: "
                f"expected JSON list, got {type(data).__name__}"
            )
        for item in data:
            if not isinstance(item, dict):
                continue
            pvs = item.get("permissibleValues", [])
            has_dup, dup_vals = has_duplicates(pvs)
            if has_dup:
                failures.append(
                    {
                        "model": case["model"],
                        "property": case["property"],
                        "version": case["version"],
                        "item": item_signature(item),
                        "duplicate_values": dup_vals,
                    }
                )
        if not any(f["model"] == case["model"] and f["property"] == case["property"] for f in failures):
            print(f"  -> {case['model']}/{case['property']} v{case['version']}: OK (no duplicates)")

    if failures:
        msg = "Bug-ticket model-pvs: duplicate permissible values found:\n"
        for f in failures:
            msg += f"  {f['model']}/{f['property']} v{f['version']} item={f['item']} dups={f['duplicate_values']}\n"
        pytest.fail(msg)
