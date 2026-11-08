"""Shared fixtures for the server tests."""
from __future__ import annotations

import pytest

from server import main, pipeline
from smallprint.tc_cache import TermsCache


async def _fast_company_stub(brand: str, domain: str, **_) -> dict:
    return {"brand": brand, "parent": None, "ch_number": None,
            "match_via": "Brand not identified", "records": []}


@pytest.fixture(autouse=True)
def no_card_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream mock cards with no delay.

    The demo delay is about 3 s per /analyse stream. test_rate_limit opens
    60 streams, so without this the suite takes over 3 minutes.
    """
    monkeypatch.setattr(main, "CARD_DELAY_SECONDS", (0.0, 0.0))


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call the real OpenAI API from tests, even if a developer has a key set.

    Real-pipeline tests opt in by patching main.get_llm_client with a faked client.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(main, "_llm_client", None)
    monkeypatch.setattr(main, "_search", None)
    monkeypatch.delenv("SMALLPRINT_PREWARM_KEY", raising=False)
    monkeypatch.delenv("SMALLPRINT_REFILL", raising=False)  # gated feature: tests opt in
    # A fresh T&C cache per test, so one test's extraction never serves another.
    fresh = TermsCache()
    monkeypatch.setattr(main, "get_cache", lambda: fresh)
    # Company lookup makes live HTTP calls; stub it out so tests stay fast and offline.
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: _fast_company_stub)
