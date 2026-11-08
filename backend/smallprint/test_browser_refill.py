"""V6 (#28): browser-use refill agent tests. OpenAI (httpx2) and page fetches (httpx) are faked at the transport layer."""
from __future__ import annotations

import json

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI

from smallprint.browser_refill import SOURCE, browse_for_refill, find_refill_links
from smallprint.refill import DEFAULT_USAGE, SOURCE_DEFAULT_USAGE
from smallprint.spend import SpendTracker
from smallprint.tc_cache import TermsCache

PAGE_URL = "https://www.sodastream.co.uk/products/terra"
REFILL_URL = "https://www.sodastream.co.uk/products/co2-cylinder-60l"
SITE = "sodastream.co.uk"

PRODUCT_HTML = """
<html><body>
  <h1>SodaStream Terra Sparkling Water Maker</h1>
  <a href="/products/co2-cylinder-60l">SodaStream CO2 Cylinder 60L - Replacement</a>
  <a href="/about">About us</a>
  <a href="https://other.example/refill">External refill</a>
</body></html>
"""

REFILL_PAGE_TEXT = (
    "SodaStream CO2 Cylinder 60L — £14.99. "
    "Exchange your empty cylinder at a participating retailer. "
    "One cylinder makes up to 60 litres of sparkling water."
)

REFILL_HTML = f"<html><body><p>{REFILL_PAGE_TEXT}</p></body></html>"

GOOD_LLM = {
    "consumable": {"value": "SodaStream CO2 Cylinder 60L", "quote": "SodaStream CO2 Cylinder 60L — £14.99."},
    "pack_price": {"value": 14.99, "quote": "SodaStream CO2 Cylinder 60L — £14.99."},
    "units_per_pack": {"value": None, "quote": None},
    "replace_every_months": {"value": None, "quote": None},
}
NULL_LLM = {k: {"value": None, "quote": None} for k in GOOD_LLM}


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------

def test_refill_links_finds_same_site_refill_links():
    links = find_refill_links(PRODUCT_HTML, PAGE_URL, SITE)
    assert REFILL_URL in links  # "Replacement" in anchor text matches


def test_refill_links_excludes_other_sites():
    links = find_refill_links(PRODUCT_HTML, PAGE_URL, SITE)
    assert not any("other.example" in l for l in links)


def test_refill_links_excludes_non_refill_links():
    links = find_refill_links(PRODUCT_HTML, PAGE_URL, SITE)
    assert not any("/about" in l for l in links)


def test_refill_links_empty_on_no_matches():
    html = "<html><body><a href='/about'>About</a><a href='/contact'>Contact</a></body></html>"
    assert find_refill_links(html, PAGE_URL, SITE) == []


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class Fakes:
    def __init__(self, llm_json: dict | None = None, stop_reason: str = "stop",
                 product_html: str = PRODUCT_HTML, refill_html: str = REFILL_HTML,
                 refill_status: int = 200):
        self.llm_json = llm_json if llm_json is not None else GOOD_LLM
        self.stop_reason = stop_reason
        self.product_html = product_html
        self.refill_html = refill_html
        self.refill_status = refill_status
        self.llm_calls: list[dict] = []
        self.fetched_urls: list[str] = []

    def llm_handler(self, request: httpx2.Request) -> httpx2.Response:
        self.llm_calls.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant",
                "content": None if self.stop_reason == "refusal" else json.dumps(self.llm_json),
                "refusal": "No." if self.stop_reason == "refusal" else None}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 200, "total_tokens": 1700},
        })

    def http_handler(self, request: httpx.Request) -> httpx.Response:
        self.fetched_urls.append(str(request.url))
        if str(request.url) == PAGE_URL:
            return httpx.Response(200, text=self.product_html, headers={"content-type": "text/html"})
        return httpx.Response(self.refill_status, text=self.refill_html, headers={"content-type": "text/html"})

    def clients(self):
        client = AsyncOpenAI(api_key="t", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.llm_handler)))
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.http_handler))
        return client, http


async def _browse(f: Fakes, brand="SodaStream", tracker=None, cache=None):
    client, http = f.clients()
    return await browse_for_refill(
        client, http,
        name="Terra Sparkling Water Maker", brand=brand,
        page_url=PAGE_URL, install_id="i1",
        tracker=tracker or SpendTracker(1.0), cache=cache,
    )


# ---------------------------------------------------------------------------
# End-to-end behaviour
# ---------------------------------------------------------------------------

async def test_finds_refill_from_product_page_link():
    f = Fakes()
    stream = await _browse(f)
    assert stream is not None
    assert stream["unit_price"] == 14.99
    assert stream["evidence"]["url"] == REFILL_URL
    assert stream["evidence"]["source_step"] == SOURCE


async def test_fetches_product_page_then_refill_page():
    f = Fakes()
    await _browse(f)
    assert PAGE_URL in f.fetched_urls
    assert REFILL_URL in f.fetched_urls


async def test_uses_product_label_in_llm_prompt():
    f = Fakes()
    await _browse(f)
    assert len(f.llm_calls) == 1
    assert "SodaStream" in f.llm_calls[0]["messages"][1]["content"]
    assert "Terra" in f.llm_calls[0]["messages"][1]["content"]


async def test_no_refill_links_returns_none_without_llm_call():
    f = Fakes(product_html="<html><body><a href='/about'>About</a></body></html>")
    stream = await _browse(f)
    assert stream is None
    assert f.llm_calls == []


async def test_no_brand_returns_none():
    f = Fakes()
    assert await _browse(f, brand=None) is None
    assert await _browse(f, brand="  ") is None
    assert f.fetched_urls == []


async def test_other_site_links_are_not_followed():
    html = '<html><body><a href="https://other.example/sodastream-co2">SodaStream replacement</a></body></html>'
    f = Fakes(product_html=html)
    stream = await _browse(f)
    assert stream is None
    assert not any("other.example" in u for u in f.fetched_urls)


async def test_failed_refill_page_fetch_is_skipped():
    f = Fakes(refill_status=404)
    stream = await _browse(f)
    assert stream is None
    assert f.llm_calls == []


async def test_wrong_brand_on_refill_page_returns_none():
    f = Fakes()
    stream = await _browse(f, brand="Philips")
    assert stream is None


async def test_default_usage_when_no_interval_stated():
    no_interval = {**GOOD_LLM, "replace_every_months": {"value": None, "quote": None}}
    f = Fakes(llm_json=no_interval)
    stream = await _browse(f)
    assert stream["units_per_month"] == DEFAULT_USAGE
    assert stream["evidence"]["source_step"] == SOURCE


async def test_spend_limit_stops_llm_calls():
    f = Fakes()
    stream = await _browse(f, tracker=SpendTracker(0.0))
    assert stream is None
    assert f.llm_calls == []


async def test_caches_found_result():
    cache = TermsCache()
    f = Fakes()
    first = await _browse(f, cache=cache)
    second = await _browse(f, cache=cache)
    assert first == second
    assert len(f.llm_calls) == 1


async def test_caches_not_found_when_fully_checked():
    cache = TermsCache()
    f = Fakes(llm_json=NULL_LLM)
    await _browse(f, cache=cache)
    await _browse(f, cache=cache)
    assert len(f.llm_calls) == 1


async def test_refusal_is_not_cached():
    cache = TermsCache()
    f = Fakes(stop_reason="refusal")
    await _browse(f, cache=cache)
    await _browse(f, cache=cache)
    assert len(f.llm_calls) == 2
