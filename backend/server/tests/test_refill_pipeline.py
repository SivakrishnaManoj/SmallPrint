"""S8 (#21): refill in /analyse. Gated: off unless SMALLPRINT_REFILL=1."""
from __future__ import annotations

import json

import httpx
import httpx2
import jsonschema
import pytest
from openai import AsyncOpenAI

from server import main
from smallprint.search_fallback import TavilySearch
from smallprint.test_refill import GOOD, PAGE, REFILL_URL

from .test_pipeline import RESPONSE_SCHEMA, assemble, cards, stream, tracker  # noqa: F401

PRODUCT = {
    "item": {"name": "Oral-B electric toothbrush", "brand": "Oral-B", "url": "https://www.amazon.co.uk/dp/B08H93ZRK9"},
    "purchase_type_signals": ["product"],
    "links": [],
    "page_text_snippets": [],
    "terms": [],
}


@pytest.fixture
def fakes(monkeypatch):
    calls = {"llm": 0, "tavily": []}

    def llm(request):
        calls["llm"] += 1
        return httpx2.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(GOOD), "refusal": None}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 200, "total_tokens": 1700}})

    def tavily(request):
        calls["tavily"].append(json.loads(request.content))
        return httpx.Response(200, json={"query": "q", "answer": None, "images": [], "response_time": 0.2,
                                         "results": [{"title": "t", "url": REFILL_URL, "content": "s", "score": 1,
                                                      "raw_content": PAGE}]})

    client = AsyncOpenAI(api_key="t", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(llm)))
    search = TavilySearch("tvly-t", http=httpx.AsyncClient(transport=httpx.MockTransport(tavily)))
    monkeypatch.setattr(main, "get_llm_client", lambda: client)
    monkeypatch.setattr(main, "get_search", lambda: search)
    return calls


async def test_gate_off_by_default_no_refill_lookup(fakes, tracker):
    by_card = cards(await stream(PRODUCT))
    assert fakes["llm"] == 0 and fakes["tavily"] == []
    # Lifetime cost doesn't apply to a one-off product unless a refill estimate is found.
    assert by_card["cost"]["state"] == "n_a"


async def test_gate_on_product_gets_an_estimated_refill_row(monkeypatch, fakes, tracker):
    monkeypatch.setenv("SMALLPRINT_REFILL", "1")
    by_card = cards(await stream(PRODUCT))

    cost = by_card["cost"]
    assert cost["state"] == "estimated"
    [row] = cost["payload"]["cost_streams"]
    assert row["type"] == "usage" and row["unit_price"] == 39.99
    assert set(row["units_per_month"]) == {"low", "mid", "high"}
    assert row["evidence"]["url"] == REFILL_URL and row["evidence"]["source_step"] == "refill_search"
    jsonschema.validate(assemble(by_card), RESPONSE_SCHEMA)
    assert fakes["tavily"][0]["include_domains"] == ["amazon.co.uk"]


async def test_gate_on_but_not_a_product_no_lookup(monkeypatch, fakes, tracker):
    monkeypatch.setenv("SMALLPRINT_REFILL", "1")
    await stream({**PRODUCT, "purchase_type_signals": ["subscription"]})
    assert fakes["llm"] == 0 and fakes["tavily"] == []
