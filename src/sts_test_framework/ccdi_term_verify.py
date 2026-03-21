"""
CCDI term-by-value verification pipeline driven by vendored ``ccdi-model-props.yml``.

**Pipeline (ports ``termValue_verification_scripts`` for CCDI)**

1. **extract** — Scan the property YAML (line-based, no PyYAML) for ``Enum:`` lists under each
   property. Each list item is a **term handle** in STS (stored as ``enum_value`` in CSV).
   Writes a per-property summary CSV and a flat “query” CSV (one row per handle).

2. **enrich** — Call STS to find the latest CCDI model version, map each property handle to a
   **node** (first node that declares the property), then for each ``(node, property)`` pair
   paginate ``GET .../terms`` to build **handle → display value**. Copy that value into
   ``term_value``. The **URL** for ``/term/{termValue}`` must use this API **value**, not the
   handle.

3. **verify** — For each enriched row with a non-empty ``term_value``, ``GET`` the term-by-value
   endpoint and assert the JSON array contains an object whose ``value`` equals ``term_value``.

**Shared API** — :func:`verify_row` is imported by other ``*_term_verify`` modules so all models use
the same HTTP check.

CLI: ``sts-ccdi-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote
from .client import APIClient

MODEL_HANDLE = "CCDI"

# --- repo paths ---

def _repo_root() -> Path:
    """Project root (parent of ``src/``)."""
    return Path(__file__).resolve().parent.parent.parent


def default_yaml_path() -> Path:
    """Vendored CCDI property YAML under the repo ``data/`` tree (override with ``--yaml``)."""
    return _repo_root() / "data" / "data-models-yaml" / "ccdi-model-props.yml"


def default_report_dir() -> Path:
    """Default directory for extract/enrich/verify CSV + Markdown (override with ``--out-dir``)."""
    return _repo_root() / "reports" / "term_value" / "CCDI"


# --- extract (regex parse; matches extract_ccdi_enum_properties.py) ---

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER = "    Enum:"
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


def strip_inline_yaml_comment(raw: str) -> str:
    """
    Drop YAML ``# comment`` suffix when the ``#`` starts a comment, not when it is inside quotes.

    Handles lines like: ``- "Data Submitter" # these? ...`` → ``- "Data Submitter"`` (caller strips list marker).
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


def parse_ccdi_yaml_props(path: Path) -> list[tuple[str, str, list[str]]]:
    """
    Walk the CCDI property YAML and collect every property that has an ``Enum`` block.

    Uses the same line/regex strategy as ``extract_ccdi_enum_properties.py``: two-space property
    keys, four-space ``Desc:`` and ``Enum:``, list items under ``Enum`` until the next four-space
    key. Enum entries are **handles** (after stripping inline ``#`` comments and YAML quotes).

    Returns:
        List of ``(prop_handle, description, enum_values)`` where ``enum_values`` are deduped
        in file order.
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result: list[tuple[str, str, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        prop_match = PROP_PATTERN.match(line)
        if prop_match:
            prop_handle = prop_match.group(1)
            desc = ""
            enum_values: list[str] = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("  ") and not cur.startswith("    ") and PROP_PATTERN.match(cur):
                    break
                desc_match = DESC_PATTERN.match(cur)
                if desc_match:
                    desc = desc_match.group(1).strip().replace("\n", " ").replace("\r", " ")
                    i += 1
                    continue
                if cur.rstrip() == ENUM_HEADER:
                    i += 1
                    while i < len(lines):
                        item_line = lines[i]
                        if ENUM_END_PATTERN.match(item_line):
                            break
                        item_match = ENUM_ITEM_PATTERN.match(item_line)
                        if item_match:
                            val = strip_inline_yaml_comment(item_match.group(1).strip())
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1].replace('\\"', '"').replace("\\'", "'")
                            if val:
                                enum_values.append(val)
                            i += 1
                        else:
                            i += 1
                    continue
                i += 1

            if enum_values:
                seen: set[str] = set()
                deduped: list[str] = []
                for v in enum_values:
                    if v not in seen:
                        seen.add(v)
                        deduped.append(v)
                result.append((prop_handle, desc, deduped))
        else:
            i += 1

    return result


def run_extract(yaml_path: Path, out_dir: Path) -> tuple[Path, Path]:
    """
    **Extract stage:** parse ``yaml_path`` and write two CSVs into ``out_dir``.

    - ``ccdi_enum_properties_summary.csv`` — one row per property with enums (counts + joined list).
    - ``ccdi_enum_terms_for_verification.csv`` — one row per ``(prop_handle, enum_value)`` with
      empty ``term_value`` and empty discovery columns (filled during enrich).

    Returns:
        ``(path_to_summary_csv, path_to_query_csv)``.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "ccdi_enum_properties_summary.csv"
    query_csv = out_dir / "ccdi_enum_terms_for_verification.csv"

    parsed = parse_ccdi_yaml_props(yaml_path)
    summary_rows: list[dict] = []
    query_rows: list[dict] = []

    for prop_handle, desc, enum_values_deduped in parsed:
        summary_rows.append({
            "prop_handle": prop_handle,
            "description": desc,
            "enum_count": str(len(enum_values_deduped)),
            "enum_values": "|".join(enum_values_deduped),
        })
        for enum_value in enum_values_deduped:
            query_rows.append({
                "prop_handle": prop_handle,
                "enum_value": enum_value,
                "term_value": "",
                "description": desc,
                "model_handle": "",
                "version_string": "",
                "node_handle": "",
            })

    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["prop_handle", "description", "enum_count", "enum_values"]
        )
        w.writeheader()
        w.writerows(summary_rows)

    with open(query_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "prop_handle",
                "enum_value",
                "term_value",
                "description",
                "model_handle",
                "version_string",
                "node_handle",
            ],
        )
        w.writeheader()
        w.writerows(query_rows)

    print(f"Extract: {len(summary_rows)} properties → {summary_csv.name}")
    print(f"Extract: {len(query_rows)} query rows → {query_csv.name}")
    return summary_csv, query_csv


# --- enrich (APIClient) ---

RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _parse_semver_tuple(v: str) -> tuple[int, int, int]:
    """Parse ``major.minor.patch`` for comparing release version strings (internal helper)."""
    if not RELEASE_VERSION.match(v):
        return (0, 0, 0)
    parts = v.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2])) if len(parts) == 3 else (0, 0, 0)


def get_latest_version(client: APIClient, model_handle: str) -> str | None:
    """Prefer latest release from /versions; else /latest-version (e.g. pre-release)."""
    path = f"/model/{quote(model_handle, safe='')}/versions"
    response = client.get(path)
    if response.status_code != 200:
        return None
    versions = response.json()
    if not isinstance(versions, list):
        return None
    release = [v for v in versions if isinstance(v, str) and RELEASE_VERSION.match(v)]
    if release:
        return max(release, key=_parse_semver_tuple)
    latest_path = f"/model/{quote(model_handle, safe='')}/latest-version"
    latest_res = client.get(latest_path)
    if latest_res.status_code != 200:
        return None
    data = latest_res.json()
    if isinstance(data, dict):
        ver = data.get("version")
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    return None


def discover_ccdi_version(client: APIClient) -> str | None:
    """
    Resolve which **model version string** to use for all subsequent paths.

    Prefer ``GET /models`` entry with ``handle == CCDI`` and ``is_latest_version``; if missing,
    fall back to :func:`get_latest_version` (release semver first, else ``/latest-version``).
    """
    r = client.get("/models/", params={"limit": 500})
    if r.status_code == 200:
        models = r.json()
        if isinstance(models, list):
            for m in models:
                if not isinstance(m, dict):
                    continue
                if m.get("handle") == MODEL_HANDLE and m.get("is_latest_version"):
                    ver = m.get("version")
                    if isinstance(ver, str) and ver.strip():
                        return ver.strip()
    return get_latest_version(client, MODEL_HANDLE)


def build_prop_to_node_map(
    client: APIClient, version_string: str
) -> dict[str, str]:
    """
    Map each **property handle** to a **node handle** for STS path construction.

    Iterates every node under the model version and lists each node's properties. The **first**
    node that exposes a given property wins (same as legacy enrich scripts). Used so each
    ``prop_handle`` row knows which ``.../node/{nodeHandle}/property/{propHandle}/...`` to call.
    """
    nodes_path = f"/model/{quote(MODEL_HANDLE, safe='')}/version/{quote(version_string, safe='')}/nodes"
    nr = client.get(nodes_path, params={"limit": 500})
    if nr.status_code != 200:
        return {}
    nodes = nr.json()
    if not isinstance(nodes, list):
        return {}
    prop_to_node: dict[str, str] = {}
    for node in nodes:
        node_handle = node.get("handle") if isinstance(node, dict) else None
        if not node_handle:
            continue
        props_path = (
            f"/model/{quote(MODEL_HANDLE, safe='')}/version/{quote(version_string, safe='')}"
            f"/node/{quote(node_handle, safe='')}/properties"
        )
        pr = client.get(props_path, params={"limit": 500})
        if pr.status_code != 200:
            continue
        props = pr.json()
        if not isinstance(props, list):
            continue
        for prop in props:
            ph = prop.get("handle") if isinstance(prop, dict) else None
            if ph and ph not in prop_to_node:
                prop_to_node[ph] = node_handle
    return prop_to_node


def fetch_handle_to_value_all(
    client: APIClient,
    version_string: str,
    node_handle: str,
    prop_handle: str,
    *,
    page_size: int = 500,
) -> dict[str, str]:
    """
    GET .../terms with ``skip``/``limit`` pagination until all pages are read.

    A single page is insufficient for very large enums (e.g. ``laboratory_test_name``);
    handle ``T4`` must resolve to value ``T4 Stage Finding`` via the full list.
    """
    path = (
        f"/model/{quote(MODEL_HANDLE, safe='')}/version/{quote(version_string, safe='')}"
        f"/node/{quote(node_handle, safe='')}/property/{quote(prop_handle, safe='')}/terms"
    )
    out: dict[str, str] = {}
    skip = 0
    while True:
        r = client.get(path, params={"limit": page_size, "skip": skip})
        if r.status_code != 200:
            break
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        for item in data:
            if isinstance(item, dict):
                h = item.get("handle")
                v = item.get("value")
                if h is not None and v is not None:
                    out[str(h)] = str(v)
        if len(data) < page_size:
            break
        skip += page_size
    return out


def run_enrich(
    client: APIClient, query_csv: Path, out_dir: Path
) -> tuple[str, Path]:
    """
    **Enrich stage:** read the query CSV, call STS to fill discovery + ``term_value``, write enriched CSV.

    Steps:

    #. Discover ``version_string`` and build ``prop_to_node`` map.
    #. For each query row, if ``prop_handle`` is known, set ``model_handle``, ``version_string``,
       ``node_handle``.
    #. For each distinct ``(node_handle, prop_handle)``, fetch **all** terms via
       :func:`fetch_handle_to_value_all` (paginated).
    #. For each row, set ``term_value`` to the API **value** for the row's ``enum_value`` **handle**.

    Returns:
        ``(version_string, path_to_ccdi_enum_terms_for_verification_enriched.csv)``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_csv = out_dir / "ccdi_enum_terms_for_verification_enriched.csv"

    version_string = discover_ccdi_version(client)
    if not version_string:
        raise RuntimeError("Could not discover CCDI version from STS")

    print(f"Enrich: CCDI version {version_string!r}")

    prop_to_node = build_prop_to_node_map(client, version_string)
    print(f"Enrich: mapped {len(prop_to_node)} properties to nodes")

    rows: list[dict] = []
    with open(query_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if "term_value" not in fieldnames:
            idx = fieldnames.index("enum_value") if "enum_value" in fieldnames else 0
            fieldnames.insert(idx + 1, "term_value")
        for row in reader:
            if "term_value" not in row:
                row["term_value"] = ""
            ph = row.get("prop_handle", "")
            if ph in prop_to_node:
                row["model_handle"] = MODEL_HANDLE
                row["version_string"] = version_string
                row["node_handle"] = prop_to_node[ph]
            rows.append(row)

    seen_node_prop: set[tuple[str, str]] = set()
    handle_to_value_cache: dict[tuple[str, str], dict[str, str]] = {}

    for row in rows:
        nh = row.get("node_handle") or ""
        ph = row.get("prop_handle") or ""
        if not nh or not ph:
            continue
        key = (nh, ph)
        if key not in seen_node_prop:
            seen_node_prop.add(key)
            handle_to_value_cache[key] = fetch_handle_to_value_all(
                client, version_string, nh, ph
            )

    for row in rows:
        nh = row.get("node_handle") or ""
        ph = row.get("prop_handle") or ""
        handle = row.get("enum_value") or ""
        if (nh, ph) in handle_to_value_cache:
            row["term_value"] = handle_to_value_cache[(nh, ph)].get(handle, "")

    with open(enriched_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    filled_node = sum(1 for r in rows if r.get("node_handle"))
    filled_tv = sum(1 for r in rows if r.get("term_value"))
    print(
        f"Enrich: wrote {enriched_csv.name} ({filled_node}/{len(rows)} with node, "
        f"{filled_tv}/{len(rows)} with term_value)"
    )
    return version_string, enriched_csv


# --- verify ---

def verify_row(
    client: APIClient,
    model_handle: str,
    version_string: str,
    node_handle: str,
    prop_handle: str,
    term_value: str,
) -> tuple[int, bool, str]:
    """
    Perform a single **GET** for the term-by-value endpoint (shared by all commons pipelines).

    Calls::

        GET /model/{model_handle}/version/{version_string}/node/{node_handle}/
            property/{prop_handle}/term/{url_encoded_term_value}

    **Important:** ``term_value`` must be the Term **value** field returned by STS (what we store
    in enriched CSV ``term_value`` for CCDI-like models), not the YAML/API handle, unless the model's
    legacy script explicitly uses the handle (e.g. CDS ``enum_value`` only).

    Returns:
        ``(http_status, passed, notes)`` where ``passed`` means status 200 and the response JSON
        array contains at least one object with ``"value" == term_value``.
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


def run_verify(
    client: APIClient,
    enriched_csv: Path,
    out_dir: Path,
    base_url: str,
    *,
    limit: int = 0,
) -> tuple[Path, Path, int, int]:
    """
    **Verify stage:** HTTP-check each row of the enriched CSV and write pass/fail reports.

    Skips rows missing model path fields or with empty ``term_value`` (handle cannot be used in the
    URL for CCDI). Optional ``limit`` truncates **after** filtering (for smoke tests).

    Writes:

    - ``ccdi_term_endpoint_verification_report.csv`` — per-row status and notes.
    - ``ccdi_term_endpoint_verification_report.md`` — human-readable summary + failed row preview.

    Returns:
        ``(report_csv_path, report_md_path, passed_count, total_verified_rows)``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_csv = out_dir / "ccdi_term_endpoint_verification_report.csv"
    report_md = out_dir / "ccdi_term_endpoint_verification_report.md"

    with open(enriched_csv, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # CCDI: /term/{termValue} requires the Term *value* from /terms, never the YAML/API *handle*
    # (enum_value). Rows without a resolved term_value are skipped (no HTTP call).
    to_verify: list[dict] = []
    skipped_no_value = 0
    for row in rows:
        if not (row.get("model_handle") and row.get("version_string") and row.get("node_handle")):
            continue
        term_value_only = row.get("term_value") or ""
        if not str(term_value_only).strip():
            skipped_no_value += 1
            continue
        to_verify.append({**row, "_value_for_url": term_value_only})

    if limit and limit > 0:
        to_verify = to_verify[:limit]

    print(
        f"Verify: {len(to_verify)} rows to GET (from {len(rows)} enriched; "
        f"skipped {skipped_no_value} with empty term_value — handle cannot be used as URL param)"
    )

    report_rows: list[dict] = []
    for i, row in enumerate(to_verify):
        status, passed, notes = verify_row(
            client,
            row["model_handle"],
            row["version_string"],
            row["node_handle"],
            row["prop_handle"],
            row["_value_for_url"],
        )
        report_rows.append({
            "prop_handle": row["prop_handle"],
            "enum_value": row["enum_value"],
            "term_value": row.get("term_value", ""),
            "http_status": status,
            "passed": passed,
            "notes": notes,
        })
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(to_verify)} ...")

    with open(report_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "prop_handle",
                "enum_value",
                "term_value",
                "http_status",
                "passed",
                "notes",
            ],
        )
        w.writeheader()
        w.writerows(report_rows)

    passed_count = sum(1 for r in report_rows if r["passed"])
    failed = [r for r in report_rows if not r["passed"]]

    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# CCDI term endpoint verification report\n\n")
        f.write(
            f"**Base URL:** `{base_url}`\n\n"
            f"**Endpoint:** `GET {{base}}/model/{{modelHandle}}/version/{{versionString}}/"
            f"node/{{nodeHandle}}/property/{{propHandle}}/term/{{termValue}}`\n\n"
        )
        f.write(f"**Input:** `{enriched_csv.name}`\n\n")
        f.write(
            f"**Rows skipped (no API `term_value`):** {skipped_no_value} "
            "(YAML handle could not be resolved from paginated `/terms`; "
            "`/term/{termValue}` requires the Term **value**, not the handle.)\n\n"
        )
        f.write(f"**Rows verified (HTTP):** {len(report_rows)}\n\n")
        f.write(f"**Passed:** {passed_count}\n\n")
        f.write(f"**Failed:** {len(failed)}\n\n")
        if failed:
            f.write("## Failed rows (first 50)\n\n")
            f.write(
                "| prop_handle | enum_value (handle) | term_value | http_status | notes |\n"
            )
            f.write("|-------------|---------------------|------------|-------------|-------|\n")
            for r in failed[:50]:
                ev = r.get("enum_value", "")
                ev = (ev[:25] + "…") if len(ev) > 25 else ev
                tv = r.get("term_value", "")
                tv = (tv[:25] + "…") if len(tv) > 25 else tv
                notes = str(r.get("notes", ""))[:60]
                f.write(
                    f"| {r['prop_handle']} | {ev} | {tv} | {r['http_status']} | {notes} |\n"
                )
            if len(failed) > 50:
                f.write(
                    f"\n... and {len(failed) - 50} more. See `{report_csv.name}` for full list.\n"
                )
        f.write(f"\n**Full results:** `{report_csv.name}`\n")

    print(f"Verify: passed {passed_count}/{len(report_rows)} → {report_csv.name}, {report_md.name}")
    return report_csv, report_md, passed_count, len(report_rows)


def main() -> None:
    """
    CLI entrypoint: run extract → enrich → verify unless ``--skip-extract`` / ``--skip-enrich``.

    Exit code **1** if any verified row fails (unless ``--warn-only``). Uses ``STS_BASE_URL`` or
    ``--base-url`` (must include ``/v2``).
    """
    import argparse

    from .config import DEFAULT_STS_BASE_URL, sts_base_url

    parser = argparse.ArgumentParser(
        description=(
            "CCDI term-by-value pipeline: extract from YAML, enrich via STS, verify /term/{value}, "
            "write CSV + Markdown under reports/term_value/CCDI/"
        )
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help=f"Path to ccdi-model-props.yml (default: {default_yaml_path()})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=f"Output directory for all artifacts (default: {default_report_dir()})",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"STS base URL including /v2 (default: STS_BASE_URL or {DEFAULT_STS_BASE_URL})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max rows to verify (0 = all). Extract/enrich always process full YAML.",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extract; expect ccdi_enum_terms_for_verification.csv in out-dir",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrich; expect ccdi_enum_terms_for_verification_enriched.csv in out-dir",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Exit 0 even if some rows fail (still writes reports; use when refreshing artifacts)",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml) if args.yaml else default_yaml_path()
    out_dir = Path(args.out_dir) if args.out_dir else default_report_dir()
    base_url = (args.base_url or sts_base_url()).rstrip("/")

    out_dir.mkdir(parents=True, exist_ok=True)
    query_csv = out_dir / "ccdi_enum_terms_for_verification.csv"
    enriched_csv = out_dir / "ccdi_enum_terms_for_verification_enriched.csv"

    if not args.skip_extract:
        run_extract(yaml_path, out_dir)
    elif not query_csv.exists():
        print(f"--skip-extract but missing {query_csv}", file=sys.stderr)
        sys.exit(2)

    client = APIClient(base_url)

    if not args.skip_enrich:
        _, enriched_path = run_enrich(client, query_csv, out_dir)
        enriched_csv = enriched_path
    elif not enriched_csv.exists():
        print(f"--skip-enrich but missing {enriched_csv}", file=sys.stderr)
        sys.exit(2)

    _, _, passed, total = run_verify(
        client, enriched_csv, out_dir, base_url, limit=args.limit
    )
    if passed < total and not args.warn_only:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
