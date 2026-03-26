"""
ICDC term-by-value verification pipeline.

Subclass of :class:`~sts_test_framework.term_verify_pipeline.TermVerifyPipeline`.

Uses :func:`~sts_test_framework.term_verify_utils.clean_enum_value` instead of
``strip_inline_yaml_comment`` — it strips `` #`` comments only when the value
is not quoted, then unquotes.

CLI: ``sts-icdc-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import re
from pathlib import Path

from sts_test_framework.term_verify_pipeline import TermVerifyPipeline
from sts_test_framework.term_verify_utils import clean_enum_value

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER_PATTERN = re.compile(r"^\s{4,}Enum\s*:")
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


class ICDCTermVerify(TermVerifyPipeline):
    model_handle = "ICDC"
    csv_prefix = "icdc"
    default_yaml_filename = "icdc-model-props.yml"
    report_subdir = "ICDC"

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


if __name__ == "__main__":
    ICDCTermVerify().main()
