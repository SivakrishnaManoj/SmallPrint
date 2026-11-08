"""Company matcher (J5, #17): brand → parent → Companies House number.

Chain (each step only runs if the previous found nothing):
  1. Wikidata SPARQL — look up brand label and official website (P856),
     follow owned-by (P127) / parent-org (P749) one level up,
     retrieve Companies House number (P1278) from the brand or its parent.
  2. GLEIF — search the Global LEI registry for the ultimate parent;
     extract the CH number from the UK registration-authority entity ID.
  3. Companies House — exact name search on the free Companies House API.
     Accepts only when the first result's title is a case-insensitive exact
     match for the brand name.

No fuzzy matching at any step.  "Brand not identified" is the only honest
answer when nothing matches — never a guess.

Records are joined on CH number only (strict).  No name-based join because
a name that looks the same can belong to a different company.

No verdict words: summaries come verbatim from the records index.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

log = logging.getLogger(__name__)

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
GLEIF_API       = "https://api.gleif.org/api/v1"
CH_API          = "https://api.company-information.service.gov.uk"

TIMEOUT_S   = 8.0
_DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "records.sqlite"

# ---------------------------------------------------------------------------
# SPARQL query
# ---------------------------------------------------------------------------

_SPARQL = """\
SELECT DISTINCT ?brand ?brandLabel ?parent ?parentLabel ?ch ?parentCh WHERE {{
  {{
    ?brand rdfs:label {brand_lit}@en .
    FILTER NOT EXISTS {{ ?brand wdt:P31 wd:Q5 . }}
  }} UNION {{
    ?brand wdt:P856 ?site .
    FILTER(CONTAINS(LCASE(STR(?site)), {domain_lit}))
  }}
  OPTIONAL {{
    {{ ?brand wdt:P127 ?parent . }} UNION {{ ?brand wdt:P749 ?parent . }}
    OPTIONAL {{ ?parent wdt:P1278 ?parentCh . }}
  }}
  OPTIONAL {{ ?brand wdt:P1278 ?ch . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
LIMIT 5"""


def _sparql_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _build_sparql(brand: str, domain: str) -> str:
    return _SPARQL.format(
        brand_lit=_sparql_str(brand),
        domain_lit=_sparql_str(domain.lower()),
    )


def _parse_wikidata(rows: list[dict]) -> tuple[str | None, str | None, str | None]:
    """Return (parent_name, ch_number, match_via) from SPARQL result rows."""
    for row in rows:
        ch = (row.get("ch", {}) or {}).get("value") or (row.get("parentCh", {}) or {}).get("value")
        parent = (row.get("parentLabel", {}) or {}).get("value") or (row.get("parent", {}) or {}).get("value")
        if ch or parent:
            ch_clean = ch.strip() if ch else None
            parent_clean = parent.strip() if parent else None
            return parent_clean, ch_clean, "Wikidata"
    return None, None, None


# ---------------------------------------------------------------------------
# GLEIF lookup
# ---------------------------------------------------------------------------

async def _gleif_lookup(http: httpx.AsyncClient, brand: str) -> tuple[str | None, str | None]:
    """Return (parent_name, ch_number) via GLEIF, or (None, None) on any failure.

    Uses the autocomplete-LEI endpoint, then walks the relationship to the
    ultimate parent, and reads the UK Companies House registration entity ID.
    """
    try:
        resp = await http.get(
            f"{GLEIF_API}/autocomplete-lei",
            params={"term": brand, "field": "entity.legalName"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        log.debug("gleif autocomplete failed for %s", brand)
        return None, None

    items = data.get("data") or []
    if not items:
        return None, None

    # Pick the first result whose name is a case-insensitive exact match.
    lei = None
    for item in items:
        name = (item.get("attributes") or {}).get("value") or ""
        if name.strip().casefold() == brand.casefold():
            lei = item.get("id") or ""
            break
    if not lei:
        return None, None

    # Walk to ultimate parent.
    try:
        resp = await http.get(
            f"{GLEIF_API}/lei-records/{lei}",
            params={"include": "ultimateAccountingConsolidatingParent"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        record = resp.json()
    except (httpx.HTTPError, ValueError):
        return None, None

    entity = (record.get("data") or {}).get("attributes", {}).get("entity", {})
    reg = entity.get("registeredAs") or ""
    reg_id = entity.get("registrationEntityId") or ""

    # registeredAs == "Companies House" means the ID is a CH number.
    parent_name = entity.get("legalName", {}).get("name")
    ch = reg_id if "companies house" in reg.lower() else None
    return parent_name, ch


# ---------------------------------------------------------------------------
# Companies House exact name lookup
# ---------------------------------------------------------------------------

async def _ch_lookup(http: httpx.AsyncClient, brand: str, api_key: str) -> tuple[str | None, str | None]:
    """Exact name match against Companies House search. Returns (name, ch_number) or (None, None)."""
    if not api_key:
        return None, None
    try:
        resp = await http.get(
            f"{CH_API}/search/companies",
            params={"q": brand, "items_per_page": 5},
            auth=(api_key, ""),
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        log.debug("companies house search failed for %s", brand)
        return None, None

    for item in (data.get("items") or []):
        title = (item.get("title") or "").strip()
        number = (item.get("company_number") or "").strip()
        if title.casefold() == brand.casefold() and number:
            return title, number
    return None, None


# ---------------------------------------------------------------------------
# Records index
# ---------------------------------------------------------------------------

def _load_records(ch_number: str, db_path: Path) -> list[dict]:
    """Return all records for this CH number, newest first. [] if DB absent."""
    if not db_path.exists():
        log.warning("records DB not found at %s", db_path)
        return []
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT kind, summary, date, source_url FROM records "
            "WHERE ch_number = ? ORDER BY date DESC",
            (ch_number,),
        ).fetchall()
        con.close()
    except sqlite3.Error:
        log.exception("records query failed for ch_number=%s", ch_number)
        return []
    return [{"kind": r[0], "summary": r[1], "date": r[2], "source_url": r[3]} for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _not_identified(brand: str) -> dict:
    return {
        "brand": brand,
        "parent": None,
        "ch_number": None,
        "match_via": "Brand not identified",
        "records": [],
    }


async def company_lookup(
    brand: str,
    domain: str,
    *,
    http: httpx.AsyncClient | None = None,
    db_path: Path | None = None,
    ch_api_key: str | None = None,
) -> dict:
    """Brand → parent → CH number.  Returns the company dict for the response schema.

    Injectable ``http``, ``db_path`` and ``ch_api_key`` for testing.
    Production callers pass nothing; defaults come from env / filesystem.
    """
    brand = (brand or "").strip()
    if not brand:
        return _not_identified("")

    domain = _extract_domain(domain)
    db_path = db_path or _DEFAULT_DB
    ch_api_key = ch_api_key if ch_api_key is not None else os.environ.get("COMPANIES_HOUSE_API_KEY", "")

    own_http = http is None
    if own_http:
        http = httpx.AsyncClient(
            headers={"User-Agent": "SmallPrint/1.0 (+https://smallprint.dev)", "Accept": "application/json"},
            follow_redirects=True,
        )

    try:
        # --- Step 1: Wikidata ---
        sparql = _build_sparql(brand, domain)
        parent, ch, via = None, None, None
        try:
            resp = await http.get(
                WIKIDATA_SPARQL,
                params={"query": sparql, "format": "json"},
                timeout=TIMEOUT_S,
            )
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("bindings", [])
            parent, ch, via = _parse_wikidata(rows)
        except (httpx.HTTPError, ValueError, KeyError):
            log.debug("wikidata lookup failed for brand=%s", brand)

        # --- Step 2: GLEIF (ultimate parent fallback) ---
        if not ch:
            gleif_parent, gleif_ch = await _gleif_lookup(http, brand)
            if gleif_ch:
                parent = gleif_parent or parent
                ch = gleif_ch
                via = "GLEIF"

        # --- Step 3: Companies House exact name ---
        if not ch:
            ch_name, ch_num = await _ch_lookup(http, brand, ch_api_key)
            if ch_num:
                parent = parent or ch_name
                ch = ch_num
                via = "Companies House exact name"

        if not ch:
            return _not_identified(brand)

        from smallprint.asa import fetch_asa_rulings
        db_records = _load_records(ch, db_path)
        asa_records = await fetch_asa_rulings(brand, http=http)
        return {
            "brand": brand,
            "parent": parent,
            "ch_number": ch,
            "match_via": via,
            "records": db_records + asa_records,
        }

    finally:
        if own_http:
            await http.aclose()


def _extract_domain(url_or_domain: str) -> str:
    """Return just the hostname without www., from a URL or bare domain."""
    s = url_or_domain.strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    host = (urlsplit(s).hostname or "").lower()
    return host.removeprefix("www.")
