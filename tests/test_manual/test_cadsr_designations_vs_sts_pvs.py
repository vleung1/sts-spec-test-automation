"""
Manual tests: caDSR **Designations** vs STS **cde-pvs** and **model-pvs** (``cadsr_alt_pvs`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

For pinned CDE + model + property rows (see ``data/cadsr_sts_pvs_cases.json``), we:

1. Load **caDSR** ``GET .../DataElement/{cde_id}`` and collect every ``Designations[].name``
   (all designation **types** — e.g. ``MCL Alt Name`` is one example) under ``PermissibleValues``
   / ``ValueMeaning``, same traversal as ``mdb/cadsr_verification/verify_cadsr_sync.py`` extended
   for the JSON API shape.
2. Load STS **cde-pvs**, ``GET /terms/cde-pvs/{cde_id}/{cde_version}/pvs``.
3. Load STS **model-pvs**, ``GET /terms/model-pvs/{model}/{property}`` with
   ``version={model_version}``.

For **each** endpoint’s ``permissibleValues`` list we assert:

- No duplicate ``value`` strings (case-sensitive).
- Every **unique** caDSR designation ``name`` appears as some row’s ``value`` (exact match).

If caDSR returns no Designations for a CDE, designation checks are skipped; duplicate-value
checks still run.

================================================================================
ENVIRONMENT
================================================================================

- ``STS_BASE_URL`` — v2 STS root (default QA).
- ``CADSR_BASE_URL`` — caDSR API root (default ``https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api``).
   Paths used: ``/DataElement/{cde_id}``.
- ``CADSR_DESIGNATION_TYPES`` — optional: comma-separated ``Designations[].type`` values to **limit**
  which names are required in STS (default: **unset** = require **all** designation names). Use this
  only if you need a narrower check (e.g. ``MCL Alt Name``).
- ``STS_SSL_VERIFY`` — applies to both STS and caDSR clients (same ``APIClient`` behavior).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_cadsr_designations_vs_sts_pvs.py -m cadsr_alt_pvs -v

Console output uses ``print`` (visible with pytest ``-s``; this project sets ``addopts = -v -s``).
Use ``--log-cli-level=INFO`` for duplicate ``logger`` lines.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from typing import Any, FrozenSet

# Max designation names to print per case (avoid huge stdout).
_DESIGNATION_PREVIEW = 12
from urllib.parse import quote

import pytest

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import cadsr_base_url, project_root

logger = logging.getLogger(__name__)

_DATA_FILE = project_root() / "data" / "cadsr_sts_pvs_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    if not _DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_DATA_FILE}")
    with open(_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_DATA_FILE}")
    return cases


def _permissible_values_from_data_element(de_item: dict[str, Any]) -> list[Any]:
    """PermissibleValues list from DataElement (direct or under ValueDomain)."""
    pvs = de_item.get("PermissibleValues")
    if isinstance(pvs, list):
        return pvs
    vd = de_item.get("ValueDomain")
    if isinstance(vd, dict):
        pvs = vd.get("PermissibleValues")
        if isinstance(pvs, list):
            return pvs
    return []


def _allowed_designation_types() -> FrozenSet[str] | None:
    """
    ``None`` = include **all** ``Designations[].name`` values (default).

    If ``CADSR_DESIGNATION_TYPES`` is set to a non-empty comma-separated list, only designation
    rows whose ``type`` is in that set are required to appear in STS.
    """
    raw = os.getenv("CADSR_DESIGNATION_TYPES", "").strip()
    if not raw or raw == "*":
        return None
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def _designation_names_from_pv(
    pv: dict[str, Any],
    allowed_types: FrozenSet[str] | None,
) -> list[str]:
    """Designation ``name`` strings from one PV row (root or under ValueMeaning)."""
    names: list[str] = []
    for block in (pv, pv.get("ValueMeaning") if isinstance(pv.get("ValueMeaning"), dict) else None):
        if not isinstance(block, dict):
            continue
        des = block.get("Designations")
        if not isinstance(des, list):
            continue
        for des_item in des:
            if not isinstance(des_item, dict) or des_item.get("name") is None:
                continue
            if allowed_types is not None:
                t = des_item.get("type")
                if t not in allowed_types:
                    continue
            names.append(str(des_item["name"]))
    return names


def _designation_name_type_pairs_unfiltered(cadsr_data: dict[str, Any]) -> list[tuple[str, str | None]]:
    """All ``(name, type)`` from Designations (for logging / type histogram)."""
    pairs: list[tuple[str, str | None]] = []
    if not isinstance(cadsr_data, dict):
        return pairs
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        de_item = de[0]
    elif isinstance(de, dict):
        de_item = de
    else:
        return pairs
    if not isinstance(de_item, dict):
        return pairs
    pvs = _permissible_values_from_data_element(de_item)
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        for block in (
            pv,
            pv.get("ValueMeaning") if isinstance(pv.get("ValueMeaning"), dict) else None,
        ):
            if not isinstance(block, dict):
                continue
            des = block.get("Designations")
            if not isinstance(des, list):
                continue
            for des_item in des:
                if not isinstance(des_item, dict) or des_item.get("name") is None:
                    continue
                t = des_item.get("type")
                t_str = str(t) if t is not None else None
                pairs.append((str(des_item["name"]), t_str))
    return pairs


def _extract_cadsr_designation_names(
    cadsr_data: dict[str, Any],
    allowed_types: FrozenSet[str] | None,
) -> list[str]:
    """
    All ``Designations[].name`` for the DataElement.

    Handles:

    - ``DataElement`` as dict or one-element list (caDSR JSON).
    - ``PermissibleValues`` on the element or under ``ValueDomain`` (REST JSON).
    - ``Designations`` on each PV or under ``PV.ValueMeaning`` (common in JSON API).
    """
    designations: list[str] = []
    if not isinstance(cadsr_data, dict):
        return designations
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        de_item = de[0]
    elif isinstance(de, dict):
        de_item = de
    else:
        return designations
    if not isinstance(de_item, dict):
        return designations

    pvs = _permissible_values_from_data_element(de_item)
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        designations.extend(_designation_names_from_pv(pv, allowed_types))
    return designations


def _sts_permissible_values_from_list_body(body: Any) -> list[dict[str, Any]]:
    """First list element’s ``permissibleValues`` (cde-pvs / model-pvs shape)."""
    if not isinstance(body, list) or len(body) == 0:
        return []
    first = body[0]
    if not isinstance(first, dict):
        return []
    pvs = first.get("permissibleValues", [])
    return pvs if isinstance(pvs, list) else []


def _pv_values_list(pvs: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        v = pv.get("value")
        if v is not None:
            out.append(str(v))
    return out


def _assert_no_duplicate_values(pvs: list[dict[str, Any]], endpoint_label: str) -> None:
    values = _pv_values_list(pvs)
    counts = Counter(values)
    dups = {k: c for k, c in counts.items() if c > 1}
    assert not dups, (
        f"{endpoint_label}: duplicate permissibleValues.value (case-sensitive): {dups!r}"
    )


def _assert_designations_present(
    unique_names: set[str],
    pv_values: set[str],
    endpoint_label: str,
) -> None:
    missing = unique_names - pv_values
    if missing:
        missing_sorted = sorted(missing)
        print(
            f"  {endpoint_label}: MISSING {len(missing)} designation name(s) "
            f"(not exact PV value): {missing_sorted!r}"
        )
        logger.warning(
            "%s: missing %s designation name(s) as PV value: %r",
            endpoint_label,
            len(missing),
            missing_sorted,
        )
    assert not missing, (
        f"{endpoint_label}: caDSR designation name(s) not found as PV value: "
        f"{sorted(missing)!r}"
    )


@pytest.fixture(scope="session")
def cadsr_api_client():
    """HTTP client against ``CADSR_BASE_URL`` (``/DataElement/...``)."""
    return APIClient(cadsr_base_url())


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['cde_id']}-{case.get('property', 'x')}"


@pytest.mark.cadsr_alt_pvs
@pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
def test_cadsr_designations_match_cde_pvs_and_model_pvs(
    api_client: APIClient,
    cadsr_api_client: APIClient,
    case: dict[str, Any],
):
    cde_id = str(case["cde_id"])
    cde_version = str(case["cde_version"])
    model = str(case["model"])
    model_version = str(case["model_version"])
    prop = str(case["property"])
    case_label = _case_id(case)

    print(f"\n--- caDSR Designations vs STS PVS: {case_label} ---")
    print(
        f"  Pinned case: CDE {cde_id} @ {cde_version} | "
        f"model {model} @ {model_version} | property {prop!r}"
    )
    if case.get("description"):
        print(f"  Note: {case['description']}")

    cadsr_path = f"/DataElement/{quote(cde_id, safe='')}"
    cadsr_url = full_url(cadsr_api_client, cadsr_path)
    print(f"  caDSR GET: {cadsr_url}")
    cadsr_res = cadsr_api_client.get(cadsr_path)
    print(
        f"  caDSR HTTP: {cadsr_res.status_code} in {cadsr_res.duration:.3f}s"
    )
    assert cadsr_res.status_code == 200, (
        f"caDSR GET {cadsr_url} expected 200, got {cadsr_res.status_code}"
    )
    cadsr_json = cadsr_res.json()
    assert isinstance(cadsr_json, dict), (
        f"caDSR {cadsr_url}: expected JSON object, got {type(cadsr_json).__name__}. "
        "HTML responses are not supported for Designations extraction."
    )

    allowed = _allowed_designation_types()
    if allowed is None:
        filter_msg = "all Designations[].name values (every type)"
        print(f"  Designation filter: {filter_msg}")
    else:
        filter_msg = f"only types in {sorted(allowed)!r}"
        print(f"  Designation filter: {filter_msg} (CADSR_DESIGNATION_TYPES)")

    all_pairs = _designation_name_type_pairs_unfiltered(cadsr_json)
    type_hist = Counter(t for _, t in all_pairs)
    print(
        f"  caDSR (unfiltered): {len(all_pairs)} designation row(s); "
        f"by type: {dict(type_hist)}"
    )

    designation_names = _extract_cadsr_designation_names(cadsr_json, allowed)
    unique_designations = set(designation_names)
    print(
        f"  After filter: {len(designation_names)} name occurrence(s), "
        f"{len(unique_designations)} unique string(s) must appear as STS PV value"
    )
    if unique_designations:
        preview = sorted(unique_designations)[:_DESIGNATION_PREVIEW]
        more = len(unique_designations) - len(preview)
        extra = f" … (+{more} more)" if more > 0 else ""
        print(f"  Unique designation names (sample): {preview!r}{extra}")
    logger.info(
        "Case %s: filter=%s caDSR designation occurrences=%s unique=%s",
        case_label,
        filter_msg,
        len(designation_names),
        len(unique_designations),
    )

    # --- cde-pvs ---
    cde_path = (
        f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
    )
    cde_url = full_url(api_client, cde_path)
    print(f"  STS cde-pvs GET: {cde_url}")
    cde_res = api_client.get(cde_path)
    print(
        f"  STS cde-pvs HTTP: {cde_res.status_code} in {cde_res.duration:.3f}s"
    )
    assert cde_res.status_code == 200, (
        f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
    )
    cde_body = cde_res.json()
    cde_pvs = _sts_permissible_values_from_list_body(cde_body)
    req_label = (
        f"every required designation name ∈ PV values ({len(unique_designations)} name(s))"
        if unique_designations
        else "no designation names to match (duplicate check only)"
    )
    print(
        f"  Verify cde-pvs: {len(cde_pvs)} permissibleValues row(s); "
        f"no duplicate value (case-sensitive); {req_label}"
    )
    _assert_no_duplicate_values(cde_pvs, "cde-pvs")
    print("  cde-pvs: duplicate-value check OK")
    cde_value_set = set(_pv_values_list(cde_pvs))
    if unique_designations:
        _assert_designations_present(unique_designations, cde_value_set, "cde-pvs")
        print("  cde-pvs: all required designation names found as value")

    # --- model-pvs ---
    mp_path = (
        f"/terms/model-pvs/{quote(model, safe='')}/{quote(prop, safe='')}"
    )
    mp_url = full_url(api_client, mp_path, {"version": model_version})
    print(f"  STS model-pvs GET: {mp_url}")
    mp_res = api_client.get(mp_path, params={"version": model_version})
    print(
        f"  STS model-pvs HTTP: {mp_res.status_code} in {mp_res.duration:.3f}s"
    )
    assert mp_res.status_code == 200, (
        f"STS model-pvs GET {mp_url} expected 200, got {mp_res.status_code}"
    )
    mp_body = mp_res.json()
    mp_pvs = _sts_permissible_values_from_list_body(mp_body)
    print(
        f"  Verify model-pvs: {len(mp_pvs)} permissibleValues row(s); "
        f"no duplicate value (case-sensitive); {req_label}"
    )
    _assert_no_duplicate_values(mp_pvs, "model-pvs")
    print("  model-pvs: duplicate-value check OK")
    mp_value_set = set(_pv_values_list(mp_pvs))
    if unique_designations:
        _assert_designations_present(unique_designations, mp_value_set, "model-pvs")
        print("  model-pvs: all required designation names found as value")

    print(
        f"  PASS {case_label}: "
        f"unique designation names checked={len(unique_designations)} | "
        f"cde-pvs rows={len(cde_pvs)} | model-pvs rows={len(mp_pvs)}\n"
    )
    logger.info(
        "PASS %s: unique_designations=%s cde_pvs_rows=%s model_pvs_rows=%s",
        case_label,
        len(unique_designations),
        len(cde_pvs),
        len(mp_pvs),
    )
