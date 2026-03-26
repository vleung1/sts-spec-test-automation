"""
CTDC term-by-value verification pipeline.

Subclass of :class:`~sts_test_framework.term_verify_pipeline.TermVerifyPipeline`.

Same parsing logic as C3DC (flexible ``ENUM_HEADER_PATTERN``,
``strip_inline_yaml_comment`` + ``_strip_quotes``).

CLI: ``sts-ctdc-term-verify`` (see pyproject ``[project.scripts]``).
"""
from __future__ import annotations

import re
from pathlib import Path

from sts_test_framework.term_verify_pipeline import TermVerifyPipeline
from sts_test_framework.term_verify_utils import strip_inline_yaml_comment

PROP_PATTERN = re.compile(r"^  ([a-zA-Z0-9_]+):\s*$")
DESC_PATTERN = re.compile(r"^    Desc:\s*(.*)$")
ENUM_HEADER_PATTERN = re.compile(r"^\s{4,}Enum\s*:")
ENUM_ITEM_PATTERN = re.compile(r"^\s+-\s+(.*)$")
ENUM_END_PATTERN = re.compile(r"^    [A-Za-z_]\w*\s*:")


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if len(val) >= 2:
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1].replace('\\"', '"').replace("\\'", "'")
    return val.strip()


class CTDCTermVerify(TermVerifyPipeline):
    model_handle = "CTDC"
    csv_prefix = "ctdc"
    default_yaml_filename = "ctdc_model_properties_file-v1.22.1.yaml"
    report_subdir = "CTDC"

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


if __name__ == "__main__":
    CTDCTermVerify().main()
