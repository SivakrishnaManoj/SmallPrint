"""ASA rulings lookup (V5, #27).

Fetches published rulings from the ASA (Advertising Standards Authority) for
a given brand and returns them as dated, sourced records using factual
language — never verdict words.

Source: the ASA has no public JSON API. Its public rulings search page,
  https://www.asa.org.uk/codes-and-rulings/rulings.html?q=<brand>
is rendered on the server. The "Rulings" tab (``<ul id="tab-1">``) lists the
formal rulings, 20 per page. Each item has the advertiser name, a link to the
ruling, the outcome, the media type (sometimes missing) and the date. The
other tabs (informally resolved, mail order, database cases) are not rulings
and are ignored.

The search is full-text, not by advertiser: "Sky" also returns rulings for
other advertisers whose ads only mention the word. So a ruling is kept only
when its advertiser name matches the brand or the parent company
(``advertiser_matches``).

Language rules (enforced in _summarise):
  * A ruling is a published administrative decision, not a conviction.
    "ASA published a ruling on <date> concerning an advertisement by <brand>."
  * Outcome: "The complaint was upheld." / "...upheld in part." / "...not upheld."
  * Never: "found guilty", "broke the law", "unethical", "misleading" as a
    conclusion. The ASA's own one-line description of the ad is not shown.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx

log = logging.getLogger(__name__)

ASA_SEARCH_URL = "https://www.asa.org.uk/codes-and-rulings/rulings.html"
ASA_RULING_BASE = "https://www.asa.org.uk/rulings/"
TIMEOUT_S = 6.0
MAX_RESULTS = 10

# ---------------------------------------------------------------------------
# Language rules
# ---------------------------------------------------------------------------

_VERDICT_WORDS = re.compile(
    r"\b(guilty|convicted|unethical|illegal|fraudulent|lied|deceived|criminal)\b",
    re.I,
)

_DATE_FORMATS = ("%d %B %Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")

# The ASA writes outcomes several ways ("Not Upheld", "Part upheld", ...).
_OUTCOMES = {
    "upheld": "upheld",
    "true": "upheld",
    "yes": "upheld",
    "1": "upheld",
    "not upheld": "not upheld",
    "false": "not upheld",
    "no": "not upheld",
    "0": "not upheld",
    "rejected": "not upheld",
    "part upheld": "upheld in part",
    "partly upheld": "upheld in part",
    "upheld in part": "upheld in part",
}


def _clean(text: str | None) -> str:
    """Strip leading/trailing whitespace and collapse internal runs."""
    if not text:
        return ""
    return " ".join(text.split())


def _iso_date(raw: str) -> str:
    """``raw`` as YYYY-MM-DD if it is in a known format, else unchanged."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def _outcome(value: object) -> str:
    """'upheld', 'upheld in part', 'not upheld', or '' when unknown."""
    if value is None:
        return ""
    return _OUTCOMES.get(str(value).strip().lower(), "")


def _summarise(item: dict) -> str:
    """Build a factual summary from one ruling item.

    The summary states what happened (a ruling was published) and the
    outcome, never reaching a verdict on the brand.
    """
    brand = _clean(item.get("advertiserName") or item.get("advertiser") or "")
    date_iso = _iso_date(_clean(item.get("date") or item.get("publishedDate") or ""))
    category = _clean(item.get("productCategory") or item.get("category") or "")
    media = _clean(item.get("media") or "")
    outcome = _outcome(item.get("upheld") if "upheld" in item else item.get("outcome"))

    parts = [f"ASA published a ruling on {date_iso} concerning an advertisement"]
    if brand:
        parts.append(f"by {brand}")
    if category:
        parts.append(f"in the {category} category")
    summary = " ".join(parts) + "."
    if media:
        summary += f" Media: {media}."
    if outcome:
        summary += f" The complaint was {outcome}."

    # Safety: if any verdict word slipped through the source data, redact it.
    return _VERDICT_WORDS.sub("[redacted]", summary)


def _to_record(item: dict) -> dict | None:
    """Convert one ruling item to a records-index dict, or None if unusable."""
    slug = _clean(item.get("slug") or item.get("id") or "")
    source_url = f"{ASA_RULING_BASE}{slug}" if slug else _clean(item.get("url") or "")
    date_raw = _clean(item.get("date") or item.get("publishedDate") or "")
    if not date_raw:
        return None

    summary = _summarise(item)
    if not summary:
        return None

    return {
        "kind": "asa_ruling",
        "date": _iso_date(date_raw),
        "summary": summary,
        "source_url": source_url or None,
    }


# ---------------------------------------------------------------------------
# Advertiser name matching
# ---------------------------------------------------------------------------

# Words that do not tell two companies apart: "PureGym Ltd" is "PureGym".
_NOISE_WORDS = {"the", "ltd", "limited", "plc", "llp", "llc", "inc", "co", "company", "uk", "group", "holdings"}
_TRADING_AS = re.compile(r"\s+(?:t/a|trading as)\s+", re.I)


def _name_key(name: str) -> str:
    """A comparable key: lower case, noise words dropped, letters and digits only.

    "Pure Gym Ltd" and "PureGym" both become "puregym".
    """
    words = re.findall(r"[a-z0-9&]+", name.casefold())
    return "".join(w for w in words if w not in _NOISE_WORDS)


def advertiser_matches(advertiser: str, names: list[str | None]) -> bool:
    """True if the advertiser, or the name it trades as, is one of ``names``.

    "Bonne Terre Ltd t/a Sky Bet" matches "Sky Bet" or "Bonne Terre Limited",
    not "Sky".
    """
    wanted = {_name_key(n) for n in names if n}
    wanted.discard("")
    if not wanted:
        return False
    return any(_name_key(part) in wanted for part in _TRADING_AS.split(advertiser))


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

_ITEM_SPLIT = re.compile(r'<li\s+class="icon-listing-item"\s*>')
_HEADING = re.compile(r'<h4\s+class="heading"\s*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_CAPTION = re.compile(r'<span\s+class="caption"\s*>(.*?)</span>', re.S)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return _clean(html_lib.unescape(_TAGS.sub(" ", fragment)))


def parse_rulings_html(page: str) -> list[dict]:
    """The formal rulings on one ASA search results page, as ruling items.

    Each item: {"advertiserName", "url", "date", "upheld", "media"}. Items
    without a heading link or a date are skipped.
    """
    start = page.find('id="tab-1"')
    if start == -1:
        return []
    end = page.find('class="toggle-tabs-panel-item', start)
    block = page[start:end if end != -1 else len(page)]

    items: list[dict] = []
    for chunk in _ITEM_SPLIT.split(block)[1:]:
        heading = _HEADING.search(chunk)
        if not heading:
            continue
        url = urljoin(ASA_RULING_BASE, html_lib.unescape(heading.group(1)))
        if not url.startswith(ASA_RULING_BASE):
            continue
        item: dict = {"advertiserName": _text(heading.group(2)), "url": url}
        media: list[str] = []
        for caption in (_text(c) for c in _CAPTION.findall(chunk)):
            if not caption:
                continue
            if _outcome(caption):
                item["upheld"] = caption
            elif _iso_date(caption) != caption:
                item["date"] = caption
            else:
                media.append(caption)
        if media:
            item["media"] = ", ".join(media)
        if item.get("date"):
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

async def fetch_asa_rulings(
    brand: str,
    *,
    parent: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Return ASA ruling records for ``brand``, newest first, or [] on any failure.

    Only rulings whose advertiser is ``brand`` or ``parent`` are kept.
    Each record: {"kind": "asa_ruling", "date": "YYYY-MM-DD", "summary": str, "source_url": str|None}
    """
    if not brand or not brand.strip():
        return []

    own_http = http is None
    if own_http:
        http = httpx.AsyncClient(
            headers={"Accept": "text/html", "User-Agent": "SmallPrint/1.0 (+https://smallprint.dev)"},
            follow_redirects=True,
        )

    try:
        resp = await http.get(ASA_SEARCH_URL, params={"q": brand.strip()}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        items = parse_rulings_html(resp.text)
    except httpx.HTTPError:
        log.debug("asa lookup failed for brand=%s", brand)
        return []
    finally:
        if own_http:
            await http.aclose()

    matched = [i for i in items if advertiser_matches(i["advertiserName"], [brand, parent])]
    records = [r for r in (_to_record(i) for i in matched) if r]
    records.sort(key=lambda r: r["date"], reverse=True)
    return records[:MAX_RESULTS]
