"""Behaviour of the lifetime cost model, tested through `lifetime_cost` only.

Expected totals are worked out by hand in the comments, not recomputed in code.
"""
import pytest

from smallprint.cost import lifetime_cost

EVIDENCE = {"quote": "q", "url": "https://example.com/terms"}


def recurring(amount, from_month=1, to_month=None, label="Monthly fee"):
    stream = {"label": label, "type": "recurring", "amount": amount,
              "from_month": from_month, "evidence": EVIDENCE}
    if to_month is not None:
        stream["to_month"] = to_month
    return stream


def one_off(amount, label="Setup fee"):
    return {"label": label, "type": "one_off", "amount": amount, "evidence": EVIDENCE}


def test_setup_fee_is_charged_once():
    result = lifetime_cost([one_off(49.00), recurring(30.00)], horizon_months=12)

    # 49.00 once + 12 x 30.00 = 409.00
    assert result["total"]["mid"] == 409.00


def test_trial_price_then_full_price():
    streams = [
        recurring(1.00, from_month=1, to_month=3, label="Introductory price"),
        recurring(9.99, from_month=4, label="Full price"),
    ]

    result = lifetime_cost(streams, horizon_months=12)

    # 3 x 1.00 + 9 x 9.99 = 3.00 + 89.91 = 92.91
    assert result["total"]["mid"] == 92.91


def step_change(amount, month, label="Annual price rise"):
    return {"label": label, "type": "step_change", "amount": amount,
            "month": month, "evidence": EVIDENCE}


def test_annual_rise_applies_from_month_13():
    streams = [recurring(30.00, to_month=24), step_change(3.00, month=13)]

    result = lifetime_cost(streams, horizon_months=24)

    # months 1-12: 12 x 30.00 = 360.00; months 13-24: 12 x 33.00 = 396.00; total 756.00
    assert result["total"]["mid"] == 756.00


def test_annual_rise_in_month_13_does_not_affect_a_12_month_horizon():
    streams = [recurring(30.00, to_month=24), step_change(3.00, month=13)]

    result = lifetime_cost(streams, horizon_months=12)

    # 12 x 30.00 = 360.00
    assert result["total"]["mid"] == 360.00


def usage(unit_price, low, mid, high, label="CO2 cylinder"):
    return {"label": label, "type": "usage", "unit_price": unit_price,
            "units_per_month": {"low": low, "mid": mid, "high": high},
            "evidence": {"source": "listing", "url": "https://example.com/refill"}}


def test_usage_gives_a_low_mid_high_range():
    streams = [one_off(89.99, label="Machine"), usage(14.99, 0.5, 1.0, 2.0)]

    result = lifetime_cost(streams, horizon_months=12)

    # machine 89.99 + cylinders: low 6 x 14.99 = 89.94, mid 12 x 14.99 = 179.88, high 24 x 14.99 = 359.76
    assert result["total"] == {"low": 179.93, "mid": 269.87, "high": 449.75}


def test_usage_scales_with_the_24_month_horizon():
    streams = [one_off(89.99, label="Machine"), usage(14.99, 0.5, 1.0, 2.0)]

    result = lifetime_cost(streams, horizon_months=24)

    # machine 89.99 + cylinders: low 179.88, mid 359.76, high 719.52
    assert result["total"] == {"low": 269.87, "mid": 449.75, "high": 809.51}


def test_exit_fee_is_added_when_leaving_before_the_minimum_term_ends():
    result = lifetime_cost([recurring(32.99, to_month=24)], horizon_months=12,
                           exit_fee=215.00, min_term_months=24)

    # staying 12 months: 12 x 32.99 = 395.88; leaving then adds 215.00 = 610.88
    assert result["total"]["mid"] == 395.88
    assert result["total_if_leaving"]["mid"] == 610.88


def test_no_exit_fee_when_the_horizon_reaches_the_end_of_the_minimum_term():
    result = lifetime_cost([recurring(32.99, to_month=24)], horizon_months=24,
                           exit_fee=215.00, min_term_months=24)

    # 24 x 32.99 = 791.76, and the contract has run its course
    assert result["total"]["mid"] == 791.76
    assert result["total_if_leaving"]["mid"] == 791.76


def test_state_is_found_when_every_number_comes_from_the_page():
    assert lifetime_cost([recurring(9.99)], horizon_months=12)["state"] == "found"


def test_state_is_estimated_when_a_usage_stream_is_included():
    result = lifetime_cost([usage(14.99, 0.5, 1.0, 2.0)], horizon_months=12)

    assert result["state"] == "estimated"


def test_state_is_not_found_when_there_are_no_cost_streams():
    result = lifetime_cost([], horizon_months=12)

    assert result["state"] == "not_found"
    assert result["total"] is None
    assert result["total_if_leaving"] is None


def test_a_horizon_other_than_12_or_24_months_is_rejected():
    with pytest.raises(ValueError, match="horizon"):
        lifetime_cost([recurring(9.99)], horizon_months=18)


def test_a_stream_without_an_amount_is_rejected_rather_than_counted_as_zero():
    stream = {"label": "Monthly fee", "type": "recurring", "evidence": EVIDENCE}

    with pytest.raises(ValueError, match="Monthly fee"):
        lifetime_cost([stream], horizon_months=12)


def test_recurring_fee_is_charged_every_month_of_the_horizon():
    result = lifetime_cost([recurring(9.99)], horizon_months=12)

    # 12 x 9.99 = 119.88
    assert result["total"] == {"low": 119.88, "mid": 119.88, "high": 119.88}
