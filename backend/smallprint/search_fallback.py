"""Search fallback: when the extension couldn't fetch a T&C page, find it with Tavily (S6, #15).

One Tavily search per failed document, restricted to the failed page's own
website. Restricting the domain keeps us on the company the user is looking
at: a search across the whole web could return another company's terms,
which would be a wrong value.

Documents found this way carry ``source = "tavily_search"``, so every value
extracted from them is labelled with that source and links to the page the
quote came from. They go through the same extractor and quote verifier as
browser-fetched pages; nothing from a search snippet is shown unverified.

No bot evasion: one plain API call, no retries against the site itself.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import httpx

from smallprint.extract import Document

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
SOURCE = "tavily_search"
TIMEOUT_S = 8.0
MAX_RESULTS = 3
MAX_SEARCHES_PER_REQUEST = 2  # 1 credit each (search_depth "basic")

KIND_QUERY = {
    "terms": "terms and conditions",
    "returns": "returns policy",
    "warranty": "warranty",
    "cancel": "how to cancel",
    "subscription": "subscription terms",
    "contract_summary": "contract summary",
    "price_guide": "price guide",
    "privacy": "terms and conditions",
    "other": "terms and conditions",
}


def site_of(url: str) -> str | None:
    """Host without a leading www., or None if the URL has no host."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.") or None


def _same_site(url: str, site: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == site or host.endswith("." + site)


class TavilySearch:
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.http = http or httpx.AsyncClient(timeout=TIMEOUT_S)

    async def find_terms(self, failed_url: str, name: str | None, kind: str = "terms") -> list[Document]:
        """Documents on the failed page's site that look like its T&Cs. [] on any failure."""
        site = site_of(failed_url)
        if not site:
            return []
        query = " ".join(p for p in (name, KIND_QUERY.get(kind, "terms and conditions")) if p)
        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": MAX_RESULTS,
            "include_raw_content": "text",
            "include_domains": [site],
            "topic": "general",
            "country": "united kingdom",
        }
        try:
            resp = await self.http.post(TAVILY_URL, json=body, timeout=TIMEOUT_S,
                                        headers={"Authorization": f"Bearer {self.api_key}"})
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (httpx.HTTPError, ValueError):
            log.warning("tavily search failed for site=%s", site, exc_info=True)
            return []

        docs: list[Document] = []
        seen: set[str] = set()
        for r in results:
            url = r.get("url") or ""
            text = r.get("raw_content") or r.get("content") or ""
            # Defence in depth: Tavily restricts to the domain, but never accept another site.
            if not url or url in seen or not text.strip() or not _same_site(url, site):
                continue
            seen.add(url)
            docs.append(Document(url, text, source=SOURCE))
        log.info("tavily site=%s results=%d kept=%d", site, len(results), len(docs))
        return docs


def from_env() -> TavilySearch | None:
    key = os.environ.get("TAVILY_API_KEY")
    return TavilySearch(key) if key else None
