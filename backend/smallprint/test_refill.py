"""S8 (#21): refill lookup. Anthropic (httpx2) and Tavily (httpx) are faked at HTTP."""
from __future__ import annotations

import json

import httpx
import httpx2
import pytest
from anthropic import AsyncAnthropic

from smallprint.refill import (
    DEFAULT_USAGE, SOURCE, SOURCE_DEFAULT_USAGE, find_refill, verify_refill,
)
from smallprint.search_fallback import TavilySearch
from smallprint.spend import SpendTracker
from smallprint.tc_cache import TermsCache

PAGE_URL = "https://www.amazon.co.uk/dp/B08H93ZRK9"
REFILL_URL = "https://www.amazon.co.uk/dp/B07REFILL1"
PAGE = ("Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99.\n"
        "Replace your brush head every 3 months.\nFree delivery on orders over £25.")

GOOD = {
    "consumable": {"value": "Oral-B iO Replacement Brush Heads", "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."},
    "pack_price": {"value": 39.99, "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."},
    "units_per_pack": {"value": 4, "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."},
    "replace_every_months": {"value": 3, "quote": "Replace your brush head every 3 months."},
}
NONE = {k: {"value": None, "quote": None} for k in GOOD}


# --- verification --------------------------------------------------------

def test_good_refill_becomes_a_labelled_usage_stream():
    s = verify_refill(GOOD, PAGE, "Oral-B", REFILL_URL)
    assert s["type"] == "usage" and s["unit_price"] == 39.99
    assert s["label"] == "Refill: Oral-B iO Replacement Brush Heads (pack of 4)"
    # 4 heads, each replaced every 3 months: one pack per 12 months.
    assert s["units_per_month"] == {"low": 0.042, "mid": 0.083, "high": 0.167}
    assert s["evidence"] == {"quote": GOOD["pack_price"]["quote"], "url": REFILL_URL, "source_step": SOURCE}


def test_without_a_stated_interval_usage_is_the_labelled_default():
    s = verify_refill({**GOOD, "replace_every_months": NONE["replace_every_months"]}, PAGE, "Oral-B", REFILL_URL)
    assert s["units_per_month"] == DEFAULT_USAGE
    assert s["evidence"]["source_step"] == SOURCE_DEFAULT_USAGE


@pytest.mark.parametrize("raw", [
    {**GOOD, "pack_price": {"value": 29.99, "quote": GOOD["pack_price"]["quote"]}},          # price not in quote
    {**GOOD, "pack_price": {"value": 39.99, "quote": "Brush heads cost £39.99 for four."}},  # paraphrase
    {**GOOD, "consumable": NONE["consumable"]},                                              # no consumable
    {**GOOD, "pack_price": NONE["pack_price"]},                                              # no price
    {**GOOD, "pack_price": {"value": -39.99, "quote": GOOD["pack_price"]["quote"]}},
    NONE,
])
def test_refill_that_does_not_hold_up_is_dropped(raw):
    assert verify_refill(raw, PAGE, "Oral-B", REFILL_URL) is None


def test_another_brands_refill_is_never_attached():
    assert verify_refill(GOOD, PAGE, "Philips", REFILL_URL) is None


def test_bad_interval_or_pack_falls_back_safely():
    raw = {**GOOD, "units_per_pack": {"value": 4.5, "quote": GOOD["units_per_pack"]["quote"]},
           "replace_every_months": {"value": 6, "quote": "Replace your brush head every 3 months."}}
    s = verify_refill(raw, PAGE, "Oral-B", REFILL_URL)
    assert s["label"].endswith("Brush Heads")  # no pack size
    assert s["units_per_month"] == DEFAULT_USAGE


# --- the lookup end to end -----------------------------------------------

class Fakes:
    def __init__(self, llm_json: dict | None = GOOD, results: list[dict] | None = None, stop_reason: str = "end_turn"):
        self.llm_json, self.stop_reason = llm_json, stop_reason
        self.results = results if results is not None else [
            {"title": "Brush heads", "url": REFILL_URL, "content": "snippet", "score": 0.9, "raw_content": PAGE}]
        self.llm_bodies: list[dict] = []
        self.tavily_bodies: list[dict] = []

    def llm(self, request: httpx2.Request) -> httpx2.Response:
        self.llm_bodies.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [] if self.stop_reason == "refusal" else [{"type": "text", "text": json.dumps(self.llm_json)}],
            "stop_reason": self.stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1500, "output_tokens": 200}})

    def tavily(self, request: httpx.Request) -> httpx.Response:
        self.tavily_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"query": "q", "answer": None, "images": [], "response_time": 0.2,
                                         "results": self.results})

    def clients(self):
        client = AsyncAnthropic(api_key="t", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.llm)))
        search = TavilySearch("tvly-t", http=httpx.AsyncClient(transport=httpx.MockTransport(self.tavily)))
        return client, search


async def _find(f: Fakes, brand="Oral-B", page_url=PAGE_URL, tracker=None, cache=None):
    client, search = f.clients()
    return await find_refill(client, search, name="Oral-B electric toothbrush", brand=brand, page_url=page_url,
                             install_id="i1", tracker=tracker or SpendTracker(1.0), cache=cache)


async def test_finds_the_refill_with_one_restricted_search_and_one_llm_call():
    f = Fakes()
    tracker = SpendTracker(1.0)
    s = await _find(f, tracker=tracker)
    assert s["unit_price"] == 39.99 and s["evidence"]["url"] == REFILL_URL
    assert len(f.tavily_bodies) == 1 and len(f.llm_bodies) == 1
    body = f.tavily_bodies[0]
    assert body["include_domains"] == ["amazon.co.uk"]
    assert body["query"].startswith("Oral-B ")
    assert f.llm_bodies[0]["model"] == "claude-haiku-5-5"
    assert "character for character" in f.llm_bodies[0]["system"]
    assert tracker.spent("i1") > 0  # charged to the install like any LLM call


async def test_brand_site_is_searched_too_for_non_amazon_pages():
    f = Fakes(results=[])
    await _find(f, brand="SodaStream", page_url="https://www.sodastream.co.uk/products/terra")
    assert f.tavily_bodies[0]["include_domains"] == ["amazon.co.uk", "sodastream.co.uk"]


async def test_results_from_other_sites_are_ignored():
    f = Fakes(results=[{"title": "x", "url": "https://cheap-heads.example/oralb", "content": PAGE, "score": 1, "raw_content": PAGE}])
    assert await _find(f) is None
    assert f.llm_bodies == []


async def test_no_brand_means_no_lookup():
    f = Fakes()
    assert await _find(f, brand=None) is None
    assert await _find(f, brand="  ") is None
    assert f.tavily_bodies == [] and f.llm_bodies == []


async def test_spend_limit_stops_it():
    f = Fakes()
    assert await _find(f, tracker=SpendTracker(0.0)) is None
    assert f.llm_bodies == []


async def test_cached_both_found_and_not_found_but_not_failures():
    cache = TermsCache()
    f = Fakes()
    first = await _find(f, cache=cache)
    assert await _find(f, cache=cache) == first
    assert len(f.llm_bodies) == 1 and len(f.tavily_bodies) == 1

    nothing = Fakes(llm_json=NONE)
    await _find(nothing, brand="Gillette", cache=cache)
    await _find(nothing, brand="Gillette", cache=cache)
    assert len(nothing.llm_bodies) == 1  # "looked properly, nothing there" is cached

    refused = Fakes(stop_reason="refusal")
    await _find(refused, brand="Canon", cache=cache)
    await _find(refused, brand="Canon", cache=cache)
    assert len(refused.llm_bodies) == 2  # a refusal is retried, never cached
