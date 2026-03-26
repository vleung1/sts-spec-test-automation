"""
CCDI-DCC term-by-value verification pipeline.

Subclass of :class:`~sts_test_framework.term_verify_pipeline.TermVerifyPipeline`.

**Unique behaviors compared to other models:**

- **extract** — Inline enums plus optional ``http(s)`` URLs pointing at remote
  PropDefinitions YAML (CBIIT); values are merged into the same enum list.
- **discover** — ``GET /models`` may return handle ``CCDI-DCC`` or ``CCDI_DCC``;
  the actual handle is discovered at runtime.
- **verify** — URL value = ``(term_value or '') or (enum_value or '')`` per legacy
  sheet. :data:`KNOWN_MISSING_IN_STS_DB` lists ``(prop_handle, enum_value)`` pairs
  that still appear as failed but do not cause a non-zero exit.

CLI: ``sts-ccdi-dcc-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from sts_test_framework.client import APIClient
from sts_test_framework.discover import get_latest_version
from sts_test_framework.term_verify_pipeline import TermVerifyPipeline
from sts_test_framework.term_verify_utils import strip_inline_yaml_comment

MODEL_LABEL = "CCDI-DCC"

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

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER_PATTERN = re.compile(r"^\s{4,}Enum\s*:")
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


def _clean_enum_value(val: str) -> str:
    """Normalize one enum item: quoted values use ``strip_inline_yaml_comment``; unquoted use `` #``."""
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


def _is_enum_url(s: str) -> bool:
    t = s.strip()
    return t.startswith("http://") or t.startswith("https://")


def _parse_remote_prop_definitions_yaml(body: str) -> list[str]:
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
            s = _clean_enum_value(rest)
            if s:
                values.append(s)
    seen: set[str] = set()
    return [v for v in values if v not in seen and not seen.add(v)]  # type: ignore[func-returns-value]


def _fetch_enum_values_from_url(url: str, cache: dict[str, list[str]]) -> list[str]:
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


class CCDIDCCTermVerify(TermVerifyPipeline):
    model_handle = "CCDI-DCC"
    csv_prefix = "ccdi_dcc"
    default_yaml_filename = "ccdi-dcc-model-props-3.yml"
    report_subdir = "CCDI-DCC"

    def parse_yaml(self, path: Path) -> list[tuple[str, str, list[str]]]:
        cache: dict[str, list[str]] = {}
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
                                val = _clean_enum_value(item_match.group(1))
                                if val:
                                    if _is_enum_url(val):
                                        enum_values.extend(_fetch_enum_values_from_url(val, cache))
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

    def _resolve_model_and_version(self, client: APIClient) -> tuple[str, str]:
        """CCDI-DCC handle may be ``CCDI-DCC`` or ``CCDI_DCC`` in the API."""
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
        raise RuntimeError("Could not discover CCDI-DCC model handle/version from STS")

    def _select_url_value(self, row: dict) -> str | None:
        """CCDI-DCC legacy: prefer ``term_value``, fall back to ``enum_value``."""
        if not (row.get("model_handle") and row.get("version_string") and row.get("node_handle")):
            return None
        value = (row.get("term_value") or "") or (row.get("enum_value") or "")
        if not str(value).strip():
            return None
        return value

    def _print_verify_preamble(self, count: int, total: int, skipped: int) -> None:
        print(
            f"Verify: {count} rows to GET (from {total} enriched; "
            f"skipped {skipped} empty after (term_value or enum_value); "
            f"legacy: `(term_value or '') or (enum_value or '')` then `.strip()` check)"
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
        failed_allowlisted = [
            r for r in failed
            if (str(r["prop_handle"]), str(r["enum_value"])) in KNOWN_MISSING_IN_STS_DB
        ]
        unexpected_failure_count = len(failed) - len(failed_allowlisted)
        self._unexpected_failure_count = unexpected_failure_count

        with open(report_md, "w", encoding="utf-8") as f:
            f.write(f"# {MODEL_LABEL} term endpoint verification report\n\n")
            f.write(
                f"**Base URL:** `{base_url}`\n\n"
                f"**Endpoint:** `GET {{base}}/model/{{modelHandle}}/version/{{versionString}}/"
                f"node/{{nodeHandle}}/property/{{propHandle}}/term/{{termValue}}`\n\n"
            )
            f.write(f"**Input:** `{enriched_csv.name}`\n\n")
            f.write(
                f"**Rows skipped (neither `term_value` nor `enum_value` usable):** {skipped_count}\n\n"
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
                    ev = (ev[:25] + "\u2026") if len(ev) > 25 else ev
                    tv = r.get("term_value", "")
                    tv = (tv[:25] + "\u2026") if len(tv) > 25 else tv
                    notes = str(r.get("notes", ""))[:60]
                    f.write(
                        f"| {r['prop_handle']} | {ev} | {tv} | {r['http_status']} | {notes} |\n"
                    )
                if len(failed) > 50:
                    f.write(
                        f"\n... and {len(failed) - 50} more. See `{report_csv.name}` for full list.\n"
                    )
            f.write(f"\n**Full results:** `{report_csv.name}`\n")

    def _print_verify_stdout_summary(
        self,
        passed_count: int,
        total_rows: int,
        failed: list[dict],
        report_csv: Path,
        report_md: Path,
    ) -> None:
        failed_count = len(failed)
        u = getattr(self, "_unexpected_failure_count", failed_count)
        allowlisted_count = failed_count - u
        print(
            f"Verify: passed {passed_count}/{total_rows}, failed {failed_count} "
            f"\u2192 {report_csv.name}, {report_md.name}"
        )
        if not failed_count:
            return
        print(
            f"Verify: failed breakdown \u2014 {allowlisted_count} allowlisted "
            f"(known missing in STS), {u} unexpected (see {report_csv.name})."
        )
        if u > 0:
            print(
                f"Verify: FAIL — {u} unexpected term verification failure(s) "
                f"(process exits 1 unless --warn-only)."
            )
        else:
            print(
                "Verify: OK \u2014 0 unexpected failures (all failed rows are allowlisted; exit 0)."
            )

    def _should_fail(self, passed: int, total: int, warn_only: bool) -> bool:
        if warn_only:
            return False
        return getattr(self, "_unexpected_failure_count", total - passed) > 0


if __name__ == "__main__":
    CCDIDCCTermVerify().main()
