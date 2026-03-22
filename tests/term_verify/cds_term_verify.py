"""
CDS term endpoint verification driven by vendored ``cds-model-props-4.yml``.

**Unlike CCDI/C3DC/ICDC**, CDS legacy scripts do **not** call ``GET .../terms`` to map handle→value.
The YAML ``enum_value`` is already the string used in the term URL and in the JSON ``value`` check.

**Pipeline**

1. **extract** — Strict ``Enum:`` / ``- item`` line parse (``extract_cds_enum_properties.py``).
2. **enrich** — Only fills ``model_handle``, ``version_string``, ``node_handle`` from STS discovery.
3. **verify** — Passes ``enum_value`` to :func:`ccdi_term_verify.verify_row` as ``term_value``.

CLI: ``sts-cds-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote

from ccdi_term_verify import verify_row
from sts_test_framework.client import APIClient
from sts_test_framework.discover import get_latest_version

MODEL_HANDLE = "CDS"


def _repo_root() -> Path:
    """Project root (parent of ``src/``)."""
    return Path(__file__).resolve().parent.parent.parent


def default_yaml_path() -> Path:
    """Default vendored CDS YAML (override with ``--yaml``)."""
    return _repo_root() / "data" / "data-models-yaml" / "cds-model-props-4.yml"


def default_report_dir() -> Path:
    """Default output under ``reports/term_value/CDS/``."""
    return _repo_root() / "reports" / "term_value" / "CDS"


# --- extract (matches extract_cds_enum_properties.py) ---

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER = "    Enum:"
ENUM_ITEM_PATTERN = re.compile(r"^    -\s+(.*)$")


def parse_cds_yaml_props(path: Path) -> list[tuple[str, str, list[str]]]:
    """
    CDS-specific line parser: ``Enum:`` must be exactly four spaces + ``Enum:``; items are ``    -``.

    Returned enum strings are **already** the values used in ``/term/{...}`` (after YAML unquoting).
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
                        item_match = ENUM_ITEM_PATTERN.match(item_line)
                        if item_match:
                            val = item_match.group(1).strip()
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1].replace('\\"', '"').replace("\\'", "'")
                            if val:
                                enum_values.append(val)
                            i += 1
                        else:
                            break
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
    """Write ``cds_enum_properties_summary.csv`` and ``cds_enum_terms_for_verification.csv`` (no ``term_value`` column)."""
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML not found: {yaml_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "cds_enum_properties_summary.csv"
    query_csv = out_dir / "cds_enum_terms_for_verification.csv"

    parsed = parse_cds_yaml_props(yaml_path)
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


def discover_cds_version(client: APIClient) -> str | None:
    """Latest CDS version from ``/models`` or :func:`get_latest_version`."""
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
    """Property handle → first CDS node that exposes it (for path construction only)."""
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


def run_enrich(client: APIClient, query_csv: Path, out_dir: Path) -> tuple[str, Path]:
    """
    Add STS discovery fields only (no ``/terms`` calls). Writes ``cds_enum_terms_for_verification_enriched.csv``.

    Returns:
        ``(version_string, enriched_csv_path)``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_csv = out_dir / "cds_enum_terms_for_verification_enriched.csv"

    version_string = discover_cds_version(client)
    if not version_string:
        raise RuntimeError("Could not discover CDS version from STS")

    print(f"Enrich: CDS version {version_string!r}")

    prop_to_node = build_prop_to_node_map(client, version_string)
    print(f"Enrich: mapped {len(prop_to_node)} properties to nodes")

    rows: list[dict] = []
    fieldnames = [
        "prop_handle",
        "enum_value",
        "description",
        "model_handle",
        "version_string",
        "node_handle",
    ]
    with open(query_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ph = row.get("prop_handle", "")
            if ph in prop_to_node:
                row["model_handle"] = MODEL_HANDLE
                row["version_string"] = version_string
                row["node_handle"] = prop_to_node[ph]
            rows.append(row)

    with open(enriched_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    filled = sum(1 for r in rows if r.get("node_handle"))
    print(f"Enrich: wrote {enriched_csv.name} ({filled}/{len(rows)} rows with model/version/node)")
    return version_string, enriched_csv


def run_verify(
    client: APIClient,
    enriched_csv: Path,
    out_dir: Path,
    base_url: str,
    *,
    limit: int = 0,
) -> tuple[Path, Path, int, int]:
    """
    For each row with model path filled, ``GET`` using **enum_value** as the URL segment (legacy CDS).

    Report columns: ``prop_handle``, ``enum_value``, ``http_status``, ``passed``, ``notes`` (no separate
    ``term_value`` column — enum **is** the value).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_csv = out_dir / "cds_term_endpoint_verification_report.csv"
    report_md = out_dir / "cds_term_endpoint_verification_report.md"

    with open(enriched_csv, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    to_verify: list[dict] = []
    for row in rows:
        if not (
            row.get("model_handle")
            and row.get("version_string")
            and row.get("node_handle")
        ):
            continue
        to_verify.append(row)

    if limit and limit > 0:
        to_verify = to_verify[:limit]

    print(
        f"Verify: {len(to_verify)} rows to GET (from {len(rows)} enriched; "
        "URL uses YAML enum_value, same as legacy verify_term_endpoint_from_sheet.py)"
    )

    report_rows: list[dict] = []
    for i, row in enumerate(to_verify):
        enum_value = row.get("enum_value") or ""
        status, passed, notes = verify_row(
            client,
            row["model_handle"],
            row["version_string"],
            row["node_handle"],
            row["prop_handle"],
            enum_value,
        )
        report_rows.append({
            "prop_handle": row["prop_handle"],
            "enum_value": enum_value,
            "http_status": status,
            "passed": passed,
            "notes": notes,
        })
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(to_verify)} ...")

    with open(report_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["prop_handle", "enum_value", "http_status", "passed", "notes"],
        )
        w.writeheader()
        w.writerows(report_rows)

    passed_count = sum(1 for r in report_rows if r["passed"])
    failed = [r for r in report_rows if not r["passed"]]

    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# CDS term endpoint verification report\n\n")
        f.write(
            f"**Base URL:** `{base_url}`\n\n"
            f"**Endpoint:** `GET {{base}}/model/{{modelHandle}}/version/{{versionString}}/"
            f"node/{{nodeHandle}}/property/{{propHandle}}/term/{{termValue}}`\n\n"
        )
        f.write(
            f"**Input:** `{enriched_csv.name}`\n\n"
            "**Note:** `termValue` in the URL is the YAML **enum_value** (CDS legacy behavior; "
            "no `/terms` handle→value enrichment).\n\n"
        )
        f.write(f"**Rows verified:** {len(report_rows)}\n\n")
        f.write(f"**Passed:** {passed_count}\n\n")
        f.write(f"**Failed:** {len(failed)}\n\n")
        if failed:
            f.write("## Failed rows (first 50)\n\n")
            f.write("| prop_handle | enum_value | http_status | notes |\n")
            f.write("|-------------|------------|-------------|-------|\n")
            for r in failed[:50]:
                ev = r.get("enum_value", "")
                ev = (ev[:40] + "…") if len(ev) > 40 else ev
                notes = str(r.get("notes", ""))[:80]
                f.write(
                    f"| {r['prop_handle']} | {ev} | {r['http_status']} | {notes} |\n"
                )
            if len(failed) > 50:
                f.write(
                    f"\n... and {len(failed) - 50} more. See `{report_csv.name}` for full list.\n"
                )
        f.write(f"\n**Full results:** `{report_csv.name}`\n")

    print(f"Verify: passed {passed_count}/{len(report_rows)} → {report_csv.name}, {report_md.name}")
    return report_csv, report_md, passed_count, len(report_rows)


def main() -> None:
    """CLI for ``sts-cds-term-verify`` (``--yaml``, ``--out-dir``, ``--skip-*``, ``--warn-only``, etc.)."""
    import argparse
    from sts_test_framework.config import DEFAULT_STS_BASE_URL, sts_base_url

    parser = argparse.ArgumentParser(
        description=(
            "CDS term pipeline: extract from YAML, enrich (discovery only), verify /term/{enum_value}, "
            "write CSV + Markdown under reports/term_value/CDS/"
        )
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=None,
        help=f"Path to cds-model-props-4.yml (default: {default_yaml_path()})",
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
        help="Skip extract; expect cds_enum_terms_for_verification.csv in out-dir",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrich; expect cds_enum_terms_for_verification_enriched.csv in out-dir",
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
    query_csv = out_dir / "cds_enum_terms_for_verification.csv"
    enriched_csv = out_dir / "cds_enum_terms_for_verification_enriched.csv"

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
