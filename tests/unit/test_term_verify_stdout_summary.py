"""Stdout summaries from term-verify pipelines (parser_agent-friendly lines)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
_TERM_VERIFY_DIR = _REPO / "tests" / "term_verify"
if str(_TERM_VERIFY_DIR) not in sys.path:
    sys.path.insert(0, str(_TERM_VERIFY_DIR))

from ccdi_dcc_term_verify import CCDIDCCTermVerify  # noqa: E402
from icdc_term_verify import ICDCTermVerify  # noqa: E402


@patch("builtins.print")
def test_icdc_stdout_summary_all_pass(mock_print) -> None:
    ICDCTermVerify()._print_verify_stdout_summary(5, 5, [], Path("r.csv"), Path("r.md"))
    assert mock_print.call_count == 1
    out = mock_print.call_args_list[0][0][0]
    assert "failed 0" in out
    assert "FAIL" not in out


@patch("builtins.print")
def test_icdc_stdout_summary_emits_fail_line(mock_print) -> None:
    failed = [{"prop_handle": "p", "enum_value": "e"}]
    ICDCTermVerify()._print_verify_stdout_summary(4, 5, failed, Path("r.csv"), Path("r.md"))
    assert mock_print.call_count == 2
    assert "failed 1" in mock_print.call_args_list[0][0][0]
    assert "Verify: FAIL —" in mock_print.call_args_list[1][0][0]


@patch("builtins.print")
def test_dcc_stdout_allowlisted_only_no_fail_token(mock_print) -> None:
    pwc = CCDIDCCTermVerify()
    pwc._unexpected_failure_count = 0
    failed = [{"prop_handle": "file_type", "enum_value": "cnn"}]
    pwc._print_verify_stdout_summary(9, 10, failed, Path("r.csv"), Path("r.md"))
    lines = [c[0][0] for c in mock_print.call_args_list]
    assert any("failed breakdown" in ln for ln in lines)
    assert any("Verify: OK" in ln for ln in lines)
    assert not any("Verify: FAIL" in ln for ln in lines)


@patch("builtins.print")
def test_dcc_stdout_unexpected_emits_fail_line(mock_print) -> None:
    pwc = CCDIDCCTermVerify()
    pwc._unexpected_failure_count = 2
    failed = [{"prop_handle": "a"}, {"prop_handle": "b"}]
    pwc._print_verify_stdout_summary(8, 10, failed, Path("r.csv"), Path("r.md"))
    lines = [c[0][0] for c in mock_print.call_args_list]
    assert any("Verify: FAIL — 2 unexpected" in ln for ln in lines)
