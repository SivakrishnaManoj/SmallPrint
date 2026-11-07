"""FastAPI server for SmallPrint /analyse endpoint.

POST /analyse  — streams SSE card events from fixtures (integration stubs below)
GET  /health   — liveness check
"""
from __future__ import annotations
import asyncio
import json
import random
from typing import AsyncGenerator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .fixtures import pick_fixture
from .models import AnalyseRequest
from .rate_limit import check as rate_check

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

    fixture = pick_fixture(request.item.url, request.item.name)

    # Fan out to source stubs in parallel (mirrors the real asyncio.gather pattern)
    terms_result, company_result = await asyncio.gather(
        terms_source(request, fixture),
        company_source(request, fixture),
    )

    # Merge stub results back into the fixture so card states remain consistent
    result = {**fixture, **terms_result, **company_result}

    return EventSourceResponse(_stream_cards(result))
