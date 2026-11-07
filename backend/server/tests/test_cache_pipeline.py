"""S7 (#16) done when: a second request for the same domain returns without a new LLM call.

Real /analyse, extractor and quote verifier; Anthropic and Tavily faked at HTTP.
"""
from __future__ import annotations

import time

import pytest

from server import main
from smallprint.spend import SpendTracker
from smallprint.tc_cache import TermsCache

from .test_fallback_pipeline import FAILED, FakeTavily, gym_result, use_tavily
from .test_pipeline import REQUEST, TERMS_URL, FakeLLM, _reply, cards, stream, tracker, use_llm  # noqa: F401

TERMS_CARDS = ("cost", "lock_in", "small_print")


def terms_cards(by_card: dict) -> dict:
    return {c: (by_card[c]["state"], by_card[c]["payload"]) for c in TERMS_CARDS}


async def test_second_request_for_the_same_domain_makes_no_llm_call(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    first = cards(await stream(REQUEST))
    assert llm.calls == 1

    second = cards(await stream(REQUEST, install="another-install"))

    assert llm.calls == 1, "cached: no new LLM call"
    assert terms_cards(second) == terms_cards(first)
    assert second["cost"]["state"] == "found"
    assert tracker.spent("another-install") == 0  # nothing charged for a cache hit


async def test_repeat_visit_without_terms_is_served_from_the_site_cache(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    tav = use_tavily(monkeypatch, FakeTavily([gym_result()]))
    first = cards(await stream(REQUEST))

    # Another product page on the same site; the extension sends no T&C this time.
    other_page = {**REQUEST, "item": {**REQUEST["item"], "url": "https://www.fitbox.example/join/premium"},
                  "terms": []}
    second = cards(await stream(other_page))

    assert llm.calls == 1 and tav.bodies == []  # no LLM call, no search
    assert terms_cards(second) == terms_cards(first)


async def test_cached_cards_arrive_in_under_5_seconds(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM(delay=6))  # a fresh extraction would take 6 s
    cache = TermsCache()
    monkeypatch.setattr(main, "get_cache", lambda: cache)
    # Warm the cache directly (as the pre-warm run would).
    from server.pipeline import terms_source
    from server.models import AnalyseRequest
    fast = FakeLLM()
    await terms_source(AnalyseRequest.model_validate(REQUEST), "warm", fast.client(), SpendTracker(1.0), None, cache)

    start = time.monotonic()
    events = await stream(REQUEST)
    t = {e["card"]: at for at, e in events if e is not None}
    assert max(t[c] for c in TERMS_CARDS) < 5
    assert time.monotonic() - start < 5


async def test_changed_terms_page_is_extracted_again(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    await stream(REQUEST)
    changed = {**REQUEST, "terms": [{"url": TERMS_URL, "kind": "terms",
                                     "text": REQUEST["terms"][0]["text"] + "\n4. New clause added."}]}
    await stream(changed)
    assert llm.calls == 2


async def test_search_results_are_cached_too(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    tav = use_tavily(monkeypatch, FakeTavily([gym_result()]))
    await stream({**REQUEST, "terms": [FAILED]})
    second = cards(await stream({**REQUEST, "terms": [FAILED]}))
    assert llm.calls == 1
    assert len(tav.bodies) == 1  # the failed-fetch request is answered from the site cache
    assert second["lock_in"]["payload"]["evidence"][0]["source_step"] == "tavily_search"


@pytest.mark.parametrize("reply", [
    {**_reply("{}"), "stop_reason": "refusal", "content": []},
    _reply("not json"),
])
async def test_a_failed_extraction_is_not_cached(monkeypatch, tracker, reply):
    llm = use_llm(monkeypatch, FakeLLM(reply=reply))
    await stream(REQUEST)
    await stream(REQUEST)
    assert llm.calls == 2  # retried, never cached as "nothing found"


async def test_a_spend_limit_cut_off_is_not_cached(monkeypatch):
    t = SpendTracker(daily_limit_usd=0.0)
    monkeypatch.setattr(main, "get_spend_tracker", lambda: t)
    llm = use_llm(monkeypatch, FakeLLM())
    first = cards(await stream(REQUEST))
    assert first["cost"]["state"] == "limit_reached"

    t.daily_limit_usd = 1.0
    second = cards(await stream(REQUEST))
    assert llm.calls == 1 and second["cost"]["state"] == "found"


# --- pre-warm access -----------------------------------------------------

async def test_prewarm_key_gets_its_own_higher_limit(monkeypatch):
    t = SpendTracker(daily_limit_usd=0.0)  # normal installs can't spend anything
    monkeypatch.setattr(main, "get_spend_tracker", lambda: t)
    monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", "s3cret")
    llm = use_llm(monkeypatch, FakeLLM())

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        async with c.stream("POST", "/analyse", json=REQUEST,
                            headers={"X-Install-Id": "prewarm", "X-Prewarm-Key": "s3cret"}) as resp:
            assert resp.status_code == 200
            body = "".join([chunk async for chunk in resp.aiter_text()])
    assert llm.calls == 1 and '"state": "found"' in body
    assert t.spent(main.PREWARM_INSTALL) > 0


@pytest.mark.parametrize("env,key", [(None, "anything"), ("s3cret", "wrong"), ("s3cret", None), ("", "")])
def test_prewarm_needs_the_server_key(monkeypatch, env, key):
    if env is None:
        monkeypatch.delenv("SMALLPRINT_PREWARM_KEY", raising=False)
    else:
        monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", env)
    assert main.is_prewarm(key) is False
