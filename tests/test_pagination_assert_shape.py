"""Unit tests for ``pagination_assert_max_items`` in ``_check_basic_shape``."""

from sts_test_framework.client import APIResponse
from sts_test_framework.runners.functional import _check_basic_shape


def test_pagination_assert_passes_when_list_within_limit():
    case = {"pagination_assert_max_items": 1}
    response = APIResponse(200, "[]", [], 0.0)
    ok, err = _check_basic_shape(response, case)
    assert ok and err is None

    response = APIResponse(200, "...", [{"x": 1}], 0.0)
    ok, err = _check_basic_shape(response, case)
    assert ok and err is None


def test_pagination_assert_fails_when_list_exceeds_limit():
    case = {"pagination_assert_max_items": 1}
    response = APIResponse(200, "...", [{"a": 1}, {"b": 2}], 0.0)
    ok, err = _check_basic_shape(response, case)
    assert ok is False
    assert err is not None
    assert "2" in err and "1" in err


def test_pagination_assert_skips_non_list_body():
    case = {"pagination_assert_max_items": 1}
    response = APIResponse(200, "...", {"nanoid": "x"}, 0.0)
    ok, err = _check_basic_shape(response, case)
    assert ok and err is None
