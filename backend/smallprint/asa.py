"""ASA rulings lookup (V5, #27).

Fetches published rulings from the ASA (Advertising Standards Authority) for
a given brand name and returns them as dated, sourced records using factual
language — never verdict words, lawsuits only as allegations.

Language rules (enforced in _summarise):
  * A ruling is a published administrative decision, not a conviction.
    "ASA published a ruling on <date> concerning an advertisement by <brand>."
  * Where a ruling upheld a complaint: "The complaint was upheld."
    Where not upheld: "The complaint was not upheld."
  * Never: "found guilty", "broke the law", "unethical", "misleading" as a
    conclusion — only as a quoted claim if the ASA text uses that word.
  * Lawsuits/legal action are recorded as: "Legal proceedings were commenced
    alleging <X>." Never: "found liable", "convicted", "guilty".

The ASA provides a public JSON search at:
  https://api.asa.org.uk/api/v1/complaints/
No API key is required for read-only access.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx

log = logging.getLogger(__name__)

ASA_SEARCH_URL = "https://api.asa.org.uk/api/v1/complaints/"
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


def _clean(text: str | None) -> str:
    """Strip leading/trailing whitespace and collapse internal runs."""
    if not text:
        return ""
    return " ".join(text.split())


def _summarise(item: dict) -> str:
    """Build a factual summary from an ASA search result item.

    The summary states what happened (a ruling was published) and the
    outcome (upheld / not upheld), never reaching a verdict on the brand.
    """
    brand = _clean(item.get("advertiserName") or item.get("advertiser") or "")
    date_raw = _clean(item.get("date") or item.get("publishedDate") or "")
    category = _clean(item.get("productCategory") or item.get("category") or "")
    upheld_val = item.get("upheld") if "upheld" in item else item.get("outcome")
    upheld_raw = str(upheld_val).strip().lower() if upheld_val is not None else ""

    # Normalise date to YYYY-MM-DD if possible.
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            date_raw = datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue

    outcome = ""
    if upheld_raw in ("true", "yes", "1", "upheld"):
        outcome = " The complaint was upheld."
    elif upheld_raw in ("false", "no", "0", "not upheld", "rejected"):
        outcome = " The complaint was not upheld."

    parts = [f"ASA published a ruling on {date_raw} concerning an advertisement"]
    if brand:
        parts.append(f"by {brand}")
    if category:
        parts.append(f"in the {category} category")
    summary = " ".join(parts) + "." + outcome

    # Safety: if any verdict word slipped through the source data, redact it.
    summary = _VERDICT_WORDS.sub("[redacted]", summary)
    return summary


def _to_record(item: dict) -> dict | None:
    """Convert one ASA search result to a records-index dict, or None if unusable."""
    slug = _clean(item.get("slug") or item.get("id") or "")
    source_url = f"{ASA_RULING_BASE}{slug}" if slug else _clean(item.get("url") or "")
    date_raw = _clean(item.get("date") or item.get("publishedDate") or "")
    if not date_raw:
        return None

    # Normalise date.
    date_iso = date_raw
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            date_iso = datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue

    summary = _summarise(item)
    if not summary:
        return None

    return {
        "kind": "asa_ruling",
        "date": date_iso,
        "summary": summary,
        "source_url": source_url or None,
    }


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

async def fetch_asa_rulings(
    brand: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Return ASA ruling records for ``brand``, or [] on any failure.

    Each record: {"kind": "asa_ruling", "date": "YYYY-MM-DD", "summary": str, "source_url": str|None}
    """
    if not brand or not brand.strip():
        return []

    own_http = http is None
    if own_http:
        http = httpx.AsyncClient(
            headers={"Accept": "application/json", "User-Agent": "SmallPrint/1.0 (+https://smallprint.dev)"},
            follow_redirects=True,
        )

    try:
        resp = await http.get(
            ASA_SEARCH_URL,
            params={"q": brand, "page": 1, "pageSize": MAX_RESULTS},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        log.debug("asa lookup failed for brand=%s", brand)
        return []
    finally:
        if own_http:
            await http.aclose()

    items = data if isinstance(data, list) else (data.get("items") or data.get("results") or data.get("data") or [])
    records: list[dict] = []
    for item in items[:MAX_RESULTS]:
        r = _to_record(item)
        if r:
            records.append(r)
    return records
