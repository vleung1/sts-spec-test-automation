"""
Base class for all term-by-value verification pipelines.

Each data-model (CCDI, C3DC, CDS, CTDC, ICDC, CCDI-DCC) subclasses
:class:`TermVerifyPipeline`, overriding only the YAML parsing and any
model-specific behavior (e.g. CDS skips handle-to-value enrichment,
CCDI-DCC has remote URL expansion and a known-missing allowlist).

The three stages — extract, enrich, verify — plus the CLI ``main()`` are
implemented once here.  Subclasses set class attributes and override
:meth:`parse_yaml`.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from urllib.parse import quote

from .client import APIClient
from .config import DEFAULT_STS_BASE_URL, project_root, sts_base_url
from .discover import get_latest_version
from .term_verify_utils import verify_row


class TermVerifyPipeline:
    """Abstract base for model-specific term verification pipelines."""

    # --- subclass must set these ---
    model_handle: str = ""
    csv_prefix: str = ""
    default_yaml_filename: str = ""
    report_subdir: str = ""

    # --- behavioral flags (override in subclass if needed) ---
    needs_handle_to_value: bool = True
    query_csv_has_term_value: bool = True
    report_csv_has_term_value: bool = True

    # ------------------------------------------------------------------ paths

    def _repo_root(self) -> Path:
        return project_root()

    def default_yaml_path(self) -> Path:
        return self._repo_root() / "data" / "data-models-yaml" / self.default_yaml_filename

    def default_report_dir(self) -> Path:
        return self._repo_root() / "reports" / "term_value" / self.report_subdir

    # --------------------------------------------------------------- abstract

    def parse_yaml(self, path: Path) -> list[tuple[str, str, list[str]]]:
        """
        Walk the model property YAML and return ``(prop_handle, description, enum_values)``
        per property that has an ``Enum`` block. Enum values are deduped in file order.
        """
        raise NotImplementedError

    # ---------------------------------------------------------------- extract

    def run_extract(self, yaml_path: Path, out_dir: Path) -> tuple[Path, Path]:
        if not yaml_path.exists():
            raise FileNotFoundError(f"YAML not found: {yaml_path}")

        out_dir.mkdir(parents=True, exist_ok=True)
        summary_csv = out_dir / f"{self.csv_prefix}_enum_properties_summary.csv"
        query_csv = out_dir / f"{self.csv_prefix}_enum_terms_for_verification.csv"

        parsed = self.parse_yaml(yaml_path)
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
                row: dict[str, str] = {
                    "prop_handle": prop_handle,
                    "enum_value": enum_value,
                    "description": desc,
                    "model_handle": "",
                    "version_string": "",
                    "node_handle": "",
                }
                if self.query_csv_has_term_value:
                    row["term_value"] = ""
                query_rows.append(row)

        with open(summary_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f, fieldnames=["prop_handle", "description", "enum_count", "enum_values"]
            )
            w.writeheader()
            w.writerows(summary_rows)

        query_fieldnames = ["prop_handle", "enum_value"]
        if self.query_csv_has_term_value:
            query_fieldnames.append("term_value")
        query_fieldnames.extend(["description", "model_handle", "version_string", "node_handle"])

        with open(query_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=query_fieldnames)
            w.writeheader()
            w.writerows(query_rows)

        print(f"Extract: {len(summary_rows)} properties \u2192 {summary_csv.name}")
        print(f"Extract: {len(query_rows)} query rows \u2192 {query_csv.name}")
        return summary_csv, query_csv

    # ------------------------------------------------------------- discovery

    def discover_version(self, client: APIClient) -> str | None:
        """Resolve the latest model version string from ``GET /models`` or ``get_latest_version``."""
        r = client.get("/models/", params={"limit": 500})
        if r.status_code == 200:
            models = r.json()
            if isinstance(models, list):
                for m in models:
                    if not isinstance(m, dict):
                        continue
                    if m.get("handle") == self.model_handle and m.get("is_latest_version"):
                        ver = m.get("version")
                        if isinstance(ver, str) and ver.strip():
                            return ver.strip()
        return get_latest_version(client, self.model_handle)

    def build_prop_to_node_map(
        self, client: APIClient, model_handle: str, version_string: str
    ) -> dict[str, str]:
        """Map each property handle to the first node that declares it."""
        nodes_path = f"/model/{quote(model_handle, safe='')}/version/{quote(version_string, safe='')}/nodes"
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
        self,
        client: APIClient,
        model_handle: str,
        version_string: str,
        node_handle: str,
        prop_handle: str,
        *,
        page_size: int = 500,
    ) -> dict[str, str]:
        """Paginated ``GET .../terms``: build ``handle -> value`` map for one property."""
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

    # ---------------------------------------------------------------- enrich

    def run_enrich(
        self, client: APIClient, query_csv: Path, out_dir: Path
    ) -> tuple[str, Path]:
        """
        Enrich the query CSV with discovery data and (optionally) ``term_value``.

        Returns ``(version_string, enriched_csv_path)``.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        enriched_csv = out_dir / f"{self.csv_prefix}_enum_terms_for_verification_enriched.csv"

        model_handle, version_string = self._resolve_model_and_version(client)
        print(f"Enrich: {self.report_subdir} version {version_string!r}")

        prop_to_node = self.build_prop_to_node_map(client, model_handle, version_string)
        print(f"Enrich: mapped {len(prop_to_node)} properties to nodes")

        rows: list[dict] = []
        with open(query_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            if self.query_csv_has_term_value and "term_value" not in fieldnames:
                idx = fieldnames.index("enum_value") if "enum_value" in fieldnames else 0
                fieldnames.insert(idx + 1, "term_value")
            for row in reader:
                if self.query_csv_has_term_value and "term_value" not in row:
                    row["term_value"] = ""
                ph = row.get("prop_handle", "")
                if ph in prop_to_node:
                    row["model_handle"] = model_handle
                    row["version_string"] = version_string
                    row["node_handle"] = prop_to_node[ph]
                rows.append(row)

        if self.needs_handle_to_value:
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
                    handle_to_value_cache[key] = self.fetch_handle_to_value_all(
                        client, model_handle, version_string, nh, ph
                    )

            for row in rows:
                nh = row.get("node_handle") or ""
                ph = row.get("prop_handle") or ""
                handle = row.get("enum_value") or ""
                if (nh, ph) in handle_to_value_cache:
                    row["term_value"] = handle_to_value_cache[(nh, ph)].get(handle, "")

        if not self.needs_handle_to_value:
            enrich_fieldnames = [
                "prop_handle", "enum_value", "description",
                "model_handle", "version_string", "node_handle",
            ]
        else:
            enrich_fieldnames = fieldnames

        with open(enriched_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=enrich_fieldnames)
            w.writeheader()
            w.writerows(rows)

        if self.needs_handle_to_value:
            filled_node = sum(1 for r in rows if r.get("node_handle"))
            filled_tv = sum(1 for r in rows if r.get("term_value"))
            print(
                f"Enrich: wrote {enriched_csv.name} ({filled_node}/{len(rows)} with node, "
                f"{filled_tv}/{len(rows)} with term_value)"
            )
        else:
            filled = sum(1 for r in rows if r.get("node_handle"))
            print(f"Enrich: wrote {enriched_csv.name} ({filled}/{len(rows)} rows with model/version/node)")

        return version_string, enriched_csv

    def _resolve_model_and_version(self, client: APIClient) -> tuple[str, str]:
        """Return ``(model_handle, version_string)``. Override for dynamic handles (CCDI-DCC)."""
        version = self.discover_version(client)
        if not version:
            raise RuntimeError(f"Could not discover {self.model_handle} version from STS")
        return self.model_handle, version

    # ---------------------------------------------------------------- verify

    def _select_url_value(self, row: dict) -> str | None:
        """Return the value to use in the term URL, or None to skip the row."""
        if not (row.get("model_handle") and row.get("version_string") and row.get("node_handle")):
            return None
        term_value_only = row.get("term_value") or ""
        if not str(term_value_only).strip():
            return None
        return term_value_only

    def run_verify(
        self,
        client: APIClient,
        enriched_csv: Path,
        out_dir: Path,
        base_url: str,
        *,
        limit: int = 0,
    ) -> tuple[Path, Path, int, int]:
        out_dir.mkdir(parents=True, exist_ok=True)
        report_csv = out_dir / f"{self.csv_prefix}_term_endpoint_verification_report.csv"
        report_md = out_dir / f"{self.csv_prefix}_term_endpoint_verification_report.md"

        with open(enriched_csv, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        to_verify: list[dict] = []
        skipped_count = 0
        for row in rows:
            url_value = self._select_url_value(row)
            if url_value is None:
                if row.get("model_handle") and row.get("version_string") and row.get("node_handle"):
                    skipped_count += 1
                continue
            to_verify.append({**row, "_value_for_url": url_value})

        if limit and limit > 0:
            to_verify = to_verify[:limit]

        self._print_verify_preamble(len(to_verify), len(rows), skipped_count)

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
            rr: dict = {
                "prop_handle": row["prop_handle"],
                "enum_value": row.get("enum_value", ""),
            }
            if self.report_csv_has_term_value:
                rr["term_value"] = row.get("term_value", "")
            rr.update({"http_status": status, "passed": passed, "notes": notes})
            report_rows.append(rr)
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(to_verify)} ...")

        report_fieldnames = ["prop_handle", "enum_value"]
        if self.report_csv_has_term_value:
            report_fieldnames.append("term_value")
        report_fieldnames.extend(["http_status", "passed", "notes"])

        with open(report_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=report_fieldnames)
            w.writeheader()
            w.writerows(report_rows)

        passed_count = sum(1 for r in report_rows if r["passed"])
        failed = [r for r in report_rows if not r["passed"]]

        self._write_report_md(
            report_md, report_csv, enriched_csv, base_url,
            report_rows, passed_count, failed, skipped_count,
        )

        self._print_verify_stdout_summary(
            passed_count, len(report_rows), failed, report_csv, report_md
        )
        return report_csv, report_md, passed_count, len(report_rows)

    def _print_verify_stdout_summary(
        self,
        passed_count: int,
        total_rows: int,
        failed: list[dict],
        report_csv: Path,
        report_md: Path,
    ) -> None:
        """Stdout summary for humans and log parsers (e.g. parser_agent)."""
        failed_count = len(failed)
        print(
            f"Verify: passed {passed_count}/{total_rows}, failed {failed_count} "
            f"\u2192 {report_csv.name}, {report_md.name}"
        )
        if failed_count:
            print(
                f"Verify: FAIL — {failed_count} term verification failure(s) "
                f"(see {report_csv.name}; process exits 1 unless --warn-only)."
            )

    def _print_verify_preamble(self, count: int, total: int, skipped: int) -> None:
        if self.needs_handle_to_value:
            print(
                f"Verify: {count} rows to GET (from {total} enriched; "
                f"skipped {skipped} with empty term_value \u2014 handle cannot be used as URL param)"
            )
        else:
            print(
                f"Verify: {count} rows to GET (from {total} enriched; "
                "URL uses YAML enum_value, same as legacy verify_term_endpoint_from_sheet.py)"
            )

    def _write_report_md(
        self,
        report_md: Path,
        report_csv: Path,
        enriched_csv: Path,
        base_url: str,
        report_rows: list[dict],
        passed_count: int,
        failed: list[dict],
        skipped_count: int,
    ) -> None:
        with open(report_md, "w", encoding="utf-8") as f:
            f.write(f"# {self.report_subdir} term endpoint verification report\n\n")
            f.write(
                f"**Base URL:** `{base_url}`\n\n"
                f"**Endpoint:** `GET {{base}}/model/{{modelHandle}}/version/{{versionString}}/"
                f"node/{{nodeHandle}}/property/{{propHandle}}/term/{{termValue}}`\n\n"
            )
            f.write(f"**Input:** `{enriched_csv.name}`\n\n")
            if self.needs_handle_to_value:
                f.write(
                    f"**Rows skipped (no API `term_value`):** {skipped_count} "
                    "(YAML handle could not be resolved from paginated `/terms`; "
                    "`/term/{termValue}` requires the Term **value**, not the handle.)\n\n"
                )
            else:
                f.write(
                    "**Note:** `termValue` in the URL is the YAML **enum_value** (legacy behavior; "
                    "no `/terms` handle\u2192value enrichment).\n\n"
                )
            f.write(f"**Rows verified (HTTP):** {len(report_rows)}\n\n")
            f.write(f"**Passed:** {passed_count}\n\n")
            f.write(f"**Failed:** {len(failed)}\n\n")
            if failed:
                f.write("## Failed rows (first 50)\n\n")
                if self.report_csv_has_term_value:
                    f.write(
                        "| prop_handle | enum_value (handle) | term_value | http_status | notes |\n"
                    )
                    f.write("|-------------|---------------------|------------|-------------|-------|\n")
                else:
                    f.write("| prop_handle | enum_value | http_status | notes |\n")
                    f.write("|-------------|------------|-------------|-------|\n")
                for r in failed[:50]:
                    ev = r.get("enum_value", "")
                    ev = (ev[:25] + "\u2026") if len(ev) > 25 else ev
                    if self.report_csv_has_term_value:
                        tv = r.get("term_value", "")
                        tv = (tv[:25] + "\u2026") if len(tv) > 25 else tv
                        notes = str(r.get("notes", ""))[:60]
                        f.write(
                            f"| {r['prop_handle']} | {ev} | {tv} | {r['http_status']} | {notes} |\n"
                        )
                    else:
                        ev_wide = r.get("enum_value", "")
                        ev_wide = (ev_wide[:40] + "\u2026") if len(ev_wide) > 40 else ev_wide
                        notes = str(r.get("notes", ""))[:80]
                        f.write(
                            f"| {r['prop_handle']} | {ev_wide} | {r['http_status']} | {notes} |\n"
                        )
                if len(failed) > 50:
                    f.write(
                        f"\n... and {len(failed) - 50} more. See `{report_csv.name}` for full list.\n"
                    )
            f.write(f"\n**Full results:** `{report_csv.name}`\n")

    # ------------------------------------------------------------------ CLI

    def _should_fail(self, passed: int, total: int, warn_only: bool) -> bool:
        """Return True if the process should exit with code 1."""
        if warn_only:
            return False
        return passed < total

    def main(self) -> None:
        """CLI entrypoint: run extract, enrich, verify with standard flags."""
        parser = argparse.ArgumentParser(
            description=(
                f"{self.report_subdir} term-by-value pipeline: extract from YAML, enrich via STS, "
                f"verify /term/{{value}}, write CSV + Markdown under reports/term_value/{self.report_subdir}/"
            )
        )
        parser.add_argument(
            "--yaml", type=Path, default=None,
            help=f"Path to property YAML (default: {self.default_yaml_filename})",
        )
        parser.add_argument(
            "--out-dir", type=Path, default=None,
            help=f"Output directory (default: reports/term_value/{self.report_subdir}/)",
        )
        parser.add_argument(
            "--base-url", default=None,
            help=f"STS base URL including /v2 (default: STS_BASE_URL or {DEFAULT_STS_BASE_URL})",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Max rows to verify (0 = all). Extract/enrich always process full YAML.",
        )
        parser.add_argument(
            "--skip-extract", action="store_true",
            help=f"Skip extract; expect {self.csv_prefix}_enum_terms_for_verification.csv in out-dir",
        )
        parser.add_argument(
            "--skip-enrich", action="store_true",
            help=f"Skip enrich; expect {self.csv_prefix}_enum_terms_for_verification_enriched.csv in out-dir",
        )
        parser.add_argument(
            "--warn-only", action="store_true",
            help="Exit 0 even if some rows fail (still writes reports)",
        )
        args = parser.parse_args()

        yaml_path = Path(args.yaml) if args.yaml else self.default_yaml_path()
        out_dir = Path(args.out_dir) if args.out_dir else self.default_report_dir()
        base_url = (args.base_url or sts_base_url()).rstrip("/")

        out_dir.mkdir(parents=True, exist_ok=True)
        query_csv = out_dir / f"{self.csv_prefix}_enum_terms_for_verification.csv"
        enriched_csv = out_dir / f"{self.csv_prefix}_enum_terms_for_verification_enriched.csv"

        if not args.skip_extract:
            self.run_extract(yaml_path, out_dir)
        elif not query_csv.exists():
            print(f"--skip-extract but missing {query_csv}", file=sys.stderr)
            sys.exit(2)

        client = APIClient(base_url)

        if not args.skip_enrich:
            _, enriched_path = self.run_enrich(client, query_csv, out_dir)
            enriched_csv = enriched_path
        elif not enriched_csv.exists():
            print(f"--skip-enrich but missing {enriched_csv}", file=sys.stderr)
            sys.exit(2)

        _, _, passed, total = self.run_verify(
            client, enriched_csv, out_dir, base_url, limit=args.limit
        )
        if self._should_fail(passed, total, args.warn_only):
            sys.exit(1)
        sys.exit(0)
