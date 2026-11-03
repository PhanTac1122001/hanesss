from types import SimpleNamespace

import pytest

from harness.pricing import PRICES, Usage, cost_usd


def test_usage_addition_returns_new_usage():
    a = Usage(1, 2, 3, 4)
    b = Usage(10, 20, 30, 40)
    c = a + b
    assert c == Usage(11, 22, 33, 44)
    assert a == Usage(1, 2, 3, 4)
    assert b == Usage(10, 20, 30, 40)


def test_from_api_none_cache_fields_become_zero():
    u = SimpleNamespace(
        input_tokens=5,
        output_tokens=7,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
    )
    assert Usage.from_api(u) == Usage(5, 7, 0, 0)


def test_from_api_missing_cache_fields_become_zero():
    u = SimpleNamespace(input_tokens=1, output_tokens=2)
    assert Usage.from_api(u) == Usage(1, 2, 0, 0)


def test_from_api_reads_cache_fields():
    u = SimpleNamespace(
        input_tokens=1,
        output_tokens=2,
        cache_read_input_tokens=3,
        cache_creation_input_tokens=4,
    )
    assert Usage.from_api(u) == Usage(1, 2, 3, 4)


def test_cost_sonnet_all_categories():
    u = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(2 + 10 + 0.2 + 2.5)
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(14.7)


def test_cost_unknown_model_falls_back_to_sonnet():
    u = Usage(1_000_000, 500_000, 0, 0)
    assert "no-such-model" not in PRICES
    assert cost_usd("no-such-model", u) == pytest.approx(cost_usd("claude-sonnet-5-5", u))
