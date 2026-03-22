"""
Manual tests: verify v2/terms/model-pvs returns no duplicate permissible values.

Port of endpoint_tests/verify_dedup_across_models.py. Uses major models
(C3DC, CCDI, CCDI-DCC, ICDC, CTDC, CDS, PSDC). Release versions preferred;
falls back to latest (including pre-release) when a model has no release version.
Asserts no duplicate PVs on current env (STS_BASE_URL).

Second test covers explicit model/property/version pairs from the original bug ticket.
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

# Limit cases for default run (14 = 7 models × 2 props); override with STS_DEDUP_LIMIT (e.g. 14 or 60)
def _dedup_limit():
    try:
        return int(os.getenv("STS_DEDUP_LIMIT", "14"))
    except ValueError:
        return 14


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


def discover_model_pvs_cases(client, major_models, limit=12, max_per_model=2):
    """Discover (model, property, version) for major models; release preferred, fallback to latest-version endpoint when no release."""
    out = []
    seen_pair = set()
    for model_handle in major_models:
        if len(out) >= limit:
            break
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
            if len(out) >= limit or taken >= max_per_model:
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
                if len(out) >= limit or taken >= max_per_model:
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
    """GET model-pvs for major models (release versions); assert no duplicate PVs in any item."""
    limit = _dedup_limit()
    max_per_model = 2 if limit <= 14 else 10
    cases = discover_model_pvs_cases(api_client, MAJOR_MODELS, limit=limit, max_per_model=max_per_model)
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
    """v2/terms/model-pvs for paths from the original dedup bug ticket (fixed model/property/version)."""
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
