"""
Manual caDSR vs STS: special **permissible value** shapes (see ``case_type`` in JSON).

Cases live in ``data/cadsr_multi_concept_cdes_cases.json``.

**``case_type``: ``multi_concept_pv``** — set explicitly in JSON for each case when possible;
if omitted or empty, the test treats the case as ``multi_concept_pv`` (backward compatible).

1. **caDSR** ``GET .../DataElement/{cde_id}`` — find the PV whose ``value`` matches ``pv_value``.
   Assert ``ValueMeaning.Concepts`` has at least ``min_concept_count`` entries. Optionally assert
   ``expected_concept_codes`` matches the multiset of ``Concepts[].conceptCode``.

2. **STS cde-pvs** — exactly one row with that ``value``, ``ncit_concept_code: null``,
   ``synonyms: []``.

3. **STS model-pvs** — for each ``model`` / ``model_version`` / ``property``, exactly one
   matching row with null ncit and empty synonyms.

**``case_type``: ``url_pv_yaml_enum_model_pvs``**

1. **caDSR** — PV ``value`` is a URL (e.g. Uberon by-reference); same Concept checks as above.

2. **STS cde-pvs** — **not asserted** for this case type. QA STS may still return a primary
   ``ncit_concept_code`` and non-empty ``synonyms`` for the URL row on **cde-pvs**; this scenario
   focuses on **model-pvs** expansion only.

3. **STS model-pvs** — property is backed by an inline **Enum** in the data model YAML while
   caDSR lists a URL. Response must **not** include the URL; every row must have null ncit and
   ``synonyms: []``; multiset of ``value`` must equal ``PropDefinitions.{property}.Enum`` from the
   pinned YAML file (``yaml_enum.file`` / ``yaml_enum.property``). Exactly one ``model_pvs``
   binding is required.

**Run:**

::

    pytest tests/test_manual/test_cadsr_multi_concept_cdes.py -m cadsr_multi_concept_pv -v

**Environment:** ``STS_BASE_URL``, ``CADSR_BASE_URL``, ``STS_SSL_VERIFY`` (same as other caDSR
manual tests; see ``test_cadsr_alternatevalues_draftnew_cdes.py``).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any
from urllib.parse import quote

import pytest
import yaml

from sts_test_framework.client import APIClient, full_url
from sts_test_framework.config import cadsr_base_url, project_root

logger = logging.getLogger(__name__)

_DATA_FILE = project_root() / "data" / "cadsr_multi_concept_cdes_cases.json"

CASE_TYPE_MULTI = "multi_concept_pv"
CASE_TYPE_URL_ENUM = "url_pv_yaml_enum_model_pvs"


def _load_cases() -> list[dict[str, Any]]:
    if not _DATA_FILE.is_file():
        pytest.skip(f"Case data file not found: {_DATA_FILE}")
    with open(_DATA_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not cases:
        pytest.skip(f"No cases in {_DATA_FILE}")
    return cases


def _case_type(case: dict[str, Any]) -> str:
    """Return case_type from JSON, or ``multi_concept_pv`` when absent (see data file)."""
    t = case.get("case_type")
    if t is None or str(t).strip() == "":
        return CASE_TYPE_MULTI
    return str(t).strip()


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


def _data_element_dict(cadsr_data: dict[str, Any]) -> dict[str, Any] | None:
    """Single DataElement object from caDSR JSON (dict or one-element list)."""
    de = cadsr_data.get("DataElement")
    if isinstance(de, list) and len(de) > 0:
        first = de[0]
        return first if isinstance(first, dict) else None
    if isinstance(de, dict):
        return de
    return None


def _find_cadsr_pv_by_value(de_item: dict[str, Any], pv_value: str) -> dict[str, Any]:
    """Return the PermissibleValues dict whose ``value`` equals ``pv_value`` (exact string)."""
    for pv in _permissible_values_from_data_element(de_item):
        if not isinstance(pv, dict):
            continue
        v = pv.get("value")
        if v is not None and str(v) == pv_value:
            return pv
    pytest.fail(
        f"caDSR DataElement: no PermissibleValues row with value={pv_value!r} "
        f"(checked {len(_permissible_values_from_data_element(de_item))} row(s))"
    )


def _concept_codes_from_cadsr_pv(pv: dict[str, Any]) -> list[str]:
    """Non-empty ``conceptCode`` strings from ``ValueMeaning.Concepts``."""
    vm = pv.get("ValueMeaning")
    if not isinstance(vm, dict):
        pytest.fail("caDSR PV missing ValueMeaning object")
    concepts = vm.get("Concepts")
    if not isinstance(concepts, list):
        pytest.fail(
            f"caDSR ValueMeaning.Concepts expected list, got {type(concepts).__name__!r}"
        )
    out: list[str] = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        code = c.get("conceptCode")
        if code is not None and str(code).strip():
            out.append(str(code).strip())
    return out


def _load_yaml_enum_strings(rel_file: str, property_name: str) -> list[str]:
    """
    Load ``PropDefinitions[property_name].Enum`` from a model props YAML under project root.

    Each list item is normalized with ``str(...).strip()`` (supports string or numeric enums).
    """
    path = project_root() / rel_file
    if not path.is_file():
        pytest.fail(f"yaml_enum file not found: {path}")
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        pytest.fail(f"YAML root must be mapping: {path}")
    props = doc.get("PropDefinitions")
    if not isinstance(props, dict):
        pytest.fail(f"YAML missing PropDefinitions mapping: {path}")
    block = props.get(property_name)
    if not isinstance(block, dict):
        pytest.fail(f"YAML PropDefinitions[{property_name!r}] missing or not a mapping: {path}")
    raw_enum = block.get("Enum")
    if not isinstance(raw_enum, list):
        pytest.fail(
            f"YAML PropDefinitions[{property_name!r}].Enum must be a list: {path}"
        )
    out: list[str] = []
    for item in raw_enum:
        if item is None:
            continue
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _sts_permissible_values_from_list_body(body: Any) -> list[dict[str, Any]]:
    """First list element’s ``permissibleValues`` (cde-pvs / model-pvs shape)."""
    if not isinstance(body, list) or len(body) == 0:
        return []
    first = body[0]
    if not isinstance(first, dict):
        return []
    pvs = first.get("permissibleValues", [])
    return pvs if isinstance(pvs, list) else []


def _sts_value_strings(pvs: list[dict[str, Any]]) -> list[str]:
    """``value`` from each dict row (skip bad rows)."""
    out: list[str] = []
    for row in pvs:
        if not isinstance(row, dict):
            continue
        v = row.get("value")
        if v is not None:
            out.append(str(v))
    return out


def _sts_rows_for_pv_value(
    pvs: list[dict[str, Any]], pv_value: str
) -> list[dict[str, Any]]:
    """All permissibleValues rows whose ``value`` equals ``pv_value`` (exact)."""
    return [
        row
        for row in pvs
        if isinstance(row, dict)
        and row.get("value") is not None
        and str(row["value"]) == pv_value
    ]


def _assert_sts_row_null_ncit_empty_synonyms(
    row: dict[str, Any],
    *,
    endpoint_label: str,
    pv_value: str,
) -> None:
    ncit = row.get("ncit_concept_code")
    assert ncit is None, (
        f"{endpoint_label}: PV {pv_value!r} expected ncit_concept_code null, got {ncit!r}"
    )
    syn = row.get("synonyms")
    assert syn is not None, (
        f"{endpoint_label}: PV {pv_value!r} missing 'synonyms' key (expected [])"
    )
    assert syn == [], (
        f"{endpoint_label}: PV {pv_value!r} expected synonyms=[], got {syn!r}"
    )


def _assert_all_sts_rows_null_ncit_empty_synonyms(
    pvs: list[dict[str, Any]], endpoint_label: str
) -> None:
    for i, row in enumerate(pvs):
        if not isinstance(row, dict):
            pytest.fail(f"{endpoint_label}: row[{i}] expected object, got {type(row).__name__}")
        v = row.get("value")
        v_label = repr(v)[:80] if v is not None else "(no value)"
        ncit = row.get("ncit_concept_code")
        assert ncit is None, (
            f"{endpoint_label} row[{i}] value={v_label}: "
            f"expected ncit_concept_code null, got {ncit!r}"
        )
        syn = row.get("synonyms")
        assert syn is not None, (
            f"{endpoint_label} row[{i}] value={v_label}: "
            f"missing 'synonyms' key (expected [])"
        )
        assert syn == [], (
            f"{endpoint_label} row[{i}] value={v_label}: "
            f"expected synonyms=[], got {syn!r}"
        )


def _assert_no_row_with_value(
    pvs: list[dict[str, Any]], forbidden: str, endpoint_label: str
) -> None:
    matches = _sts_rows_for_pv_value(pvs, forbidden)
    assert not matches, (
        f"{endpoint_label}: expected no row with value={forbidden!r}, found {len(matches)}"
    )


@pytest.fixture(scope="session")
def cadsr_api_client():
    """HTTP client against ``CADSR_BASE_URL`` (``/DataElement/...``)."""
    return APIClient(cadsr_base_url())


def _case_id(case: dict[str, Any]) -> str:
    pid = case.get("pytest_param_id")
    if pid is not None and str(pid).strip():
        return str(pid).strip()
    return f"{case['cde_id']}-{case.get('pv_value', 'x')}"


@pytest.mark.cadsr_multi_concept_pv
@pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
def test_cadsr_multi_concept_pv_sts_null_ncit_and_synonyms(
    api_client: APIClient,
    cadsr_api_client: APIClient,
    case: dict[str, Any],
):
    cde_id = str(case["cde_id"])
    cde_version = str(case["cde_version"])
    pv_value = str(case["pv_value"])
    min_n = int(case["min_concept_count"])
    model_pvs_list = case.get("model_pvs")
    if not isinstance(model_pvs_list, list) or not model_pvs_list:
        pytest.fail("case must include non-empty model_pvs array")

    ctype = _case_type(case)
    case_label = _case_id(case)
    print(f"\n--- caDSR special PV vs STS ({ctype}): {case_label} ---")
    if case.get("description"):
        print(f"  Note: {case['description']}")

    # --- caDSR ---
    cadsr_path = f"/DataElement/{quote(cde_id, safe='')}"
    cadsr_url = full_url(cadsr_api_client, cadsr_path)
    print(f"  caDSR GET: {cadsr_url}")
    cadsr_res = cadsr_api_client.get(cadsr_path)
    assert cadsr_res.status_code == 200, (
        f"caDSR GET {cadsr_url} expected 200, got {cadsr_res.status_code}"
    )
    cadsr_json = cadsr_res.json()
    assert isinstance(cadsr_json, dict), (
        f"caDSR {cadsr_url}: expected JSON object, got {type(cadsr_json).__name__}"
    )
    de_item = _data_element_dict(cadsr_json)
    assert de_item is not None, "caDSR response missing DataElement"
    cadsr_pv = _find_cadsr_pv_by_value(de_item, pv_value)
    concept_codes = _concept_codes_from_cadsr_pv(cadsr_pv)
    print(
        f"  caDSR PV {pv_value!r}: {len(concept_codes)} conceptCode(s): {concept_codes!r}"
    )
    assert len(concept_codes) >= min_n, (
        f"caDSR: expected at least {min_n} conceptCode(s) under ValueMeaning.Concepts "
        f"for PV {pv_value!r}, got {len(concept_codes)}: {concept_codes!r}"
    )
    expected_codes = case.get("expected_concept_codes")
    if expected_codes is not None:
        if not isinstance(expected_codes, list):
            pytest.fail("expected_concept_codes must be a list when present")
        exp_norm = [str(x).strip() for x in expected_codes]
        assert Counter(concept_codes) == Counter(exp_norm), (
            f"caDSR Concepts conceptCode multiset mismatch: "
            f"got {sorted(Counter(concept_codes).items())!r} "
            f"expected {sorted(Counter(exp_norm).items())!r}"
        )
        print("  caDSR: expected_concept_codes multiset OK")

    # --- STS cde-pvs (multi_concept_pv only) ---
    # url_pv_yaml_enum_model_pvs: skip — STS cde-pvs may map the URL PV to an NCIt code and
    # synonyms (e.g. 14883047); assertions target model-pvs enum expansion instead.
    if ctype == CASE_TYPE_MULTI:
        cde_path = (
            f"/terms/cde-pvs/{quote(cde_id, safe='')}/{quote(cde_version, safe='')}/pvs"
        )
        cde_url = full_url(api_client, cde_path)
        print(f"  STS cde-pvs GET: {cde_url}")
        cde_res = api_client.get(cde_path)
        assert cde_res.status_code == 200, (
            f"STS cde-pvs GET {cde_url} expected 200, got {cde_res.status_code}"
        )
        cde_body = cde_res.json()
        cde_pvs = _sts_permissible_values_from_list_body(cde_body)
        cde_matches = _sts_rows_for_pv_value(cde_pvs, pv_value)
        assert len(cde_matches) == 1, (
            f"cde-pvs: expected exactly 1 row with value={pv_value!r}, "
            f"got {len(cde_matches)} (total permissibleValues={len(cde_pvs)})"
        )
        _assert_sts_row_null_ncit_empty_synonyms(
            cde_matches[0], endpoint_label="cde-pvs", pv_value=pv_value
        )
        print("  cde-pvs: ncit_concept_code null, synonyms [] OK")
    else:
        print(
            "  STS cde-pvs: skipped for url_pv_yaml_enum_model_pvs "
            "(only model-pvs is verified)"
        )

    # --- STS model-pvs ---
    if ctype == CASE_TYPE_URL_ENUM:
        ye = case.get("yaml_enum")
        if not isinstance(ye, dict):
            pytest.fail(
                f"case_type {CASE_TYPE_URL_ENUM!r} requires object yaml_enum "
                f"with file and property"
            )
        yaml_rel = ye.get("file")
        yaml_prop = ye.get("property")
        if not yaml_rel or not yaml_prop:
            pytest.fail("yaml_enum must include non-empty file and property")
        if len(model_pvs_list) != 1:
            pytest.fail(
                f"{CASE_TYPE_URL_ENUM}: expected exactly 1 model_pvs binding, "
                f"got {len(model_pvs_list)}"
            )
        yaml_values = _load_yaml_enum_strings(str(yaml_rel), str(yaml_prop))
        assert yaml_values, "YAML Enum list is empty"
        print(
            f"  YAML Enum {yaml_prop!r}: {len(yaml_values)} value(s) from {yaml_rel!r}"
        )

        binding = model_pvs_list[0]
        if not isinstance(binding, dict):
            pytest.fail(f"model_pvs entry must be object, got {type(binding).__name__}")
        model = str(binding["model"]).strip()
        model_version = str(binding["model_version"]).strip()
        prop = str(binding["property"]).strip()
        mp_path = f"/terms/model-pvs/{quote(model, safe='')}/{quote(prop, safe='')}"
        mp_url = full_url(api_client, mp_path, {"version": model_version})
        print(f"  STS model-pvs GET: {mp_url}")
        mp_res = api_client.get(mp_path, params={"version": model_version})
        assert mp_res.status_code == 200, (
            f"STS model-pvs GET {mp_url} expected 200, got {mp_res.status_code}"
        )
        mp_body = mp_res.json()
        mp_pvs = _sts_permissible_values_from_list_body(mp_body)
        label = f"model-pvs {model}/{prop}@{model_version}"
        assert len(mp_pvs) > 0, f"{label}: expected at least one permissibleValues row"
        _assert_no_row_with_value(mp_pvs, pv_value, label)
        print(f"  {label}: no row with URL value (expanded to enum) OK")
        _assert_all_sts_rows_null_ncit_empty_synonyms(mp_pvs, label)
        print(f"  {label}: all rows ncit null, synonyms [] OK")
        sts_vals = _sts_value_strings(mp_pvs)
        assert Counter(sts_vals) == Counter(yaml_values), (
            f"{label}: STS value multiset must match YAML Enum multiset\n"
            f"  STS count={len(sts_vals)} YAML count={len(yaml_values)}\n"
            f"  only_in_sts={sorted((Counter(sts_vals) - Counter(yaml_values)).elements())[:20]}\n"
            f"  only_in_yaml={sorted((Counter(yaml_values) - Counter(sts_vals)).elements())[:20]}"
        )
        print(f"  {label}: STS values match YAML Enum multiset ({len(sts_vals)} rows) OK")
    elif ctype == CASE_TYPE_MULTI:
        for binding in model_pvs_list:
            if not isinstance(binding, dict):
                pytest.fail(
                    f"model_pvs entry must be object, got {type(binding).__name__}"
                )
            model = str(binding["model"]).strip()
            model_version = str(binding["model_version"]).strip()
            prop = str(binding["property"]).strip()
            mp_path = f"/terms/model-pvs/{quote(model, safe='')}/{quote(prop, safe='')}"
            mp_url = full_url(api_client, mp_path, {"version": model_version})
            print(f"  STS model-pvs GET: {mp_url}")
            mp_res = api_client.get(mp_path, params={"version": model_version})
            assert mp_res.status_code == 200, (
                f"STS model-pvs GET {mp_url} expected 200, got {mp_res.status_code}"
            )
            mp_body = mp_res.json()
            mp_pvs = _sts_permissible_values_from_list_body(mp_body)
            mp_matches = _sts_rows_for_pv_value(mp_pvs, pv_value)
            label = f"model-pvs {model}/{prop}@{model_version}"
            assert len(mp_matches) == 1, (
                f"{label}: expected exactly 1 row with value={pv_value!r}, "
                f"got {len(mp_matches)} (total permissibleValues={len(mp_pvs)})"
            )
            _assert_sts_row_null_ncit_empty_synonyms(
                mp_matches[0], endpoint_label=label, pv_value=pv_value
            )
            print(f"  {label}: ncit null, synonyms [] OK")
    else:
        pytest.fail(f"Unknown case_type: {ctype!r}")

    print(f"  PASS {case_label}\n")
    logger.info("PASS %s", case_label)
