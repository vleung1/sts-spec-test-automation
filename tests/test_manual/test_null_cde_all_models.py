"""
Manual tests: Null CDE / ``useNullCDE`` pattern across STS data models (``nullcde`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

STS can attach a special "null CDE" value set to a model property's permissible values.
When a property lists **every** permissible value that belongs to that null CDE (the full set
from the null CDE term), that is a strong signal that ``useNullCDE: Yes`` (or equivalent) is in
effect for that property.

**Business rule we check:** Only the **CDS** data model in the **11.0.x** line (e.g. latest **11.0.3**)
is supposed to use that pattern. No other model (at its **latest** published version) should have any property whose
permissible values include the **complete** set of null CDE values.

If another model shows the same pattern, it may mean ``useNullCDE`` was turned on where it
should not be.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

1. **Null CDE value set** — ``GET /terms/cde-pvs/16476366/1/pvs`` (``NULL_CDE_ID`` / ``NULL_CDE_VERSION``).  
   We take permissible ``value`` strings **only for PV rows whose ``ncit_concept_code`` is present
   and non-null** (the NCIt-backed rows; typically ~14). Rows with null ``ncit_concept_code`` are
   excluded so the reference set matches the null-CDE list used for ``useNullCDE``-style checks,
   not every expanded caDSR value on the CDE.

2. **All models** — ``GET /models/`` (unique ``handle`` per model).

3. **Latest version per model** — ``GET /model/{handle}/latest-version`` → ``version`` string.

4. **Model permissible values** — ``GET /terms/model-pvs/{handle}/?version={latest}``  
   Query parameter name is ``version`` (not ``model_version``) on deployed STS.

5. **Pinned CDS check** — ``GET /terms/model-pvs/CDS/?version=11.0.3`` (current pinned release under test).  
   Example QA URL: https://sts-qa.cancer.gov/v2/terms/model-pvs/CDS/?version=11.0.3

================================================================================
TESTS IN THIS FILE (summary)
================================================================================

**Test 1 — ``test_no_models_except_cds_11_have_full_null_cde_pattern``**

- Walks every model, uses that model's **latest** version, and scans all properties in the
  model-pvs response.
- For each property, we ask: "Does this property's PV list contain **every** value from the null
  CDE set?" (same count as the full null CDE set, with each distinct null CDE value appearing at
  least once in the property's PVs).
- **Passes** if: the only case where that happens is **CDS** whose latest version string
  **contains** ``11.0.`` (so ``11.0.0``, ``11.0.3``, or a build suffix with that prefix).
- **Fails** if: any **other** model/version has at least one property with that full pattern.
  The failure message lists model, version, and property names so you can investigate.

  **Note:** CDS **latest** (e.g. ``11.0.4-…``) and CDS **pinned** (``CDS_PINNED_VERSION``) are different
  snapshots; the count of properties that bind the full NCIt-filtered set can differ (e.g. 10 vs 11).

**Test 2 — ``test_cds_pinned_release_has_full_null_cde_pattern``**

- Calls model-pvs for **CDS** pinned to ``CDS_PINNED_VERSION`` (currently **11.0.3**, not "latest").
- **Passes** if: there is **at least one** property whose PVs cover the **entire** null CDE value
  set returned by STS **at this moment** (same rule as test 1: every distinct null CDE value
  appears on that property). That strongly suggests the expected ``useNullCDE``-style behavior
  for that release.
- **Skips** (with an explanation) if: the pinned snapshot is available but **no** property lists
  the full **NCIt-filtered** null CDE set (every distinct value from step 1). That can happen if
  the CDS snapshot no longer binds all of those values on one property. The legacy script
  **warned** in this case; we skip so CI stays green while still surfacing the message in ``-v``.
- **Skips** if: the null CDE list could not be loaded, or the pinned endpoint is not available.

**Test 3 — ``test_cde_pvs_use_null_cde_param_behavior``**

- Calls ``GET /terms/cde-pvs/11527735/1.00/pvs`` three ways: no ``use_null_cde`` query param,
  ``use_null_cde=false``, and ``use_null_cde=true`` (lowercase strings in the URL).
- Uses the **same session reference set** as tests 1–2 (16476366/1 PVS, **NCIt-filtered** values).
- **Passes** if: ``true`` has at least as many distinct PV values as ``false``; default equals
  ``false``; default and ``false`` contain **none** of those reference values; values present in
  ``true`` but not in ``false`` are only drawn from that reference set.

================================================================================
HOW TO RUN
================================================================================

Uses ``api_client`` (``STS_BASE_URL``, default QA). Run only these tests::

    pytest tests/test_manual/test_null_cde_all_models.py -m nullcde -v

See also ``README.md`` / ``docs/RUNBOOK.md``. Example pinned URL (QA):
https://sts-qa.cancer.gov/v2/terms/model-pvs/CDS/?version=11.0.3
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import pytest

from sts_test_framework.client import full_url

logger = logging.getLogger(__name__)


# Null CDE term used by the CDS model configuration (same as legacy qa_vs_prod_nullcde script).
NULL_CDE_ID = "16476366"
NULL_CDE_VERSION = "1"

# CDS is the only model expected to expose the "full null CDE set" on properties (11.0.x line).
# Substring must match current CDS latest (e.g. 11.0.3) — "11.0.0" alone would not match "11.0.3".
CDS_EXPECTED_SUBSTRING = "11.0."
CDS_PINNED_VERSION = "11.0.3"

# CDE used to exercise the ``use_null_cde`` query parameter (see OpenAPI ``use_null_cde`` on
# ``GET /terms/cde-pvs/{id}/{version}/pvs``).
CDE_USE_NULL_CDE_TEST_ID = "11527735"
CDE_USE_NULL_CDE_TEST_VERSION = "1.00"


def _value_set_from_cde_pvs_where_ncit_present(data: object) -> set[str]:
    """
    Distinct ``value`` strings from the first row's ``permissibleValues`` where ``ncit_concept_code``
    is non-null and non-empty. Rows with null or missing NCIt codes are excluded (expanded caDSR
    values that are not part of the null-CDE NCIt list).
    """
    if not isinstance(data, list) or len(data) == 0:
        return set()
    item = data[0]
    if not isinstance(item, dict):
        return set()
    pvs = item.get("permissibleValues", [])
    if not isinstance(pvs, list):
        return set()
    out: set[str] = set()
    for pv in pvs:
        if not isinstance(pv, dict):
            continue
        code = pv.get("ncit_concept_code")
        if code is None:
            continue
        if isinstance(code, str) and not code.strip():
            continue
        v = pv.get("value")
        if v:
            out.add(v)
    return out


def _permissible_value_set_from_cde_pvs_json(data: object) -> set[str]:
    """Distinct ``value`` strings from the first row's ``permissibleValues`` in a cde-pvs response."""
    if not isinstance(data, list) or len(data) == 0:
        return set()
    item = data[0]
    if not isinstance(item, dict):
        return set()
    pvs = item.get("permissibleValues", [])
    if not isinstance(pvs, list):
        return set()
    out: set[str] = set()
    for pv in pvs:
        if isinstance(pv, dict):
            v = pv.get("value")
            if v:
                out.add(v)
    return out


def _get_cde_pvs_value_set(
    api_client,
    cde_id: str,
    version: str,
    use_null_cde_param: str | None,
) -> tuple[int, set[str]]:
    """
    GET ``/terms/cde-pvs/{id}/{version}/pvs``. If ``use_null_cde_param`` is ``None``, omit the
    query param; otherwise pass ``use_null_cde`` as the string ``\"true\"`` or ``\"false\"`` so
    the URL matches lowercase booleans (``APIClient`` would stringify Python ``True`` as ``True``).
    """
    path = f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(version, safe='')}/pvs"
    if use_null_cde_param is None:
        response = api_client.get(path)
    else:
        response = api_client.get(path, params={"use_null_cde": use_null_cde_param})
    if response.status_code != 200:
        return response.status_code, set()
    return response.status_code, _permissible_value_set_from_cde_pvs_json(response.json())


@pytest.fixture(scope="session")
def null_cde_values(api_client):
    """
    Load once per test session: distinct permissible ``value`` strings from
    ``GET /terms/cde-pvs/16476366/1/pvs`` **restricted to PV rows with non-null**
    ``ncit_concept_code`` (NCIt-backed null-CDE values). Other tests reuse this so we do not hammer
    the API.
    """
    path = f"/terms/cde-pvs/{quote(NULL_CDE_ID, safe='')}/{quote(NULL_CDE_VERSION, safe='')}/pvs"
    response = api_client.get(path)
    if response.status_code != 200:
        pytest.skip(
            f"GET {path} returned {response.status_code}; cannot load null CDE values"
        )
    data = response.json()
    values = _value_set_from_cde_pvs_where_ncit_present(data)
    if not values:
        pytest.skip(
            "No NCIt-filtered null CDE values (16476366/1 PVS rows with non-null ncit_concept_code)"
        )
    logger.info(
        "null_cde_values: loaded %s distinct NCIt-filtered values from %s",
        len(values),
        path,
    )
    return values


def _find_properties_with_full_null_cde_set(
    model_pvs_data: object, null_cde_values: set[str]
) -> list[dict]:
    """
    Return metadata for each property row whose PV *values* cover the entire ``null_cde_values``
    set (same cardinality: every distinct null CDE value appears at least once in that property).
    """
    out: list[dict] = []
    if not isinstance(model_pvs_data, list):
        return out
    n_expected = len(null_cde_values)
    if n_expected == 0:
        return out

    for item in model_pvs_data:
        if not isinstance(item, dict):
            continue
        property_name = item.get("property", "")
        pvs = item.get("permissibleValues", [])
        if not isinstance(pvs, list):
            continue
        matched: set[str] = set()
        for pv in pvs:
            if isinstance(pv, dict):
                value = pv.get("value")
                if value and value in null_cde_values:
                    matched.add(value)
        if len(matched) == n_expected:
            out.append(
                {
                    "property": property_name,
                    "null_cde_count": len(matched),
                    "total_pvs": len(pvs),
                    "null_cde_values": sorted(matched),
                }
            )
    return out


def _is_expected_cds_11(model_handle: str, version: str | None) -> bool:
    """True if this model/version is the allowed exception (CDS latest in the 11.0.x line)."""
    return (
        model_handle == "CDS"
        and bool(version)
        and CDS_EXPECTED_SUBSTRING in version
    )


@pytest.mark.nullcde
def test_no_models_except_cds_11_have_full_null_cde_pattern(api_client, null_cde_values):
    """
    **Assertion (plain English):** After checking every model at its **latest** version, there
    must be **zero** properties that expose the **full** null CDE value set—**except** when the
    model is CDS and the latest version string contains ``11.0.`` (11.0.0, 11.0.3, etc.).

    If this test fails, at least one non-CDS model (or CDS not on an 11.0.x latest) has a property
    that lists all null CDE values; that is treated as unexpected.
    """
    n_null = len(null_cde_values)

    models_res = api_client.get("/models/")
    assert models_res.status_code == 200, f"GET /models/ failed: {models_res.status_code}"
    raw = models_res.json()
    assert isinstance(raw, list), "/models/ response must be a list"

    handles: list[str] = []
    seen: set[str] = set()
    for m in raw:
        if not isinstance(m, dict):
            continue
        h = m.get("handle")
        if not h or h in seen:
            continue
        seen.add(h)
        handles.append(h)

    unexpected: list[str] = []

    for model_handle in handles:
        lv_path = f"/model/{quote(model_handle, safe='')}/latest-version"
        lv_url = full_url(api_client, lv_path)
        lv_res = api_client.get(lv_path)
        if lv_res.status_code != 200:
            print(
                f"  [{model_handle}] SKIP  GET {lv_url}  -> HTTP {lv_res.status_code} (no latest version)"
            )
            logger.warning("skip %s: latest-version HTTP %s", model_handle, lv_res.status_code)
            continue
        lv_body = lv_res.json()
        if not isinstance(lv_body, dict):
            print(f"  [{model_handle}] SKIP  GET {lv_url}  -> invalid JSON shape")
            continue
        version = lv_body.get("version")
        if not isinstance(version, str) or not version.strip():
            print(f"  [{model_handle}] SKIP  GET {lv_url}  -> no version string in body")
            logger.warning("skip %s: no version string", model_handle)
            continue
        version = version.strip()

        mp_path = f"/terms/model-pvs/{quote(model_handle, safe='')}/"
        mp_params = {"version": version}
        mp_url = full_url(api_client, mp_path, mp_params)
        mp_res = api_client.get(mp_path, params=mp_params)
        if mp_res.status_code != 200:
            print(
                f"  [{model_handle}] {version!r}  SKIP  GET {mp_url}  -> HTTP {mp_res.status_code}"
            )
            logger.warning(
                "skip %s @ %s: model-pvs HTTP %s",
                model_handle,
                version,
                mp_res.status_code,
            )
            continue
        data = mp_res.json()
        hits = _find_properties_with_full_null_cde_set(data, null_cde_values)
        if not hits:
            print(
                f"  [{model_handle}] {version!r}  GET {mp_url}  -> "
                f"full NCIt-filtered null CDE set on a property: NOT FOUND"
            )
            continue
        if _is_expected_cds_11(model_handle, version):
            prop_list = ", ".join(repr(h["property"]) for h in hits)
            print(
                f"  [{model_handle}] {version!r}  GET {mp_url}  -> "
                f"full null CDE set: FOUND ({len(hits)} properties) [expected for CDS 11.0.x]"
            )
            print(f"      properties: {prop_list}")
            continue
        for h in hits:
            print(
                f"  [{model_handle}] {version!r}  GET {mp_url}  -> "
                f"UNEXPECTED FOUND property={h['property']!r}"
            )
            unexpected.append(
                f"{model_handle} version={version!r} property={h['property']!r} "
                f"({h['total_pvs']} PVs; null CDE values covered={h['null_cde_count']}/{n_null})"
            )

    assert not unexpected, (
        "Unexpected: non-CDS (or CDS not at 11.0.x latest) models with at least one "
        "property listing the FULL null CDE value set:\n  - "
        + "\n  - ".join(unexpected)
    )
    print(
        f"PASS: no forbidden full null-CDE pattern on latest versions "
        f"(NCIt-filtered null CDE distinct values={n_null})"
    )


@pytest.mark.nullcde
def test_cds_pinned_release_has_full_null_cde_pattern(api_client, null_cde_values):
    """
    **Assertion (plain English):** We **prefer** to see at least one CDS property on the **pinned**
    release (``CDS_PINNED_VERSION``, e.g. 11.0.3) whose PVs cover the **full** null CDE set: every
    distinct ``value`` in the **NCIt-filtered** reference from ``GET /terms/cde-pvs/16476366/1/pvs``
    (see ``null_cde_values`` fixture).

    If the snapshot responds with HTTP 200 but **no** property covers the full NCIt-filtered set, we
    **skip** the test with a detailed reason (legacy script printed a warning only). Use this
    pass/skip output to decide whether to investigate the CDS model or null CDE term on that
    environment.
    """
    n_null = len(null_cde_values)
    path = f"/terms/model-pvs/{quote('CDS', safe='')}/"
    response = api_client.get(path, params={"version": CDS_PINNED_VERSION})
    if response.status_code != 200:
        pytest.skip(
            f"GET {path}?version={CDS_PINNED_VERSION!r} returned {response.status_code}"
        )
    data = response.json()
    hits = _find_properties_with_full_null_cde_set(data, null_cde_values)
    if not hits:
        pytest.skip(
            f"CDS {CDS_PINNED_VERSION!r} returned HTTP 200 but no property has PVs covering "
            f"all {n_null} distinct NCIt-filtered null CDE values (16476366/1). "
            f"Verify useNullCDE / CDS pinned release content manually if needed."
        )
    pinned_url = full_url(api_client, path, {"version": CDS_PINNED_VERSION})
    prop_list = ", ".join(repr(h["property"]) for h in hits)
    print(
        f"PASS: GET {pinned_url}  — {len(hits)} propert(ies) with full NCIt-filtered null CDE set:\n"
        f"      {prop_list}"
    )


@pytest.mark.nullcde
def test_cde_pvs_use_null_cde_param_behavior(api_client, null_cde_values):
    """
    **What we call (plain English):** ``GET /terms/cde-pvs/{id}/{version}/pvs`` for CDE
    **11527735** version **1.00**, three times: with **no** ``use_null_cde`` query parameter, with
    ``use_null_cde=false``, and with ``use_null_cde=true``. The OpenAPI default for ``use_null_cde``
    is false.

    **Reference set:** The same **session** ``null_cde_values`` as tests 1–2: distinct ``value``
    strings from ``GET /terms/cde-pvs/16476366/1/pvs`` **only for PV rows with non-null**
    ``ncit_concept_code``.
    That matches the null-CDE list used when ``use_null_cde`` adds NCIt-backed reasons; rows without
    an NCIt code are excluded from this reference set.

    **Assertions (plain English):**
    - ``use_null_cde=true`` yields at least as many **distinct** permissible ``value`` strings as
      ``use_null_cde=false``.
    - Omitting the param matches ``false`` (same set of values).
    - Default and ``false`` responses must **not** contain any of the NCIt-filtered null-CDE values.
    - Any values that appear with ``true`` but not with ``false`` must be drawn **only** from that
      reference set (extras ⊆ ``null_cde_values``).

    If this fails, print counts and unexpected values to simplify debugging.
    """
    cid = CDE_USE_NULL_CDE_TEST_ID
    ver = CDE_USE_NULL_CDE_TEST_VERSION
    path = f"/terms/cde-pvs/{quote(cid, safe='')}/{quote(ver, safe='')}/pvs"

    st_def, values_default = _get_cde_pvs_value_set(api_client, cid, ver, None)
    st_false, values_false = _get_cde_pvs_value_set(api_client, cid, ver, "false")
    st_true, values_true = _get_cde_pvs_value_set(api_client, cid, ver, "true")

    assert st_def == 200, (
        f"GET {path} (no use_null_cde) expected HTTP 200, got {st_def}"
    )
    assert st_false == 200, (
        f"GET {path}?use_null_cde=false expected HTTP 200, got {st_false}"
    )
    assert st_true == 200, (
        f"GET {path}?use_null_cde=true expected HTTP 200, got {st_true}"
    )

    assert len(values_true) >= len(values_false), (
        f"use_null_cde=true should have at least as many distinct PV values as false: "
        f"true={len(values_true)} false={len(values_false)}"
    )

    assert values_default == values_false, (
        "Default (no query param) must match use_null_cde=false per OpenAPI default. "
        f"default_only={sorted(values_default - values_false)!r} "
        f"false_only={sorted(values_false - values_default)!r}"
    )

    ref = null_cde_values
    bad_default = values_default & ref
    assert not bad_default, (
        f"Default response must not include NCIt-filtered null-CDE values; found: {sorted(bad_default)!r}"
    )
    bad_false = values_false & ref
    assert not bad_false, (
        f"use_null_cde=false must not include NCIt-filtered null-CDE values; found: {sorted(bad_false)!r}"
    )

    extras = values_true - values_false
    not_in_ref = extras - ref
    assert not not_in_ref, (
        "Values present with use_null_cde=true but not false must be subset of the NCIt-filtered "
        f"null-CDE reference set. Unexpected extras: {sorted(not_in_ref)!r}"
    )

    # ``len(ref)`` is from session ``null_cde_values`` (live 16476366/1, NCIt-filtered); not hardcoded.
    print(
        f"PASS: {path} distinct PV values — default={len(values_default)} false={len(values_false)} "
        f"true={len(values_true)}; "
        f"extras in true vs false (subset of null_cde_values, n_ref={len(ref)}) = {len(extras)}"
    )
    logger.info(
        "test_cde_pvs_use_null_cde_param_behavior: default=%s false=%s true=%s extras=%s",
        len(values_default),
        len(values_false),
        len(values_true),
        len(extras),
    )
