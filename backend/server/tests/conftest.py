"""Shared fixtures for the server tests."""
from __future__ import annotations

import pytest

from server import main


@pytest.fixture(autouse=True)
def no_card_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream mock cards with no delay.

    The demo delay is about 3 s per /analyse stream. test_rate_limit opens
    60 streams, so without this the suite takes over 3 minutes.
    """
    monkeypatch.setattr(main, "CARD_DELAY_SECONDS", (0.0, 0.0))
