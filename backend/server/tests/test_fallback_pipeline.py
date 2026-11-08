"""S6 (#15) done when: fallback cards are labelled and linked.

Real /analyse, real extractor and quote verifier. Anthropic and Tavily are faked at HTTP.
"""
from __future__ import annotations

import json

import httpx
import jsonschema

from server import main
from smallprint.search_fallback import SOURCE, TavilySearch
from smallprint.verify import verify_quote

from .test_pipeline import GYM_TERMS, REQUEST, RESPONSE_SCHEMA, FakeLLM, assemble, cards, stream, tracker, use_llm  # noqa: F401

FOUND_URL = "https://www.fitbox.example/legal/membership-terms"
FAILED = {"url": "https://www.fitbox.example/terms", "kind": "terms", "fetch_failed": True, "error": "HTTP 403"}


class FakeTavily:
    def __init__(self, results: list[dict]):
        self.results, self.bodies = results, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"query": "q", "answer": None, "images": [], "response_time": 0.3,
                                         "results": self.results})

    def search(self) -> TavilySearch:
        return TavilySearch("tvly-test", http=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))


def use_tavily(monkeypatch, fake: FakeTavily) -> FakeTavily:
    s = fake.search()
    monkeypatch.setattr(main, "get_search", lambda: s)
    return fake


def gym_result(url: str = FOUND_URL) -> dict:
    return {"title": "Membership terms", "url": url, "content": "snippet", "score": 0.9, "raw_content": GYM_TERMS}


async def test_fallback_cards_are_labelled_and_linked(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    tav = use_tavily(monkeypatch, FakeTavily([gym_result()]))

    by_card = cards(await stream({**REQUEST, "terms": [FAILED]}))

    assert len(tav.bodies) == 1 and tav.bodies[0]["include_domains"] == ["fitbox.example"]
    assert llm.calls == 1
    assert {by_card[c]["state"] for c in ("cost", "lock_in", "small_print")} == {"found"}
    jsonschema.validate(assemble(by_card), RESPONSE_SCHEMA)

    rows = (
        [s["evidence"] for s in by_card["cost"]["payload"]["cost_streams"]]
        + by_card["lock_in"]["payload"]["evidence"]
        + by_card["small_print"]["payload"]
    )
    assert rows
    for row in rows:
        assert row["source_step"] == SOURCE, row          # labelled
        assert row["url"] == FOUND_URL, row               # linked to the page the quote is on
        assert verify_quote(row["quote"], GYM_TERMS), row  # and still quote-verified


async def test_browser_fetched_values_are_not_labelled_and_win(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM())
    tav = use_tavily(monkeypatch, FakeTavily([gym_result()]))
    fetched = {"url": "https://www.fitbox.example/join-terms", "kind": "terms", "text": GYM_TERMS}

    by_card = cards(await stream({**REQUEST, "terms": [fetched, FAILED]}))

    assert len(tav.bodies) == 1
    ev = by_card["lock_in"]["payload"]["evidence"]
    assert ev and all("source_step" not in e for e in ev)
    assert all(e["url"] == fetched["url"] for e in ev)


async def test_search_finds_nothing_gives_not_found(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    use_tavily(monkeypatch, FakeTavily([gym_result("https://rival-gym.example/terms")]))
    by_card = cards(await stream({**REQUEST, "terms": [FAILED]}))
    assert llm.calls == 0  # another site's terms are never read
    assert {by_card[c]["state"] for c in ("cost", "lock_in", "small_print")} == {"not_found"}


async def test_at_most_two_searches_per_request(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM())
    tav = use_tavily(monkeypatch, FakeTavily([]))
    failed = [{**FAILED, "url": f"https://www.fitbox.example/t{i}"} for i in range(5)]
    await stream({**REQUEST, "terms": failed})
    assert len(tav.bodies) == 2


async def test_without_a_tavily_key_failed_fetches_resolve_not_found(monkeypatch, tracker):
    llm = use_llm(monkeypatch, FakeLLM())
    by_card = cards(await stream({**REQUEST, "terms": [FAILED]}))
    assert llm.calls == 0
    assert by_card["lock_in"]["state"] == "not_found"
