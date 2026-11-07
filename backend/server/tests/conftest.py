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


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call the real Anthropic API from tests, even if a developer has a key set.

    Real-pipeline tests opt in by patching main.get_llm_client with a faked client.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main, "_llm_client", None)
