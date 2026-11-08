"""Company matcher (J5, #17): brand → parent → Companies House number.

Chain (each step only runs if the previous found nothing):
  1. Wikidata — find the brand with the wbsearchentities API (exact label or
     alias match only), then read its claims by ID with wbgetentities:
     Companies House company ID (P2622), parent organisation (P749) or a
     single current owner (P127), and official website (P856).  When several
     items share the name, the one whose website matches the page domain wins;
     otherwise the match must be unambiguous (one item with its own CH number,
     or a lone item with an official website).  Never a guess.
  2. GLEIF — exact legal-name match among GB LEI records registered at
     Companies House (registration authority RA000585); the CH number is the
     record's registeredAs value.
  3. Companies House — exact name search on the free Companies House API.
     Accepts only when a result's title is a case-insensitive exact match for
     the brand name.

No fuzzy matching at any step.  "Brand not identified" is the only honest
answer when nothing matches — never a guess.

Records are joined on CH number only (strict).  No name-based join because
a name that looks the same can belong to a different company.

No verdict words: summaries come verbatim from the records index.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
GLEIF_API       = "https://api.gleif.org/api/v1"
CH_API          = "https://api.company-information.service.gov.uk"

# Per request.  The whole Wikidata step is at most ~3 requests (search, claims,
# one batch of parents), so a healthy lookup stays well inside the 5 s target.
TIMEOUT_S   = 4.0
_DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "records.sqlite"

# Overall cap on the Wikidata step, so slow calls cannot add up past the 5 s target.
WIKIDATA_BUDGET_S = 3.5

GLEIF_COMPANIES_HOUSE_RA = "RA000585"
_MAX_PARENT_HOPS = 3
_CH_NUMBER_RE = re.compile(r"^(?:[A-Z]{2}\d{6}|\d{8})$")

# ---------------------------------------------------------------------------
# Wikidata lookup
# ---------------------------------------------------------------------------

_WD_HEADERS = {"Accept": "application/json"}


def _normalise_ch_number(value: str | None) -> str | None:
    """A valid Companies House number (8 digits, or 2 letters + 6 digits), or None.

    Wikidata sometimes drops leading zeros, so purely numeric values are
    zero-padded to 8 digits.  Anything else that does not fit is discarded.
    """
    v = (value or "").strip().upper().replace(" ", "")
    if v.isdigit() and 0 < len(v) < 8:
        v = v.zfill(8)
    return v if _CH_NUMBER_RE.match(v) else None


def _claim_values(entity: dict, prop: str) -> list:
    """Current (no end-time qualifier), non-deprecated main values of a claim."""
    values = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        if claim.get("rank") == "deprecated" or "P582" in (claim.get("qualifiers") or {}):
            continue
        value = (claim.get("mainsnak", {}).get("datavalue") or {}).get("value")
        if value is not None:
            values.append(value)
    return values


def _claim_ids(entity: dict, prop: str) -> list[str]:
    return [v["id"] for v in _claim_values(entity, prop) if isinstance(v, dict) and v.get("id")]


def _entity_label(entity: dict) -> str | None:
    return ((entity.get("labels") or {}).get("en") or {}).get("value")


def _hosts_match(a: str, b: str) -> bool:
    """Same host, or one is a subdomain of the other (www. already stripped)."""
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _site_hosts(entity: dict) -> list[str]:
    hosts = []
    for url in _claim_values(entity, "P856"):
        if isinstance(url, str):
            host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
            if host:
                hosts.append(host)
    return hosts


def _is_human(entity: dict) -> bool:
    return "Q5" in _claim_ids(entity, "P31")


def _parent_ids(entity: dict) -> list[str]:
    """Parent organisation (P749); else the owner (P127) only if there is exactly one.

    P127 on a big company often lists many shareholders.  Calling one of them
    "the parent" would be a guess, so several owners mean no parent.
    """
    parents = _claim_ids(entity, "P749")
    if parents:
        return parents
    owners = _claim_ids(entity, "P127")
    return owners if len(owners) == 1 else []


def _pick_candidate(candidates: dict[str, dict], domain: str) -> str | None:
    """Choose one Wikidata item for the brand, or None if it is ambiguous."""
    substantial = {
        qid: e for qid, e in candidates.items()
        if not _is_human(e)
        and (_claim_values(e, "P2622") or _parent_ids(e) or _site_hosts(e))
    }
    if domain:
        by_domain = [q for q, e in substantial.items() if any(_hosts_match(h, domain) for h in _site_hosts(e))]
        if len(by_domain) == 1:
            return by_domain[0]
    with_ch = [q for q, e in substantial.items() if _normalise_ch_number(next(iter(_claim_values(e, "P2622")), None))]
    if len(with_ch) == 1:
        return with_ch[0]
    # No candidate has its own CH number.  Accept a lone candidate only if it has
    # an official website: real brands do, while stores and one-off items rarely.
    with_site = [q for q, e in substantial.items() if _site_hosts(e)]
    if not with_ch and len(substantial) == 1 and len(with_site) == 1:
        return with_site[0]
    return None


async def _wd_entities(http: httpx.AsyncClient, ids: list[str]) -> dict[str, dict]:
    resp = await http.get(
        WIKIDATA_API,
        params={
            "action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels",
            "languages": "en", "format": "json",
        },
        headers=_WD_HEADERS, timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    return {k: v for k, v in (resp.json().get("entities") or {}).items() if "missing" not in v}


async def _wikidata_lookup(
    http: httpx.AsyncClient, brand: str, domain: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (parent_name, ch_number, "Wikidata"), or (None, None, None).

    Any network or parsing failure counts as "not found" so the later steps still run.
    """
    try:
        resp = await http.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities", "search": brand, "language": "en",
                "type": "item", "limit": 50, "format": "json",
            },
            headers=_WD_HEADERS, timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        wanted = brand.casefold()
        ids = []
        for hit in resp.json().get("search") or []:
            text = ((hit.get("match") or {}).get("text") or hit.get("label") or "")
            if text.strip().casefold() == wanted and hit.get("id"):
                ids.append(hit["id"])
        if not ids:
            return None, None, None

        entities = await _wd_entities(http, ids)
        qid = _pick_candidate(entities, domain)
        if qid is None:
            return None, None, None

        entity = entities[qid]
        own_ch = _normalise_ch_number(next(iter(_claim_values(entity, "P2622")), None))
        parents = _parent_ids(entity)
        parent_name: str | None = None
        ch = own_ch

        # Walk up (breadth-first, at most _MAX_PARENT_HOPS levels) until some
        # ancestor has a Companies House number.
        frontier, seen = parents, {qid}
        for hop in range(_MAX_PARENT_HOPS):
            frontier = [p for p in frontier if p not in seen]
            if not frontier:
                break
            seen.update(frontier)
            level = await _wd_entities(http, frontier)
            if hop == 0:
                parent_name = next((_entity_label(level[p]) for p in frontier if p in level and _entity_label(level[p])), None)
            nxt: list[str] = []
            for pid in frontier:
                pe = level.get(pid)
                if not pe:
                    continue
                if ch is None:
                    pch = _normalise_ch_number(next(iter(_claim_values(pe, "P2622")), None))
                    if pch:
                        ch = pch
                        parent_name = _entity_label(pe) or parent_name
                nxt.extend(_parent_ids(pe))
            if ch is not None:
                break
            frontier = nxt

        if ch is None and parent_name is None:
            return None, None, None
        return parent_name, ch, "Wikidata"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.debug("wikidata lookup failed for brand=%s", brand)
        return None, None, None


# ---------------------------------------------------------------------------
# GLEIF lookup
# ---------------------------------------------------------------------------

async def _gleif_lookup(http: httpx.AsyncClient, brand: str) -> tuple[str | None, str | None]:
    """Return (legal_name, ch_number) via GLEIF, or (None, None) on any failure.

    Queries the GB LEI records whose legal name matches, then keeps only a record
    whose legal name equals the brand exactly (case-insensitive) and that is
    registered at Companies House (RA000585).  The CH number is ``registeredAs``.
    """
    try:
        resp = await http.get(
            f"{GLEIF_API}/lei-records",
            params={
                "filter[entity.legalName]": brand,
                "filter[entity.legalAddress.country]": "GB",
                "page[size]": 10,
            },
            headers={"Accept": "application/vnd.api+json"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        log.debug("gleif lookup failed for %s", brand)
        return None, None

    for item in data.get("data") or []:
        entity = (item.get("attributes") or {}).get("entity") or {}
        name = ((entity.get("legalName") or {}).get("name") or "").strip()
        if name.casefold() != brand.casefold():
            continue
        if ((entity.get("registeredAt") or {}).get("id")) != GLEIF_COMPANIES_HOUSE_RA:
            continue
        ch = _normalise_ch_number(entity.get("registeredAs"))
        if ch:
            return name, ch
    return None, None


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

def _load_records(ch_number: str, db_path: Path, names: tuple[str, ...] = ()) -> list[dict]:
    """Return records for this company, newest first. [] if DB absent.

    Two join paths (ADR 0001, extended by ADR 0002):
      * CH number — the trusted join for records that carry one (gender pay gap,
        modern slavery, donations).
      * Exact organisation name (case-insensitive) — the only way to surface
        records that carry no CH number (the ethics datasets: LGBTQ+ rights,
        abortion rights, climate). Matched only against ``ch_number IS NULL`` rows,
        so a name match can never override or duplicate a CH-keyed record.

    ``names`` are the company's resolved brand and parent. No fuzzy or partial
    matching: a looked-alike name can be a different legal entity.
    """
    if not db_path.exists():
        log.warning("records DB not found at %s", db_path)
        return []
    seen: set[tuple] = set()
    out: list[dict] = []
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT kind, summary, date, source_url FROM records "
            "WHERE ch_number = ? ORDER BY date DESC",
            (ch_number,),
        ).fetchall()
        for name in dict.fromkeys(n.strip() for n in names if n and n.strip()):
            rows += con.execute(
                "SELECT kind, summary, date, source_url FROM records "
                "WHERE ch_number IS NULL AND company_name = ? COLLATE NOCASE",
                (name,),
            ).fetchall()
        con.close()
    except sqlite3.Error:
        log.exception("records query failed for ch_number=%s", ch_number)
        return []
    for r in rows:
        key = (r[0], r[1], r[2], r[3])
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": r[0], "summary": r[1], "date": r[2], "source_url": r[3]})
    out.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return out


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
        try:
            parent, ch, via = await asyncio.wait_for(_wikidata_lookup(http, brand, domain), WIKIDATA_BUDGET_S)
        except asyncio.TimeoutError:
            log.debug("wikidata lookup timed out for brand=%s", brand)
            parent, ch, via = None, None, None

        # --- Step 2: GLEIF (exact legal name) ---
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

        from smallprint.asa import fetch_asa_rulings
        db_records = _load_records(ch, db_path, names=(brand, parent or ""))

        if ch:
            asa_records = await fetch_asa_rulings(brand, parent=parent, http=http)
            return {
                "brand": brand,
                "parent": parent,
                "ch_number": ch,
                "match_via": via,
                "records": db_records + asa_records,
            }

        # No Companies House match. The ethics datasets (LGBTQ+ rights, abortion
        # rights, climate) carry no CH number and are keyed on the exact brand or
        # parent name, so they can still surface for a foreign parent that has no
        # UK Companies House entry (e.g. PepsiCo, L'Oréal). ADR 0002.
        if db_records:
            return {
                "brand": brand,
                "parent": parent,
                "ch_number": None,
                "match_via": "Brand name match",
                "records": db_records,
            }
        return _not_identified(brand)

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
