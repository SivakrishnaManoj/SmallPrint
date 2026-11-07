"""Real /analyse pipeline: run the lookups in parallel and stream each card as it resolves (S5, #18).

Sources, started together:
  * page   -> item and price_drift cards, straight from the request (well under 2 s)
  * terms  -> cost, lock_in and small_print cards, from the extractor (S3) under the
              per-install spend limit (S4), with a hard timeout so no spinner hangs
  * company -> company card. Until the company matcher (J5, #17) lands this is
              not_found: showing the mock company for a real page would be a wrong value.

Every card carries a state, a source that errors or times out still emits its cards
as not_found, and the stream always ends with `done`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Awaitable, Callable

from anthropic import AsyncAnthropic

from smallprint.extract import Document, analyse_documents, html_to_text, pdf_b64_to_text
from smallprint.spend import SpendTracker

from .models import AnalyseRequest

log = logging.getLogger(__name__)

# Extraction must stream within ~20 s (CLAUDE.md); give up a little after that.
TERMS_TIMEOUT_S = 25.0

Card = tuple[str, str, object]  # (card, state, payload)

TERMS_CARDS = ("cost", "lock_in", "small_print")
EMPTY_PAYLOAD: dict[str, object] = {
    "item": {},
    "price_drift": {"first_seen": None, "at_checkout": None, "added": []},
    "cost": {"cost_streams": []},
    "lock_in": {"evidence": []},
    "small_print": [],
    "company": {"brand": None, "parent": None, "ch_number": None, "match_via": None, "records": []},
}


def _not_found(cards: tuple[str, ...], state: str = "not_found") -> list[Card]:
    return [(c, state, EMPTY_PAYLOAD[c]) for c in cards]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

async def page_source(request: AnalyseRequest) -> list[Card]:
    item = request.item
    payload = {"name": item.name, "brand": item.brand, "seller": item.seller, "url": item.url, "id": item.id}
    # Price drift is worked out in the browser and never sent here (privacy rule).
    return [
        ("item", "found" if item.name else "not_found", payload),
        ("price_drift", "n_a", EMPTY_PAYLOAD["price_drift"]),
    ]


def _looks_like_html(text: str) -> bool:
    head = text[:2000].lower()
    return any(tag in head for tag in ("<html", "<body", "<div", "<p>", "<p ", "<main", "<article"))


def build_documents(request: AnalyseRequest) -> list[Document]:
    """Turn the request into the documents the extractor reads. Page text first."""
    docs: list[Document] = []
    snippets = "\n\n".join(s for s in request.page_text_snippets if s and s.strip())
    if snippets:
        docs.append(Document(request.item.url, snippets))
    for t in request.terms:
        if t.fetch_failed:
            continue  # Tavily fallback is S6 (#15)
        try:
            if t.text:
                text = html_to_text(t.text) if _looks_like_html(t.text) else t.text
            elif t.pdf_b64:
                text = pdf_b64_to_text(t.pdf_b64)
            else:
                continue
        except Exception:  # a corrupt PDF must not take the other documents down
            log.warning("could not read terms document %s", t.url, exc_info=True)
            continue
        if text.strip():
            docs.append(Document(t.url, text))
    return docs


async def terms_source(request: AnalyseRequest, install_id: str, client: AsyncAnthropic,
                       tracker: SpendTracker) -> list[Card]:
    docs = build_documents(request)
    if not docs:
        return _not_found(TERMS_CARDS)
    result = await asyncio.wait_for(analyse_documents(client, docs, install_id, tracker), TERMS_TIMEOUT_S)
    states = result["card_states"]
    return [
        ("cost", states["cost"], {"cost_streams": result["cost_streams"]}),
        ("lock_in", states["lock_in"], result["lock_in"]),
        ("small_print", states["small_print"], result["small_print"]),
    ]


async def company_source(request: AnalyseRequest) -> list[Card]:
    # J5 (#17) replaces this with brand -> parent -> Companies House number.
    return _not_found(("company",))


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def _event(card: Card) -> dict:
    name, state, payload = card
    return {"event": "card", "data": json.dumps({"card": name, "state": state, "payload": payload})}


async def stream_real(request: AnalyseRequest, install_id: str, client: AsyncAnthropic,
                      tracker: SpendTracker) -> AsyncGenerator[dict, None]:
    sources: list[tuple[tuple[str, ...], Callable[[], Awaitable[list[Card]]]]] = [
        (("item", "price_drift"), lambda: page_source(request)),
        (TERMS_CARDS, lambda: terms_source(request, install_id, client, tracker)),
        (("company",), lambda: company_source(request)),
    ]

    async def run(cards: tuple[str, ...], fn: Callable[[], Awaitable[list[Card]]]) -> list[Card]:
        try:
            return await fn()
        except asyncio.TimeoutError:
            log.warning("source %s timed out", cards)
        except Exception:
            log.exception("source %s failed", cards)
        return _not_found(cards)

    tasks = [asyncio.create_task(run(cards, fn)) for cards, fn in sources]
    try:
        for next_done in asyncio.as_completed(tasks):
            for card in await next_done:
                yield _event(card)
        yield {"event": "done", "data": "{}"}
    finally:
        # Client went away mid-stream: stop paying for lookups nobody will see.
        for t in tasks:
            t.cancel()
