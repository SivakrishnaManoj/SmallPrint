"""FastAPI server for SmallPrint /analyse endpoint.

POST /analyse  — streams SSE card events from fixtures (integration stubs below)
GET  /health   — liveness check

To switch to the real pipeline at 22:30, set the env var:
    SMALLPRINT_LIVE=1
Both modules must be importable (Person 2 and 3 hand-off complete).
"""
from __future__ import annotations
import asyncio
import json
import os
import random
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .fixtures import pick_fixture
from .models import AnalyseRequest
from .rate_limit import check as rate_check

# ---------------------------------------------------------------------------
# Live pipeline — imported lazily so the server starts even if not ready yet
# ---------------------------------------------------------------------------

LIVE = os.getenv("SMALLPRINT_LIVE", "").strip() == "1"

_analyse_terms = None
_company_lookup = None

if LIVE:
    try:
        from smallprint.terms import analyse_terms as _analyse_terms  # type: ignore[assignment]
    except ImportError as e:
        raise RuntimeError("SMALLPRINT_LIVE=1 but smallprint.terms is not available") from e
    try:
        from smallprint.company import company_lookup as _company_lookup  # type: ignore[assignment]
    except ImportError as e:
        raise RuntimeError("SMALLPRINT_LIVE=1 but smallprint.company is not available") from e

app = FastAPI(title="SmallPrint API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"(chrome-extension://.*|http://localhost(:\d+)?)",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Source functions — fixture stubs when LIVE=False, real pipeline when LIVE=True
# ---------------------------------------------------------------------------

async def terms_source(request: AnalyseRequest, fixture: dict) -> dict:
    if LIVE and _analyse_terms is not None:
        result = await asyncio.to_thread(_analyse_terms, request.model_dump())
        return {
            "cost_streams": result.get("cost_streams", []),
            "lock_in": result.get("lock_in", {}),
            "small_print": result.get("small_print", []),
            "card_states_terms": result.get("card_states", {}),
        }
    return {
        "cost_streams": fixture.get("cost_streams", []),
        "lock_in": fixture.get("lock_in", {}),
        "small_print": fixture.get("small_print", []),
    }


async def company_source(request: AnalyseRequest, fixture: dict) -> dict:
    if LIVE and _company_lookup is not None:
        brand = request.item.brand or ""
        domain = str(request.item.url or "")
        result = await asyncio.to_thread(_company_lookup, brand, domain)
        return {"company": result, "card_states_company": {"company": "found" if result.get("ch_number") else "not_found"}}
    return {"company": fixture.get("company", {})}


# ---------------------------------------------------------------------------
# Card emission order
# ---------------------------------------------------------------------------

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
        await asyncio.sleep(random.uniform(0.3, 0.8))
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
async def analyse(request: AnalyseRequest, http_request: Request) -> EventSourceResponse:
    if not rate_check(request.install_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    fixture = pick_fixture(request.item.url, request.item.name)

    # Fan out to source stubs in parallel (mirrors the real asyncio.gather pattern)
    terms_result, company_result = await asyncio.gather(
        terms_source(request, fixture),
        company_source(request, fixture),
    )

    # Merge results; live pipeline supplies its own card_states, stubs use fixture's
    card_states = {
        **fixture.get("card_states", {}),
        **terms_result.pop("card_states_terms", {}),
        **company_result.pop("card_states_company", {}),
    }
    result = {**fixture, **terms_result, **company_result, "card_states": card_states}

    return EventSourceResponse(_stream_cards(result))
