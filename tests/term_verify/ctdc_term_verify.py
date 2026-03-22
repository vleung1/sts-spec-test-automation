"""
CTDC term-by-value verification pipeline driven by vendored ``ctdc_model_properties_file-2.yaml``.

**Behavior** is the same as :mod:`c3dc_term_verify` (same extract/enrich/verify structure and
``strip_inline_yaml_comment`` + ``_strip_quotes`` parsing), but with ``MODEL_HANDLE == "CTDC"`` and
CTDC-specific CSV filenames under ``reports/term_value/CTDC/``.

CLI: ``sts-ctdc-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote

from ccdi_term_verify import strip_inline_yaml_comment, verify_row
from sts_test_framework.client import APIClient
from sts_test_framework.discover import get_latest_version

MODEL_HANDLE = "CTDC"


def _repo_root() -> Path:
    """Project root (parent of ``src/``)."""
    return Path(__file__).resolve().parent.parent.parent


def default_yaml_path() -> Path:
    """Default vendored CTDC YAML (override with ``--yaml``)."""
    #return _repo_root() / "data" / "data-models-yaml" / "ctdc_model_properties_file-2.yaml"
    return _repo_root() / "data" / "data-models-yaml" / "ctdc_model_properties_file-v1.22.1.yaml"



def default_report_dir() -> Path:
    """Default output directory for pipeline artifacts (override with ``--out-dir``)."""
    return _repo_root() / "reports" / "term_value" / "CTDC"


# --- extract (matches extract_ctdc_enum_properties.py + comment strip) ---

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER_PATTERN = re.compile(r"^\s{4,}Enum\s*:")
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


def _strip_quotes(val: str) -> str:
    """Remove surrounding quotes from a YAML list item after comment stripping."""
    val = val.strip()
    if len(val) >= 2:
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1].replace('\\"', '"').replace("\\'", "'")
    return val.strip()


def parse_ctdc_yaml_props(path: Path) -> list[tuple[str, str, list[str]]]:
    """
    Line-parse CTDC property YAML into ``(prop_handle, description, enum_handles)`` (see C3DC).
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
                if ENUM_HEADER_PATTERN.match(cur):
                    i += 1
                    while i < len(lines):
                        item_line = lines[i]
                        if ENUM_END_PATTERN.match(item_line):
                            break
                        item_match = ENUM_ITEM_PATTERN.match(item_line)
                        if item_match:
                            raw = strip_inline_yaml_comment(item_match.group(1).strip())
                            val = _strip_quotes(raw)
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
    """Write ``ctdc_enum_*.csv`` summary + query files; returns ``(summary_path, query_path)``."""
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "ctdc_enum_properties_summary.csv"
    query_csv = out_dir / "ctdc_enum_terms_for_verification.csv"

    parsed = parse_ctdc_yaml_props(yaml_path)
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


def discover_ctdc_version(client: APIClient) -> str | None:
    """Resolve latest CTDC version string from ``/models`` or :func:`get_latest_version`."""
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


def build_prop_to_node_map(client: APIClient, version_string: str) -> dict[str, str]:
    """Map each property handle to the first CTDC node that exposes it."""
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
    """Paginated ``GET .../terms`` for one property; returns handle → display value."""
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


def run_enrich(client: APIClient, query_csv: Path, out_dir: Path) -> tuple[str, Path]:
    """
    Discover version + nodes, resolve ``term_value`` via paginated ``/terms``, write enriched CSV.

    Returns:
        ``(version_string, enriched_csv_path)``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_csv = out_dir / "ctdc_enum_terms_for_verification_enriched.csv"

    version_string = discover_ctdc_version(client)
    if not version_string:
        raise RuntimeError("Could not discover CTDC version from STS")

    print(f"Enrich: CTDC version {version_string!r}")

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


def run_verify(
    client: APIClient,
    enriched_csv: Path,
    out_dir: Path,
    base_url: str,
    *,
    limit: int = 0,
) -> tuple[Path, Path, int, int]:
    """HTTP-verify each non-empty ``term_value`` row; emit CTDC CSV + Markdown reports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report_csv = out_dir / "ctdc_term_endpoint_verification_report.csv"
    report_md = out_dir / "ctdc_term_endpoint_verification_report.md"

    with open(enriched_csv, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

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
        f.write("# CTDC term endpoint verification report\n\n")
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
    """CLI for ``sts-ctdc-term-verify`` — same flags as :func:`ccdi_term_verify.main`."""
    import argparse
    from sts_test_framework.config import DEFAULT_STS_BASE_URL, sts_base_url

    parser = argparse.ArgumentParser(
        description=(
            "CTDC term-by-value pipeline: extract from YAML, enrich via STS, verify /term/{value}, "
            "write CSV + Markdown under reports/term_value/CTDC/"
        )
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help=f"Path to CTDC properties YAML (default: {default_yaml_path().name})",
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
        help="Skip extract; expect ctdc_enum_terms_for_verification.csv in out-dir",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrich; expect ctdc_enum_terms_for_verification_enriched.csv in out-dir",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Exit 0 even if some rows fail (still writes reports)",
    )
    args = parser.parse_args()

    yaml_path = Path(args.yaml) if args.yaml else default_yaml_path()
    out_dir = Path(args.out_dir) if args.out_dir else default_report_dir()
    base_url = (
        args.base_url or sts_base_url()
    ).rstrip("/")

    out_dir.mkdir(parents=True, exist_ok=True)
    query_csv = out_dir / "ctdc_enum_terms_for_verification.csv"
    enriched_csv = out_dir / "ctdc_enum_terms_for_verification_enriched.csv"

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
