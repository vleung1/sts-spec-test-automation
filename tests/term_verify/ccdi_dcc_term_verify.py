"""
CCDI-DCC term-by-value verification driven by vendored ``ccdi-dcc-model-props-3.yml``.

**Ports** (under ``mdb/termValue_verification_scripts/``):

- **extract** — Inline enums plus optional **http(s) URLs** pointing at remote PropDefinitions YAML
  (CBIIT); values are merged into the same enum list as local items.
- **enrich** — ``GET /models`` may return handle ``CCDI-DCC`` or ``CCDI_DCC``; paginated
  ``/terms`` fills ``term_value`` (handle → API value).
- **verify** — Uses :func:`verify_row`; URL value = ``(term_value or '') or (enum_value or '')``
  per legacy sheet (non-empty after ``strip``). Some YAML enum values are not in the STS DB;
  :data:`KNOWN_MISSING_IN_STS_DB` lists ``(prop_handle, enum_value)`` pairs that still appear as
  failed rows in reports but do not cause a non-zero exit unless other rows fail.

CLI: ``sts-ccdi-dcc-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import csv
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from ccdi_term_verify import strip_inline_yaml_comment, verify_row
from sts_test_framework.client import APIClient
from sts_test_framework.discover import get_latest_version

# Preferred display name for reports; API may return CCDI-DCC or CCDI_DCC
MODEL_LABEL = "CCDI-DCC"

# Enum values present in the model YAML (incl. remote-expanded lists) that are not loaded in the
# STS graph DB. Rows still appear as failed in CSV/MD; process exit code ignores only these pairs.
KNOWN_MISSING_IN_STS_DB: frozenset[tuple[str, str]] = frozenset(
    {
        ("file_type", "cnn"),
        ("file_type", "cnr"),
        ("file_type", "mzid"),
        ("file_type", "mzml"),
        ("file_type", "parquet"),
        ("file_type", "psm"),
        ("file_type", "sf"),
        ("file_type", "selfsm"),
        ("library_strategy", "CITE-Seq"),
        ("library_source_molecule", "Not Applicable"),
        ("diagnosis", "Chondroma, NOS"),
        ("submitted_diagnosis", "Chondroma, NOS"),
    }
)


def _pair_known_missing(prop_handle: str, enum_value: str) -> bool:
    return (prop_handle, enum_value) in KNOWN_MISSING_IN_STS_DB


def _repo_root() -> Path:
    """Project root (parent of ``src/``)."""
    return Path(__file__).resolve().parent.parent.parent


def default_yaml_path() -> Path:
    """Default vendored CCDI-DCC YAML (override with ``--yaml``)."""
    return _repo_root() / "data" / "data-models-yaml" / "ccdi-dcc-model-props-3.yml"


def default_report_dir() -> Path:
    """Default directory ``reports/term_value/CCDI-DCC/`` for all pipeline artifacts."""
    return _repo_root() / "reports" / "term_value" / "CCDI-DCC"


# --- extract (matches extract_ccdi_dcc_enum_properties.py) ---

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER_PATTERN = re.compile(r"^\s{4,}Enum\s*:")
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


def clean_enum_value(val: str) -> str:
    """
    Normalize one enum list item: drop YAML ``#`` comment suffix, then strip YAML quotes.

    - **Quoted** values (start with ``"`` or ``'``): use :func:`strip_inline_yaml_comment` like CCDI
      so ``"Data Submitter" # these? 01/26/2022`` becomes ``Data Submitter``.
    - **Unquoted** values: strip only `` #`` (space + hash) so ``https://host/path#frag`` is not
      truncated at the URL fragment ``#``.
    """
    val = val.strip()
    if val.startswith('"') or val.startswith("'"):
        val = strip_inline_yaml_comment(val)
    else:
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


def is_enum_url(s: str) -> bool:
    """Return True if ``s`` is an http(s) URL (enum expands to remote YAML list)."""
    t = s.strip()
    return t.startswith("http://") or t.startswith("https://")


def _parse_remote_prop_definitions_yaml(body: str) -> list[str]:
    """
    Parse a fetched remote YAML body for CBIIT-style ``PropDefinitions`` list-of-values.

    Heuristic: after ``PropDefinitions:``, walk keys and collect ``- item`` lines under the first
    key block; each item is normalized with :func:`clean_enum_value`.
    """
    values: list[str] = []
    lines = body.splitlines()
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("PropDefinitions:"):
            continue
        if (
            stripped
            and not stripped.startswith("-")
            and stripped.endswith(":")
            and " " not in stripped.rstrip(":")
        ):
            in_list = True
            continue
        if in_list and stripped.startswith("-"):
            rest = stripped[1:].strip()
            s = clean_enum_value(rest)
            if s:
                values.append(s)
    seen: set[str] = set()
    deduped = [v for v in values if v not in seen and not seen.add(v)]
    return deduped


def fetch_enum_values_from_url(url: str, cache: dict[str, list[str]]) -> list[str]:
    """
    HTTP GET ``url``, parse enum list via :func:`_parse_remote_prop_definitions_yaml`, with caching.

    On failure, prints a warning and returns ``[]`` (cache stores empty list to avoid retries).
    """
    if url in cache:
        return cache[url]
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/x-yaml, text/plain"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"Warning: could not fetch enum URL {url!r}: {e}")
        cache[url] = []
        return []
    values = _parse_remote_prop_definitions_yaml(body)
    if not values:
        print(f"Warning: no enum values parsed from {url!r}")
    cache[url] = values
    return values


def parse_ccdi_dcc_yaml_props(
    path: Path, url_cache: dict[str, list[str]] | None = None
) -> list[tuple[str, str, list[str]]]:
    """
    Line-parse main CCDI-DCC YAML; for each enum item, either append a literal value or **expand**
    a remote URL into many values via :func:`fetch_enum_values_from_url`.

    Args:
        path: Main property YAML file.
        url_cache: Optional shared cache for remote fetches (same URL fetched once per run).

    Returns:
        ``(prop_handle, description, enum_values)`` tuples with deduped enum lists.
    """
    cache = url_cache if url_cache is not None else {}
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
                if ENUM_HEADER_PATTERN.match(cur):
                    i += 1
                    while i < len(lines):
                        item_line = lines[i]
                        if ENUM_END_PATTERN.match(item_line):
                            break
                        item_match = ENUM_ITEM_PATTERN.match(item_line)
                        if item_match:
                            val = clean_enum_value(item_match.group(1))
                            if val:
                                if is_enum_url(val):
                                    enum_values.extend(fetch_enum_values_from_url(val, cache))
                                else:
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
    """Write ``ccdi_dcc_enum_properties_summary.csv`` and ``ccdi_dcc_enum_terms_for_verification.csv``."""
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "ccdi_dcc_enum_properties_summary.csv"
    query_csv = out_dir / "ccdi_dcc_enum_terms_for_verification.csv"

    url_cache: dict[str, list[str]] = {}
    parsed = parse_ccdi_dcc_yaml_props(yaml_path, url_cache)
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


def discover_ccdi_dcc_model_and_version(client: APIClient) -> tuple[str, str] | None:
    """
    Return ``(model_handle, version_string)`` for STS paths.

    Prefer ``GET /models`` with ``is_latest_version`` and handle ``CCDI-DCC`` or ``CCDI_DCC``;
    otherwise try :func:`get_latest_version` for each handle.
    """
    r = client.get("/models/", params={"limit": 500})
    if r.status_code == 200:
        models = r.json()
        if isinstance(models, list):
            for m in models:
                if not isinstance(m, dict):
                    continue
                h = m.get("handle")
                if h in ("CCDI-DCC", "CCDI_DCC") and m.get("is_latest_version"):
                    ver = m.get("version")
                    if isinstance(ver, str) and ver.strip():
                        return (str(h), ver.strip())
    for handle in ("CCDI-DCC", "CCDI_DCC"):
        v = get_latest_version(client, handle)
        if v:
            return (handle, v)
    return None


def build_prop_to_node_map(
    client: APIClient, model_handle: str, version_string: str
) -> dict[str, str]:
    """Map property handle → first node (same semantics as CCDI, but parameterized ``model_handle``)."""
    nodes_path = (
        f"/model/{quote(model_handle, safe='')}/version/{quote(version_string, safe='')}/nodes"
    )
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
            f"/model/{quote(model_handle, safe='')}/version/{quote(version_string, safe='')}"
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
    model_handle: str,
    version_string: str,
    node_handle: str,
    prop_handle: str,
    *,
    page_size: int = 500,
) -> dict[str, str]:
    """Paginated ``GET .../terms`` for the given model handle (not a module constant)."""
    path = (
        f"/model/{quote(model_handle, safe='')}/version/{quote(version_string, safe='')}"
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


def run_enrich(client: APIClient, query_csv: Path, out_dir: Path) -> tuple[str, str, Path]:
    """
    Discover model + version, map properties to nodes, resolve ``term_value`` from ``/terms``.

    Returns:
        ``(model_handle, version_string, enriched_csv_path)`` — model handle is the STS string
        (``CCDI-DCC`` or ``CCDI_DCC``).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_csv = out_dir / "ccdi_dcc_enum_terms_for_verification_enriched.csv"

    discovered = discover_ccdi_dcc_model_and_version(client)
    if not discovered:
        raise RuntimeError("Could not discover CCDI-DCC model handle/version from STS")
    model_handle, version_string = discovered

    print(f"Enrich: {MODEL_LABEL} version {version_string!r} (handle: {model_handle!r})")

    prop_to_node = build_prop_to_node_map(client, model_handle, version_string)
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
                row["model_handle"] = model_handle
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
                client, model_handle, version_string, nh, ph
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
    return model_handle, version_string, enriched_csv


def run_verify(
    client: APIClient,
    enriched_csv: Path,
    out_dir: Path,
    base_url: str,
    *,
    limit: int = 0,
) -> tuple[Path, Path, int, int, int]:
    """
    Call :func:`verify_row` with legacy URL value: ``(term_value or enum_value)`` after empty check.

    Writes ``ccdi_dcc_term_endpoint_verification_report.{csv,md}``.

    Returns:
        ``(report_csv, report_md, passed_count, total_rows, unexpected_failure_count)``.
        ``unexpected_failure_count`` is failed rows whose ``(prop_handle, enum_value)`` is not in
        :data:`KNOWN_MISSING_IN_STS_DB` (used for process exit code in :func:`main`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_csv = out_dir / "ccdi_dcc_term_endpoint_verification_report.csv"
    report_md = out_dir / "ccdi_dcc_term_endpoint_verification_report.md"

    with open(enriched_csv, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    to_verify: list[dict] = []
    skipped_no_url_value = 0
    for row in rows:
        if not (
            row.get("model_handle")
            and row.get("version_string")
            and row.get("node_handle")
        ):
            continue
        # Match verify_ccdi_dcc_term_endpoint_from_sheet.py: prefer term_value, else enum_value
        value_for_url = (row.get("term_value") or "") or (row.get("enum_value") or "")
        if not str(value_for_url).strip():
            skipped_no_url_value += 1
            continue
        to_verify.append({**row, "_value_for_url": value_for_url})

    if limit and limit > 0:
        to_verify = to_verify[:limit]

    print(
        f"Verify: {len(to_verify)} rows to GET (from {len(rows)} enriched; "
        f"skipped {skipped_no_url_value} empty after (term_value or enum_value); "
        f"legacy: `(term_value or '') or (enum_value or '')` then `.strip()` check)"
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
    failed_allowlisted = [
        r
        for r in failed
        if _pair_known_missing(str(r["prop_handle"]), str(r["enum_value"]))
    ]
    unexpected_failure_count = len(failed) - len(failed_allowlisted)

    with open(report_md, "w", encoding="utf-8") as f:
        f.write(f"# {MODEL_LABEL} term endpoint verification report\n\n")
        f.write(
            f"**Base URL:** `{base_url}`\n\n"
            f"**Endpoint:** `GET {{base}}/model/{{modelHandle}}/version/{{versionString}}/"
            f"node/{{nodeHandle}}/property/{{propHandle}}/term/{{termValue}}`\n\n"
        )
        f.write(f"**Input:** `{enriched_csv.name}`\n\n")
        f.write(
            f"**Rows skipped (neither `term_value` nor `enum_value` usable):** {skipped_no_url_value}\n\n"
        )
        f.write(
            "**URL term:** `(term_value or '') or (enum_value or '')` must be non-empty after strip "
            "(legacy). Prefer API `term_value` from `/terms` when enrich resolved the handle.\n\n"
        )
        f.write(f"**Rows verified (HTTP):** {len(report_rows)}\n\n")
        f.write(f"**Passed:** {passed_count}\n\n")
        f.write(f"**Failed:** {len(failed)}\n\n")
        f.write(
            "**Exit code (without `--warn-only`):** process exits **1** only if there is at least "
            "one failed row **not** listed under [Known missing in STS DB](#known-missing-in-sts-db) "
            "below. Per-row `passed` in the CSV is unchanged.\n\n"
        )
        f.write(
            f"**Failed rows matching known-missing allowlist (exit ignored):** "
            f"{len(failed_allowlisted)}\n\n"
        )
        f.write(
            f"**Failed rows not allowlisted (would fail the run):** {unexpected_failure_count}\n\n"
        )
        f.write("## Known missing in STS DB\n\n")
        f.write(
            "These `(prop_handle, enum_value)` pairs are in the model enum but confirmed absent "
            "from the STS DB; they remain `passed=False` in the CSV for visibility.\n\n"
        )
        f.write("| prop_handle | enum_value |\n|-------------|------------|\n")
        for ph, ev in sorted(KNOWN_MISSING_IN_STS_DB):
            f.write(f"| {ph} | {ev} |\n")
        f.write("\n")
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

    print(
        f"Verify: passed {passed_count}/{len(report_rows)} "
        f"(allowlisted failures: {len(failed_allowlisted)}, "
        f"unexpected failures: {unexpected_failure_count}) "
        f"→ {report_csv.name}, {report_md.name}"
    )
    return report_csv, report_md, passed_count, len(report_rows), unexpected_failure_count


def main() -> None:
    """CLI for ``sts-ccdi-dcc-term-verify`` (extract may require network for remote enum URLs)."""
    import argparse
    from sts_test_framework.config import DEFAULT_STS_BASE_URL, sts_base_url

    parser = argparse.ArgumentParser(
        description=(
            f"{MODEL_LABEL} term pipeline: extract from YAML (optional remote enum URLs), "
            "enrich via STS, verify /term/{{value}}, write CSV + Markdown under "
            "reports/term_value/CCDI-DCC/"
        )
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help=f"Path to ccdi-dcc-model-props-3.yml (default: {default_yaml_path()})",
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
        help="Skip extract; expect ccdi_dcc_enum_terms_for_verification.csv in out-dir",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrich; expect ccdi_dcc_enum_terms_for_verification_enriched.csv in out-dir",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Exit 0 even if some rows fail, including non-allowlisted failures (still writes reports)",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml) if args.yaml else default_yaml_path()
    out_dir = Path(args.out_dir) if args.out_dir else default_report_dir()
    base_url = (
        args.base_url or sts_base_url()
    ).rstrip("/")

    out_dir.mkdir(parents=True, exist_ok=True)
    query_csv = out_dir / "ccdi_dcc_enum_terms_for_verification.csv"
    enriched_csv = out_dir / "ccdi_dcc_enum_terms_for_verification_enriched.csv"

    if not args.skip_extract:
        run_extract(yaml_path, out_dir)
    elif not query_csv.exists():
        print(f"--skip-extract but missing {query_csv}", file=sys.stderr)
        sys.exit(2)

    client = APIClient(base_url)

    if not args.skip_enrich:
        _, _, enriched_path = run_enrich(client, query_csv, out_dir)
        enriched_csv = enriched_path
    elif not enriched_csv.exists():
        print(f"--skip-enrich but missing {enriched_csv}", file=sys.stderr)
        sys.exit(2)

    _, _, passed, total, unexpected_failures = run_verify(
        client, enriched_csv, out_dir, base_url, limit=args.limit
    )
    if args.warn_only:
        sys.exit(0)
    if unexpected_failures > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
