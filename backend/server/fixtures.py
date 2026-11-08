"""Load response fixtures from /fixtures and serve them by keyword match."""
from __future__ import annotations
import json
from pathlib import Path

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / f"{name}.json").read_text())


_CACHE: dict[str, dict] = {}


def _get(name: str) -> dict:
    if name not in _CACHE:
        _CACHE[name] = _load(name)
    return _CACHE[name]


def pick_fixture(item_url: str, item_name: str | None) -> dict:
    """Return the appropriate fixture dict based on URL and name keywords."""
    if item_name is None:
        return _get("no_purchase")

    url_lower = item_url.lower()
    name_lower = (item_name or "").lower()
    combined = url_lower + " " + name_lower

    # The mock is for the SodaStream request fixture only. Any other Amazon product would
    # otherwise be shown as "found" with the SodaStream figures (V1, #29).
    if any(k in combined for k in ("sodastream", "soda")):
        return _get("sodastream")
    if any(k in combined for k in ("netflix",)):
        return _get("netflix")
    if any(k in combined for k in ("broadband", "bt.com", "sky.com", "virginmedia", "virgin media")):
        return _get("broadband")
    return _get("all_not_found")
