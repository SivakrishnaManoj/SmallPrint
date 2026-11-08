"""S7 (#16) done when: a second request for the same domain returns without a new LLM call.

Real /analyse, extractor and quote verifier; OpenAI and Tavily faked at HTTP.
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
    # The site cache is filled by the pre-warm run (server-fetched T&C), not by a visitor's text:
    # see test_site_cache_is_never_filled_from_text_a_client_sent.
    monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", "s3cret")
    first = cards(await stream(REQUEST, install="prewarm", headers={"X-Prewarm-Key": "s3cret"}))

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
    {**_reply("{}"), "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": None, "refusal": "No."}}]},
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


# --- cache poisoning -----------------------------------------------------

async def test_site_cache_is_never_filled_from_text_a_client_sent(monkeypatch, tracker):
    """T&C text comes from the client, so one install must not be able to decide what every
    other install sees for a site. The quotes in a poisoned entry verify against the text the
    attacker supplied, never against the real page, so the verifier can't catch this."""
    llm = use_llm(monkeypatch, FakeLLM())
    poison = {**REQUEST, "item": {**REQUEST["item"], "url": "https://www.vodafone.co.uk/mobile/deals"},
              "terms": [{"url": "https://attacker.example/not-vodafones-terms", "kind": "terms", "text": REQUEST["terms"][0]["text"]}]}
    attacker = cards(await stream(poison, install="attacker"))
    assert attacker["cost"]["state"] == "found"  # the attacker's own cards may use the attacker's own text
    assert llm.calls == 1

    # Another install on the same site, whose page offered no T&C to fetch.
    victim = cards(await stream({**REQUEST, "item": {**REQUEST["item"], "url": "https://www.vodafone.co.uk/mobile/sim-only"},
                                 "terms": []}, install="victim"))
    for c in TERMS_CARDS:
        assert victim[c]["state"] == "not_found", (c, victim[c]["payload"])
    assert llm.calls == 1  # nothing to extract: no page text, no T&C


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


async def test_the_prewarm_install_id_without_the_key_is_refused(monkeypatch):
    """"prewarm" is the server's own install: it gets the higher spend limit and its results are
    trusted. A client that only sends that id in X-Install-Id must not inherit either."""
    t = SpendTracker(daily_limit_usd=0.0)  # normal installs can't spend anything
    monkeypatch.setattr(main, "get_spend_tracker", lambda: t)
    monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", "s3cret")
    llm = use_llm(monkeypatch, FakeLLM())

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        async with c.stream("POST", "/analyse", json=REQUEST,
                            headers={"X-Install-Id": "prewarm", "X-Prewarm-Key": "s3cret"}) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_text():
                pass
        assert llm.calls == 1

        # Different T&C text, so a cache hit can't hide an LLM call made on the spoofed id.
        spoof = {**REQUEST, "terms": [{**REQUEST["terms"][0], "text": REQUEST["terms"][0]["text"] + "\nSpoofed."}]}
        async with c.stream("POST", "/analyse", json=spoof, headers={"X-Install-Id": "prewarm"}) as resp:
            assert resp.status_code == 403
    assert llm.calls == 1, "the spoofed request must not reach the LLM on the pre-warm budget"


@pytest.mark.parametrize("env,key", [(None, "anything"), ("s3cret", "wrong"), ("s3cret", None), ("", "")])
def test_prewarm_needs_the_server_key(monkeypatch, env, key):
    if env is None:
        monkeypatch.delenv("SMALLPRINT_PREWARM_KEY", raising=False)
    else:
        monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", env)
    assert main.is_prewarm(key) is False
