"""
Manual tests: legacy **CDE-PVS** JSON vs **v2** ``/terms/cde-pvs/.../pvs`` (``cde_pvs_legacy`` marker).

================================================================================
WHAT THIS IS (plain English)
================================================================================

The CRDC Data Hub historically used the **legacy** endpoint::

    GET {origin}/cde-pvs/{cde_id}/{cde_version}?format=json

STS v2 exposes the same conceptual data at::

    GET {v2}/terms/cde-pvs/{cde_id}/{cde_version}/pvs

where ``{v2}`` is ``STS_BASE_URL`` (default ``https://sts-qa.cancer.gov/v2``) and **origin**
is :func:`sts_test_framework.config.sts_legacy_origin` (same host, **without** ``/v2``).

**Business rule we check:** For fixed CDE id/version pairs, the **CDE metadata** (code, version,
full name) matches, and **every distinct** ``(value, ncit_concept_code)`` pair from the legacy
permissible values appears **at least once** in v2 (set inclusion of keys). Legacy may emit
**duplicate** rows for the same pair; v2 often dedupes, so we do **not** require row-for-row
multiset multiplicity. Synonyms are ignored for the key. v2 may list **additional** PV rows (e.g.
``ncit_concept_code: null`` alternates); that is expected and allowed.

================================================================================
WHERE THE DATA COMES FROM
================================================================================

- **Legacy:** ``APIClient(sts_legacy_origin())`` — ``GET /cde-pvs/{id}/{version}`` with
  ``format=json``.
- **v2:** Session ``api_client`` — ``GET /terms/cde-pvs/{id}/{version}/pvs`` (same SSL / base
  resolution as other manual tests).

================================================================================
HOW TO RUN
================================================================================

::

    pytest tests/test_manual/test_cde_pvs_legacy_vs_v2.py -m cde_pvs_legacy -v

Uses ``STS_BASE_URL`` for v2; legacy origin is derived (see :func:`~sts_test_framework.config.sts_legacy_origin`).
Each case prints a short trace (URLs, HTTP status and timing, CDE fields, PV row/distinct counts,
v2-only pairs). For duplicate ``logger`` lines in CI, use ``--log-cli-level=INFO``; default pytest
output shows the ``print`` lines when not captured (this project uses ``-s`` in ``addopts``).
"""
from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import quote

import pytest

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import sts_legacy_origin

logger = logging.getLogger(__name__)

# Max characters of CDEFullName to print/log (keep output readable).
_CDE_FULL_NAME_PREVIEW = 120


def _preview(text: object, limit: int = _CDE_FULL_NAME_PREVIEW) -> str:
    """Short string for logging; ellipsis if longer than ``limit``."""
    s = str(text) if text is not None else ""
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


# Fixed CDE id/version pairs (legacy Data Hub vs v2 parity checks).
CDE_PVS_LEGACY_CASES: list[tuple[str, str]] = [
    ("11416926", "1.00"),
    ("11253427", "1.00"),
    ("16476366", "1"),
]


def _normalize_top_level(data: object) -> dict | None:
    """Extract CDECode, CDEVersion, CDEFullName, permissibleValues from legacy or v2 JSON."""
    if data is None:
        return None
    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            return {
                "CDECode": first.get("CDECode"),
                "CDEVersion": first.get("CDEVersion"),
                "CDEFullName": first.get("CDEFullName"),
                "permissibleValues": first.get("permissibleValues", []),
            }
        if isinstance(first, list) and len(first) > 3:
            return {
                "CDECode": first[0],
                "CDEVersion": first[1],
                "CDEFullName": first[2],
                "permissibleValues": first[3] if isinstance(first[3], list) else [],
            }
    if isinstance(data, dict):
        return {
            "CDECode": data.get("CDECode"),
            "CDEVersion": data.get("CDEVersion"),
            "CDEFullName": data.get("CDEFullName"),
            "permissibleValues": data.get("permissibleValues", []),
        }
    return None


def _pv_to_tuple(pv: object) -> tuple:
    """
    Hashable multiset key for one permissible value (legacy and v2).

    Uses **(value, ncit_concept_code)** only. Synonym lists often differ between the
    legacy JSON route and v2; including synonyms would falsely fail checks while CDE
    metadata still matches.
    """
    if isinstance(pv, dict):
        val = pv.get("value")
        ncit = pv.get("ncit_concept_code")
        return (val, ncit)
    return (str(pv), None)


def _counter_from_pvs(pvs: object) -> Counter:
    """Multiset of normalized PV tuples."""
    if not isinstance(pvs, list):
        return Counter()
    return Counter(_pv_to_tuple(pv) for pv in pvs)


@pytest.fixture(scope="session")
def legacy_api_client():
    """HTTP client against STS origin (no ``/v2``) for ``/cde-pvs/...``."""
    return APIClient(sts_legacy_origin())


@pytest.mark.cde_pvs_legacy
@pytest.mark.parametrize(
    "cde_id,cde_version",
    CDE_PVS_LEGACY_CASES,
    ids=[f"{i}-{v}" for i, v in CDE_PVS_LEGACY_CASES],
)
def test_legacy_cde_pvs_distinct_pairs_subset_of_v2(
    api_client,
    legacy_api_client,
    cde_id: str,
    cde_version: str,
):
    """
    Legacy ``/cde-pvs/...?format=json`` distinct ``(value, ncit)`` pairs must each
    appear in v2 ``/terms/cde-pvs/.../pvs``; CDE metadata must match.
    """
    legacy_path = f"/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}"
    v2_path = (
        f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
    )

    legacy_url = full_url(legacy_api_client, legacy_path, {"format": "json"})
    v2_url = full_url(api_client, v2_path)

    print(f"\n--- CDE-PVS legacy vs v2: {cde_id}/{cde_version} ---")
    print(f"  Legacy GET: {legacy_url}")
    print(f"  v2 GET:     {v2_url}")
    logger.info(
        "CDE-PVS legacy vs v2: case %s/%s legacy_url=%s v2_url=%s",
        cde_id,
        cde_version,
        legacy_url,
        v2_url,
    )

    legacy_res = legacy_api_client.get(legacy_path, params={"format": "json"})
    v2_res = api_client.get(v2_path)

    print(
        f"  HTTP: legacy {legacy_res.status_code} in {legacy_res.duration:.3f}s | "
        f"v2 {v2_res.status_code} in {v2_res.duration:.3f}s"
    )
    logger.info(
        "HTTP timings: legacy status=%s duration=%.3fs | v2 status=%s duration=%.3fs",
        legacy_res.status_code,
        legacy_res.duration,
        v2_res.status_code,
        v2_res.duration,
    )

    assert legacy_res.status_code == 200, (
        f"Legacy GET {legacy_url} expected 200, got {legacy_res.status_code}"
    )
    assert v2_res.status_code == 200, (
        f"v2 GET {v2_url} expected 200, got {v2_res.status_code}"
    )

    legacy_data = legacy_res.json()
    v2_data = v2_res.json()
    assert legacy_data is not None, f"Legacy {legacy_url}: not JSON"
    assert v2_data is not None, f"v2 {v2_url}: not JSON"

    norm_leg = _normalize_top_level(legacy_data)
    norm_v2 = _normalize_top_level(v2_data)
    assert norm_leg is not None, f"Legacy response shape unusable: {legacy_data!r}"
    assert norm_v2 is not None, f"v2 response shape unusable: {v2_data!r}"

    for field in ("CDECode", "CDEVersion", "CDEFullName"):
        assert norm_leg.get(field) == norm_v2.get(field), (
            f"CDE metadata mismatch for {cde_id}/{cde_version} field {field!r}: "
            f"legacy={norm_leg.get(field)!r} v2={norm_v2.get(field)!r}"
        )

    cde_code = norm_leg.get("CDECode")
    cde_ver = norm_leg.get("CDEVersion")
    cde_name = norm_leg.get("CDEFullName")
    print(
        f"  CDE metadata OK: CDECode={cde_code!r} CDEVersion={cde_ver!r} "
        f"CDEFullName={_preview(cde_name)!r}"
    )
    logger.info(
        "CDE metadata OK: CDECode=%r CDEVersion=%r CDEFullName=%r",
        cde_code,
        cde_ver,
        cde_name,
    )

    leg_pvs = norm_leg.get("permissibleValues", [])
    v2_pvs = norm_v2.get("permissibleValues", [])
    c_leg = _counter_from_pvs(leg_pvs)
    c_v2 = _counter_from_pvs(v2_pvs)

    keys_leg = set(c_leg)
    keys_v2 = set(c_v2)
    legacy_row_total = sum(c_leg.values())
    v2_row_total = sum(c_v2.values())
    legacy_dup_rows = legacy_row_total - len(keys_leg)
    v2_only_keys = keys_v2 - keys_leg
    v2_null_ncit_extras = sum(
        1 for (val, ncit) in v2_only_keys if ncit is None
    )

    print(
        f"  PV rows: legacy {legacy_row_total} rows, {len(keys_leg)} distinct (value, ncit); "
        f"v2 {v2_row_total} rows, {len(keys_v2)} distinct"
    )
    if legacy_dup_rows:
        print(
            f"  Note: legacy has {legacy_dup_rows} duplicate-row pair(s) "
            f"(same value+ncit repeated); v2 may list each once."
        )
    print(
        f"  v2-only distinct pairs: {len(v2_only_keys)} "
        f"({v2_null_ncit_extras} with ncit_concept_code=null, e.g. alternates)"
    )
    logger.info(
        "PV summary: legacy_rows=%s legacy_distinct=%s v2_rows=%s v2_distinct=%s "
        "legacy_dup_rows=%s v2_only_distinct=%s v2_only_null_ncit=%s",
        legacy_row_total,
        len(keys_leg),
        v2_row_total,
        len(keys_v2),
        legacy_dup_rows,
        len(v2_only_keys),
        v2_null_ncit_extras,
    )

    missing = keys_leg - keys_v2
    assert not missing, (
        f"Legacy (value, ncit) pairs missing from v2 for {cde_id}/{cde_version}: "
        f"{sorted(missing)}. legacy_url={legacy_url} v2_url={v2_url}"
    )

    logger.info(
        "cde_pvs legacy vs v2 OK: %s/%s legacy_distinct=%s legacy_rows=%s v2_rows=%s",
        cde_id,
        cde_version,
        len(keys_leg),
        legacy_row_total,
        v2_row_total,
    )
    print(
        f"  PASS: {cde_id}/{cde_version} — every legacy distinct (value,ncit) appears in v2 "
        f"(legacy_rows={legacy_row_total}, v2_rows={v2_row_total})\n"
    )
