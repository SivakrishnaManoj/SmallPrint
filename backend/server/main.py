"""FastAPI server for SmallPrint /analyse endpoint.

POST /analyse  — streams SSE card events. Real pipeline (server/pipeline.py) when
                 ANTHROPIC_API_KEY is set; otherwise the fixtures (mock mode).
GET  /health   — liveness check
"""
from __future__ import annotations
import asyncio
import json
import os
import random
from typing import AsyncGenerator

from anthropic import AsyncAnthropic
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from smallprint import search_fallback
from smallprint.search_fallback import TavilySearch
from smallprint.spend import SpendTracker, tracker as default_tracker

from .fixtures import pick_fixture
from .models import AnalyseRequest
from .pipeline import stream_real
from .rate_limit import check as rate_check

_llm_client: AsyncAnthropic | None = None


def get_llm_client() -> AsyncAnthropic | None:
    """The Anthropic client, or None in mock mode (no ANTHROPIC_API_KEY)."""
    global _llm_client
    if _llm_client is None and os.environ.get("ANTHROPIC_API_KEY"):
        _llm_client = AsyncAnthropic()
    return _llm_client


def get_spend_tracker() -> SpendTracker:
    return default_tracker


_search: TavilySearch | None = None


def get_search() -> TavilySearch | None:
    """Tavily search for failed T&C fetches, or None without TAVILY_API_KEY (no fallback)."""
    global _search
    if _search is None:
        _search = search_fallback.from_env()
    return _search

app = FastAPI(title="SmallPrint API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"(chrome-extension://.*|http://localhost(:\d+)?)",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Integration stubs — replace these with real module calls at H6
# ---------------------------------------------------------------------------

async def terms_source(request: AnalyseRequest, fixture: dict) -> dict:
    """Stub: returns cost_streams, lock_in and small_print slices from fixture.

    Real implementation will call:
        from smallprint.terms import analyse_terms
        return await analyse_terms(request)
    """
    return {
        "cost_streams": fixture.get("cost_streams", []),
        "lock_in": fixture.get("lock_in", {}),
        "small_print": fixture.get("small_print", []),
    }


async def company_source(request: AnalyseRequest, fixture: dict) -> dict:
    """Stub: returns company slice from fixture.

    Real implementation will call:
        from smallprint.company import company_lookup
        brand = request.item.brand or ""
        domain = request.item.url
        return await company_lookup(brand, domain)
    """
    return {"company": fixture.get("company", {})}


# ---------------------------------------------------------------------------
# Card emission order
# ---------------------------------------------------------------------------

# Delay between mock cards, in seconds, so the panel shows cards streaming in.
# Tests set this to (0, 0); see server/tests/conftest.py.
CARD_DELAY_SECONDS: tuple[float, float] = (0.3, 0.8)

_CARD_ORDER = ["item", "price_drift", "cost", "lock_in", "small_print", "company"]

_CARD_PAYLOAD_MAP = {
    "item": lambda r: r.get("item", {}),
    "price_drift": lambda r: r.get("price_drift", {}),
    "cost": lambda r: {"cost_streams": r.get("cost_streams", [])},
    "lock_in": lambda r: r.get("lock_in", {}),
    "small_print": lambda r: r.get("small_print", []),
    "company": lambda r: r.get("company", {}),
}


def _card_state(card: str, result: dict) -> str:
    states = result.get("card_states", {})
    state_key = {
        "cost": "cost",
        "lock_in": "lock_in",
        "small_print": "small_print",
        "company": "company",
        "price_drift": "price_drift",
        "item": "cost",  # item card uses overall cost state as proxy
    }.get(card, "cost")
    return states.get(state_key, "not_found")


async def _stream_cards(result: dict) -> AsyncGenerator[dict, None]:
    for card in _CARD_ORDER:
        await asyncio.sleep(random.uniform(*CARD_DELAY_SECONDS))
        payload = _CARD_PAYLOAD_MAP[card](result)
        state = _card_state(card, result)
        yield {
            "event": "card",
            "data": json.dumps({"card": card, "state": state, "payload": payload}),
        }
    yield {"event": "done", "data": "{}"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/analyse")
async def analyse(
    request: AnalyseRequest,
    http_request: Request,
    x_install_id: str | None = Header(default=None),
) -> EventSourceResponse:
    # Install UUID comes from the X-Install-Id header; the body field is a fallback.
    install_id = (x_install_id or "").strip() or request.install_id
    if not install_id:
        raise HTTPException(status_code=422, detail="Missing X-Install-Id header")
    if not rate_check(install_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    client = get_llm_client()
    if client is not None:
        return EventSourceResponse(stream_real(request, install_id, client, get_spend_tracker(), get_search()))

    # Mock mode: no API key configured, serve the fixtures.
    fixture = pick_fixture(request.item.url, request.item.name)

    # Fan out to source stubs in parallel (mirrors the real asyncio.gather pattern)
    terms_result, company_result = await asyncio.gather(
        terms_source(request, fixture),
        company_source(request, fixture),
    )

    # Merge stub results back into the fixture so card states remain consistent
    result = {**fixture, **terms_result, **company_result}

    return EventSourceResponse(_stream_cards(result))
