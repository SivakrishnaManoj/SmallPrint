"""S5 (#18): /analyse streams real cards, each the moment its source resolves.

The real FastAPI app and the real OpenAI SDK run; only the LLM's HTTP
transport is faked (recorded replies from the S3 fixtures).
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import httpx2
import jsonschema
import pymupdf
import pytest
from openai import AsyncOpenAI
from httpx import ASGITransport, AsyncClient

from server import main, pipeline
from smallprint.spend import SpendTracker
from smallprint.verify import verify_quote

ROOT = Path(__file__).parent.parent.parent.parent
FIX = ROOT / "backend" / "smallprint" / "extract" / "tests" / "fixtures"
STREAM_EVENT = jsonschema.Draft202012Validator(json.loads((ROOT / "contracts" / "stream-event.schema.json").read_text()))
RESPONSE_SCHEMA = json.loads((ROOT / "contracts" / "response.schema.json").read_text())

GYM_TERMS = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
GYM_LLM = (FIX / "gym_llm.json").read_text(encoding="utf-8")
TERMS_URL = "https://fitbox.example/terms"
INSTALL = "install-s5-test"

REQUEST = {
    "item": {"name": "Fitbox Off-Peak", "brand": "Fitbox", "url": "https://fitbox.example/join", "price": 29.99},
    "purchase_type_signals": ["subscription"],
    "links": [],
    "page_text_snippets": [],
    "terms": [{"url": TERMS_URL, "kind": "terms", "text": GYM_TERMS}],
}


def _reply(text: str) -> dict:
    return {
        "id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text, "refusal": None}}],
        "usage": {"prompt_tokens": 2_000, "completion_tokens": 400, "total_tokens": 2_400},
    }


class FakeLLM:
    def __init__(self, reply: dict | None = None, delay: float = 0.0, status: int = 200):
        self.reply, self.delay, self.status = reply or _reply(GYM_LLM), delay, status
        self.calls = 0

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        return httpx2.Response(200, json=self.reply)

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(api_key="test", max_retries=0,
                              http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler)))


@pytest.fixture
def tracker(monkeypatch) -> SpendTracker:
    t = SpendTracker(daily_limit_usd=1.0)
    monkeypatch.setattr(main, "get_spend_tracker", lambda: t)
    return t


def use_llm(monkeypatch, fake: FakeLLM) -> FakeLLM:
    client = fake.client()
    monkeypatch.setattr(main, "get_llm_client", lambda: client)
    return fake


async def stream(body: dict, install: str = INSTALL) -> list[tuple[float, dict | None]]:
    """POST /analyse; return [(seconds since start, card event or None for done)]."""
    events: list[tuple[float, dict | None]] = []
    start = time.monotonic()
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        async with c.stream("POST", "/analyse", json=body, headers={"X-Install-Id": install}) as resp:
            assert resp.status_code == 200
            name = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip())
                    if name == "card":
                        assert not list(STREAM_EVENT.iter_errors(data)), data
                        events.append((time.monotonic() - start, data))
                    elif name == "done":
                        events.append((time.monotonic() - start, None))
    return events


def cards(events) -> dict[str, dict]:
    return {e["card"]: e for _, e in events if e is not None}


def assemble(by_card: dict[str, dict]) -> dict:
    """The streamed cards put back together as one response; must satisfy the contract."""
    return {
        "purchase_types": ["subscription"],
        "item": by_card["item"]["payload"],
        "cost_streams": by_card["cost"]["payload"]["cost_streams"],
        "lock_in": by_card["lock_in"]["payload"],
        "small_print": by_card["small_print"]["payload"],
        "company": by_card["company"]["payload"],
        "price_drift": by_card["price_drift"]["payload"],
        "card_states": {k: by_card[k]["state"] for k in ("cost", "lock_in", "small_print", "company", "price_drift")},
    }


# --- end to end ----------------------------------------------------------

async def test_streams_every_card_with_a_state_then_done(monkeypatch, tracker):
    fake = use_llm(monkeypatch, FakeLLM())
    events = await stream(REQUEST)

    assert events[-1][1] is None, "stream must end with done"
    by_card = cards(events)
    assert set(by_card) == {"item", "price_drift", "cost", "lock_in", "small_print", "company"}
    assert len(events) == 7  # six cards, one done, nothing repeated
    jsonschema.validate(assemble(by_card), RESPONSE_SCHEMA)
    assert fake.calls == 1

    assert by_card["item"]["state"] == "found"
    assert by_card["price_drift"]["state"] == "n_a"
    assert by_card["cost"]["state"] == "found"
    assert by_card["lock_in"]["state"] == "found"
    # Company matcher (J5) not wired yet: honest not_found, not the mock company.
    assert by_card["company"]["state"] == "not_found"
    assert by_card["company"]["payload"]["parent"] is None


async def test_every_found_value_has_a_verified_quote_and_url(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM())
    by_card = cards(await stream(REQUEST))

    for s in by_card["cost"]["payload"]["cost_streams"]:
        assert s["evidence"]["url"] == TERMS_URL and verify_quote(s["evidence"]["quote"], GYM_TERMS)
    for e in by_card["lock_in"]["payload"]["evidence"]:
        assert e["url"] == TERMS_URL and verify_quote(e["quote"], GYM_TERMS)
    for r in by_card["small_print"]["payload"]:
        assert r["url"] == TERMS_URL and verify_quote(r["quote"], GYM_TERMS)


async def test_page_cards_arrive_first_and_fast_while_extraction_runs(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM(delay=0.5))
    events = await stream(REQUEST)
    order = [e["card"] for _, e in events if e is not None]
    t = {e["card"]: at for at, e in events if e is not None}

    assert order.index("item") < order.index("cost")
    assert order.index("company") < order.index("cost")
    assert t["item"] < 2.0  # page-derived cards under 2 s
    assert t["cost"] >= 0.5  # waited for the LLM, so it really streamed later


async def test_spend_is_charged_to_the_header_install_id(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM())
    await stream(REQUEST, install="install-charged")
    assert tracker.spent("install-charged") > 0
    assert tracker.spent(INSTALL) == 0


async def test_spend_limit_gives_limit_reached_and_no_llm_call(monkeypatch):
    monkeypatch.setattr(main, "get_spend_tracker", lambda: SpendTracker(daily_limit_usd=0.0))
    fake = use_llm(monkeypatch, FakeLLM())
    by_card = cards(await stream(REQUEST))
    assert fake.calls == 0
    assert {by_card[c]["state"] for c in ("cost", "lock_in", "small_print")} == {"limit_reached"}
    assert by_card["item"]["state"] == "found"


# --- failures still resolve every card -----------------------------------

async def test_extraction_timeout_resolves_as_not_found(monkeypatch, tracker):
    monkeypatch.setattr(pipeline, "TERMS_TIMEOUT_S", 0.2)
    use_llm(monkeypatch, FakeLLM(delay=5))
    events = await stream(REQUEST)
    by_card = cards(events)
    assert events[-1][1] is None
    assert {by_card[c]["state"] for c in ("cost", "lock_in", "small_print")} == {"not_found"}
    assert events[-1][0] < 3


async def test_llm_error_resolves_as_not_found(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM(status=500))
    events = await stream(REQUEST)
    by_card = cards(events)
    assert events[-1][1] is None
    assert {by_card[c]["state"] for c in ("cost", "lock_in", "small_print")} == {"not_found"}
    assert by_card["item"]["state"] == "found"


async def test_no_terms_and_no_page_text_makes_no_llm_call(monkeypatch, tracker):
    fake = use_llm(monkeypatch, FakeLLM())
    by_card = cards(await stream({**REQUEST, "terms": []}))
    assert fake.calls == 0
    assert by_card["cost"]["state"] == "not_found"


async def test_failed_fetches_are_skipped(monkeypatch, tracker):
    fake = use_llm(monkeypatch, FakeLLM())
    body = {**REQUEST, "terms": [{"url": "https://blocked.example/terms", "fetch_failed": True, "error": "HTTP 403"}]}
    by_card = cards(await stream(body))
    assert fake.calls == 0  # no Tavily key in tests, so no fallback; see test_fallback_pipeline.py
    assert by_card["lock_in"]["state"] == "not_found"


# --- documents -----------------------------------------------------------

def _req(**kw):
    from server.models import AnalyseRequest
    return AnalyseRequest.model_validate({**REQUEST, **kw})


def test_documents_page_text_first_then_terms():
    docs = pipeline.build_documents(_req(page_text_snippets=["£29.99 a month", "  "]))
    assert [d.url for d in docs] == ["https://fitbox.example/join", TERMS_URL]
    assert docs[0].text == "£29.99 a month"


def test_documents_html_text_and_pdf():
    html = (FIX / "retail_returns.html").read_text(encoding="utf-8")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Your membership has a minimum term of 12 months.")
    terms = [
        {"url": "https://retail.example/returns", "text": html},
        {"url": "https://fitbox.example/terms.pdf", "pdf_b64": base64.b64encode(pdf.tobytes()).decode()},
        {"url": "https://bad.example/terms.pdf", "pdf_b64": base64.b64encode(b"not a pdf").decode()},
    ]
    docs = pipeline.build_documents(_req(terms=terms))
    assert [d.url for d in docs] == ["https://retail.example/returns", "https://fitbox.example/terms.pdf"]
    assert "<p>" not in docs[0].text and "window.track" not in docs[0].text
    assert "minimum term of 12 months" in docs[1].text


# --- mock mode is unchanged ----------------------------------------------

async def test_without_an_api_key_the_mock_still_streams():
    by_card = cards(await stream(REQUEST))
    assert set(by_card) == {"item", "price_drift", "cost", "lock_in", "small_print", "company"}


# --- product-only purchases: lifetime cost and lock-in don't apply --------
# 40-URL run 2026-11-08: Amazon products showed "£37.82 a month" (the price) and
# finance offers as a monthly fee, and a protection policy's notice period as lock-in.
# Verbatim quotes, wrong meaning. Lifetime cost and lock-in are for subscriptions and contracts.

async def test_product_only_purchase_has_no_cost_or_lock_in(monkeypatch, tracker):
    use_llm(monkeypatch, FakeLLM())
    sub = cards(await stream(REQUEST))
    use_llm(monkeypatch, FakeLLM())
    prod = cards(await stream({**REQUEST, "purchase_type_signals": ["product"]}, install="install-product"))

    assert prod["cost"]["state"] == "n_a"
    assert prod["cost"]["payload"]["cost_streams"] == []
    assert prod["lock_in"]["state"] == "n_a"
    assert prod["lock_in"]["payload"]["evidence"] == []
    assert all(v is None for k, v in prod["lock_in"]["payload"].items() if k != "evidence")
    # Returns window, warranty and seller still apply to a product.
    assert prod["small_print"] == sub["small_print"]
    jsonschema.validate(assemble(prod), RESPONSE_SCHEMA)


@pytest.mark.parametrize("signals", [["product", "subscription"], ["product", "contract"], []])
async def test_cost_and_lock_in_kept_unless_the_page_is_only_a_product(monkeypatch, tracker, signals):
    use_llm(monkeypatch, FakeLLM())
    by_card = cards(await stream({**REQUEST, "purchase_type_signals": signals}))
    assert by_card["cost"]["state"] == "found"
    assert by_card["lock_in"]["state"] == "found"
