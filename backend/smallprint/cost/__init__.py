"""Cost model: turns `cost_streams` and a horizon into a lifetime total."""
from decimal import Decimal

LEVELS = ("low", "mid", "high")


def _is_active(stream, month, horizon_months):
    first = stream.get("from_month", 1)
    last = min(stream.get("to_month", horizon_months), horizon_months)
    return first <= month <= last


def _monthly_charge(streams, month, horizon_months):
    recurring = [s for s in streams
                 if s["type"] == "recurring" and _is_active(s, month, horizon_months)]
    if not recurring:
        return Decimal(0)
    charge = sum(Decimal(str(s["amount"])) for s in recurring)
    # A rise only exists while there is a recurring fee for it to apply to.
    charge += sum(Decimal(str(s["amount"])) for s in streams
                  if s["type"] == "step_change" and s["month"] <= month)
    return charge


def _usage_charge(stream, level, horizon_months):
    months = sum(1 for m in range(1, horizon_months + 1)
                 if _is_active(stream, m, horizon_months))
    units = Decimal(str(stream["units_per_month"][level]))
    return Decimal(str(stream["unit_price"])) * units * months


HORIZONS = (12, 24)

# What each stream type must carry before it can be counted.
REQUIRED_FIELDS = {
    "one_off": ("amount",),
    "recurring": ("amount",),
    "step_change": ("amount", "month"),
    "usage": ("unit_price", "units_per_month"),
}


def _validate(cost_streams, horizon_months):
    if horizon_months not in HORIZONS:
        raise ValueError(f"horizon must be 12 or 24 months, got {horizon_months}")
    for stream in cost_streams:
        label = stream.get("label", "<unlabelled>")
        if stream.get("type") not in REQUIRED_FIELDS:
            raise ValueError(f"cost stream '{label}' has unknown type {stream.get('type')!r}")
        for field in REQUIRED_FIELDS[stream["type"]]:
            if stream.get(field) is None:
                raise ValueError(f"cost stream '{label}' is missing '{field}'")
        if stream["type"] == "usage":
            missing = [lv for lv in LEVELS if stream["units_per_month"].get(lv) is None]
            if missing:
                raise ValueError(f"cost stream '{label}' is missing units_per_month {missing}")


def _exit_fee_applies(exit_fee, min_term_months, horizon_months):
    if exit_fee is None:
        return False
    # With no stated minimum term, the fee is taken to apply whenever you leave.
    return min_term_months is None or horizon_months < min_term_months


def lifetime_cost(cost_streams, horizon_months, exit_fee=None, min_term_months=None):
    """Lifetime cost of `cost_streams` over `horizon_months`.

    `total` is the cost of staying to the end of the horizon, as a low/mid/high range.
    `total_if_leaving` adds `exit_fee` when leaving at the horizon would break the
    minimum term. The exit fee never changes `total`.
    """
    _validate(cost_streams, horizon_months)
    if not cost_streams:
        return {"state": "not_found", "total": None, "total_if_leaving": None}
    fixed = sum(Decimal(str(s["amount"])) for s in cost_streams if s["type"] == "one_off")
    for month in range(1, horizon_months + 1):
        fixed += _monthly_charge(cost_streams, month, horizon_months)
    usage_streams = [s for s in cost_streams if s["type"] == "usage"]
    exact = {
        level: fixed + sum(_usage_charge(s, level, horizon_months) for s in usage_streams)
        for level in LEVELS
    }
    fee = Decimal(str(exit_fee)) if _exit_fee_applies(exit_fee, min_term_months, horizon_months) else 0
    return {
        "state": "estimated" if usage_streams else "found",
        "total": {level: float(value) for level, value in exact.items()},
        "total_if_leaving": {level: float(value + fee) for level, value in exact.items()},
    }
