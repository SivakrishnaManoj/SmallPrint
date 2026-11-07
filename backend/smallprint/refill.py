"""Refill cost for products (S8, #21). GATED: ships only if the H10 gate passes.

For a product, find the consumable it uses (CO2 cylinder, ink cartridge, razor
blades, ...) and that consumable's price, with a source, and return it as a
`usage` cost stream the panel's slider can recalculate locally.

How:
  1. One Tavily search for the brand's refill, restricted to amazon.co.uk and
     the product page's own site.
  2. Haiku reads each result page (first chunk only) and fills a fixed form.
     Every value needs a verbatim quote, checked by the quote verifier, and
     prices must appear as digits in their quote.
  3. The brand name must appear in the consumable's or the price's quote, so
     another brand's refill can't be attached to this product (no fuzzy matching).

Usage (`units_per_month`) is an estimate, labelled as one:
  * If the page states a replacement interval ("replace every 3 months"), mid is
    one pack per that interval, low half of it, high double. source_step
    "refill_search".
  * Otherwise a default range (0.25 / 0.5 / 1 packs a month) the user adjusts with
    the slider. source_step "refill_search_default_usage".

No refill found means no usage stream: the panel shows "Running costs: not estimated".
"""
from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

from smallprint.extract.extractor import _extract_chunk, _field_schema, _number_in_quote
from smallprint.extract.text import chunk_text
from smallprint.search_fallback import TavilySearch, site_of
from smallprint.spend import SpendLimitReached, SpendTracker
from smallprint.tc_cache import TermsCache
from smallprint.verify import verify_field

log = logging.getLogger(__name__)

AMAZON_UK = "amazon.co.uk"
SOURCE = "refill_search"
SOURCE_DEFAULT_USAGE = "refill_search_default_usage"
DEFAULT_USAGE = {"low": 0.25, "mid": 0.5, "high": 1.0}  # packs per month
CHUNK_TOKENS = 4_000

REFILL_FIELDS: dict[str, str] = {
    "consumable": "string",            # e.g. "SodaStream CO2 cylinder 60L"
    "pack_price": "number",            # GBP for one pack as sold
    "units_per_pack": "integer",       # how many consumables in that pack
    "replace_every_months": "number",  # stated replacement interval per unit
}

REFILL_SCHEMA: dict = {
    "type": "object",
    "properties": {name: _field_schema(t) for name, t in REFILL_FIELDS.items()},
    "required": list(REFILL_FIELDS),
    "additionalProperties": False,
}

REFILL_PROMPT = """You find the replacement consumable for a product, and its price, on a UK retail page.

The user message names the product. The document is a web page. Find the consumable this product needs replacing (refills, cartridges, capsules, blades, brush heads, filters, cylinders) and its price in GBP.

Rule: every field needs a quote copied character for character from the document. If you cannot quote it, return null for both value and quote. Never guess or use outside knowledge. If the page is about a different brand or product, return null for every field.

Fields:
- consumable (string): the consumable's name as the page states it, including the brand.
- pack_price (number): the price in GBP of one pack, as digits from the quote.
- units_per_pack (integer): how many consumables are in that pack, if stated.
- replace_every_months (number): how often one unit should be replaced, in months, only if the page states it with a number (e.g. "replace every 3 months").

Example. Document: "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99. Replace your brush head every 3 months."
Output: consumable = {"value": "Oral-B iO Replacement Brush Heads", "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."}, pack_price = {"value": 39.99, "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."}, units_per_pack = {"value": 4, "quote": "Oral-B iO Replacement Brush Heads, Pack of 4 - £39.99."}, replace_every_months = {"value": 3, "quote": "Replace your brush head every 3 months."}.
"""


def _verified(raw: dict[str, Any], name: str, text: str) -> dict | None:
    item = raw.get(name)
    if not isinstance(item, dict):
        return None
    ok = verify_field(item, text)
    if ok is None:
        return None
    value = ok["value"]
    if REFILL_FIELDS[name] in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        if not _number_in_quote(value, ok["quote"]):
            return None
        if REFILL_FIELDS[name] == "integer" and not float(value).is_integer():
            return None
    elif not (isinstance(value, str) and value.strip()):
        return None
    return {"value": value, "quote": ok["quote"]}


def verify_refill(raw: dict[str, Any], text: str, brand: str, url: str) -> dict | None:
    """A usage cost stream from one page's extraction, or None if it doesn't hold up."""
    consumable = _verified(raw, "consumable", text)
    price = _verified(raw, "pack_price", text)
    if consumable is None or price is None:
        return None
    b = brand.casefold()
    if b not in consumable["quote"].casefold() and b not in price["quote"].casefold():
        return None  # can't show it's this brand's refill

    pack = _verified(raw, "units_per_pack", text)
    per_pack = int(pack["value"]) if pack else 1
    interval = _verified(raw, "replace_every_months", text)
    if interval:
        mid = 1 / (float(interval["value"]) * per_pack)  # packs per month
        usage = {"low": round(mid / 2, 3), "mid": round(mid, 3), "high": round(mid * 2, 3)}
        source = SOURCE
    else:
        usage = dict(DEFAULT_USAGE)
        source = SOURCE_DEFAULT_USAGE

    label = f"Refill: {consumable['value']}" + (f" (pack of {per_pack})" if per_pack > 1 else "")
    return {
        "label": label,
        "type": "usage",
        "unit_price": float(price["value"]),
        "units_per_month": usage,
        "evidence": {"quote": price["quote"], "url": url, "source_step": source},
    }


async def find_refill(client: AsyncAnthropic, search: TavilySearch, *, name: str | None, brand: str | None,
                      page_url: str, install_id: str, tracker: SpendTracker | None,
                      cache: TermsCache | None = None) -> dict | None:
    """The refill as a `usage` cost stream, or None ("Running costs: not estimated")."""
    if not brand or not brand.strip():
        return None  # no brand, no way to check the refill is for this product
    key = f"{site_of(page_url)}|{brand.casefold()}|{(name or '').casefold()}"
    if cache is not None:
        hit = cache.get_refill(key)
        if hit is not None:
            return hit.get("stream")

    sites = [AMAZON_UK]
    own = site_of(page_url)
    if own and own != AMAZON_UK and not own.endswith("." + AMAZON_UK):
        sites.append(own)
    query = f"{brand} {name or ''} replacement refill price".replace("  ", " ")
    docs = await search.search(query, sites, SOURCE)

    complete = True
    for doc in docs:
        chunk = chunk_text(doc.text, CHUNK_TOKENS)[:1]
        if not chunk:
            continue
        product = f"Product: {brand} {name or ''}".strip()
        try:
            raw = await _extract_chunk(client, f"{product}\n\n{chunk[0]}", install_id, tracker,
                                       system=REFILL_PROMPT, schema=REFILL_SCHEMA)
        except SpendLimitReached:
            return None  # not cached: try again tomorrow
        if raw is None:
            complete = False
            continue
        stream = verify_refill(raw, chunk[0], brand, doc.url)
        if stream:
            if cache is not None:
                cache.put_refill(key, {"stream": stream})
            return stream
    if cache is not None and complete and docs:
        cache.put_refill(key, {"stream": None})  # looked properly, nothing found
    return None
