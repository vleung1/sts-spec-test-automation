"""Unit tests for model-pvs ``__skip_oob`` body shape (non-empty array, empty permissibleValues)."""

from sts_test_framework.client import APIResponse
from sts_test_framework.runners.functional import _check_basic_shape


CASE = {"skip_oob_assert": "model_pvs_empty_permissible_values"}


def test_model_pvs_skip_oob_rejects_empty_top_level_array():
    response = APIResponse(200, "[]", [], 0.0)
    ok, err = _check_basic_shape(response, CASE)
    assert ok is False
    assert err is not None
    assert "please investigate" in err.lower()


def test_model_pvs_skip_oob_accepts_non_empty_with_empty_permissible_values():
    data = [{"permissibleValues": []}]
    response = APIResponse(200, "...", data, 0.0)
    ok, err = _check_basic_shape(response, CASE)
    assert ok is True
    assert err is None


def test_model_pvs_skip_oob_rejects_item_without_empty_permissible_values():
    data = [{"permissibleValues": ["x"]}]
    response = APIResponse(200, "...", data, 0.0)
    ok, err = _check_basic_shape(response, CASE)
    assert ok is False
    assert "permissibleValues" in (err or "")
