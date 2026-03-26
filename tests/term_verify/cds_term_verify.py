"""
CDS term-by-value verification pipeline.

Subclass of :class:`~sts_test_framework.term_verify_pipeline.TermVerifyPipeline`.

**Unlike CCDI/C3DC/ICDC**, CDS does **not** call ``GET .../terms`` to map handle to value.
The YAML ``enum_value`` is already the string used in the term URL and in the JSON ``value``
check. Accordingly, ``needs_handle_to_value = False`` and the CSV has no ``term_value`` column.

CLI: ``sts-cds-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import re
from pathlib import Path

from sts_test_framework.term_verify_pipeline import TermVerifyPipeline

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER = "    Enum:"
ENUM_ITEM_PATTERN = re.compile(r"^    -\s+(.*)$")


class CDSTermVerify(TermVerifyPipeline):
    model_handle = "CDS"
    csv_prefix = "cds"
    default_yaml_filename = "cds-model-props-4.yml"
    report_subdir = "CDS"
    needs_handle_to_value = False
    query_csv_has_term_value = False
    report_csv_has_term_value = False

    def parse_yaml(self, path: Path) -> list[tuple[str, str, list[str]]]:
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

    def _select_url_value(self, row: dict) -> str | None:
        """CDS uses ``enum_value`` directly (no term_value)."""
        if not (row.get("model_handle") and row.get("version_string") and row.get("node_handle")):
            return None
        return row.get("enum_value") or None


if __name__ == "__main__":
    CDSTermVerify().main()
