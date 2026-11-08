"""Browser-use refill agent (V6, #28).

When the Tavily search path (find_refill in refill.py) returns None,
this agent fetches the product page, finds links whose anchor text or
href suggests a refill or replacement, fetches those pages, and runs
the same Haiku extractor over them.

Read-only: httpx GET requests only. Never clicks, fills forms or buys.
Respects the same spend tracker and quote-verification rules as the search path.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlsplit

import httpx
from anthropic import AsyncAnthropic

from smallprint.extract.extractor import _extract_chunk
from smallprint.extract.text import chunk_text, html_to_text
from smallprint.refill import CHUNK_TOKENS, REFILL_PROMPT, REFILL_SCHEMA, verify_refill
from smallprint.search_fallback import _same_site, site_of
from smallprint.spend import SpendLimitReached, SpendTracker
from smallprint.tc_cache import TermsCache

log = logging.getLogger(__name__)

FETCH_TIMEOUT_S = 10.0
MAX_LINKS = 5   # candidate refill links to collect from the product page
MAX_PAGES = 3   # pages to actually fetch and extract from
SOURCE = "browse_refill"

_REFILL_WORDS = re.compile(
    r"\b(refill|replacement|cartridge|capsule|pod|blade|brush.?head|cylinder|filter|ink|toner|tip|accessori)\w*\b",
    re.I,
)
_LINK_RE = re.compile(r'<a\b[^>]*?\bhref=["\']([^"\']{2,})["\'][^>]*>(.*?)</a>', re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')
_HEADERS = {"User-Agent": "SmallPrint/1.0 (+https://smallprint.dev)", "Accept": "text/html"}


def find_refill_links(html: str, base_url: str, allowed_site: str) -> list[str]:
    """Links from ``html`` whose anchor text or path hints at a refill, same site only."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _LINK_RE.finditer(html):
        href = m.group(1).strip()
        text = _TAG_RE.sub("", m.group(2))
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        full = urljoin(base_url, href)
        parsed = urlsplit(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if not _same_site(full, allowed_site):
            continue
        if full in seen:
            continue
        if _REFILL_WORDS.search(text) or _REFILL_WORDS.search(parsed.path):
            seen.add(full)
            out.append(full)
        if len(out) >= MAX_LINKS:
            break
    return out


async def _fetch_html(http: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await http.get(url, timeout=FETCH_TIMEOUT_S, headers=_HEADERS, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except (httpx.HTTPError, UnicodeDecodeError):
        log.debug("browse_refill: fetch failed %s", url)
        return None


async def browse_for_refill(
    client: AsyncAnthropic,
    http: httpx.AsyncClient,
    *,
    name: str | None,
    brand: str | None,
    page_url: str,
    install_id: str,
    tracker: SpendTracker | None = None,
    cache: TermsCache | None = None,
) -> dict | None:
    """Find a refill price by navigating from the product page. Read-only.

    Returns a usage cost stream with source_step="browse_refill", or None.
    """
    if not brand or not brand.strip():
        return None

    allowed = site_of(page_url)
    if not allowed:
        return None

    cache_key = f"browse|{allowed}|{brand.casefold()}|{(name or '').casefold()}"
    if cache is not None:
        hit = cache.get_refill(cache_key)
        if hit is not None:
            return hit.get("stream")

<<<<<<< Updated upstream
=======
    # Step 1: fetch the product page and find refill links from it.
>>>>>>> Stashed changes
    product_html = await _fetch_html(http, page_url)
    if not product_html:
        return None

    links = find_refill_links(product_html, page_url, allowed)
    log.info("browse_refill: %d candidate link(s) found on %s", len(links), page_url)

    if not links:
        if cache is not None:
            cache.put_refill(cache_key, {"stream": None})
        return None

<<<<<<< Updated upstream
=======
    # Step 2: fetch each candidate and try extraction with the same Haiku + quote verifier.
>>>>>>> Stashed changes
    product_label = f"Product: {brand} {name or ''}".strip()
    complete = True
    for url in links[:MAX_PAGES]:
        html = await _fetch_html(http, url)
        if not html:
            complete = False
            continue
        text = html_to_text(html)
        if not text:
            complete = False
            continue
        chunks = chunk_text(text, CHUNK_TOKENS)
        if not chunks:
            continue
        try:
            raw = await _extract_chunk(
                client,
                f"{product_label}\n\n{chunks[0]}",
                install_id,
                tracker,
                system=REFILL_PROMPT,
                schema=REFILL_SCHEMA,
            )
        except SpendLimitReached:
            return None
        if raw is None:
            complete = False
            continue
        stream = verify_refill(raw, chunks[0], brand, url)
        if stream:
            stream["evidence"]["source_step"] = SOURCE
            if cache is not None:
                cache.put_refill(cache_key, {"stream": stream})
            return stream

    if cache is not None and complete:
        cache.put_refill(cache_key, {"stream": None})
    return None
