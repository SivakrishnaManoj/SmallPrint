"""Company matcher (J5, #17): brand → parent → Companies House number.

Chain (each step only runs if the previous found nothing):
  0. Clean the brand text the page gave us: drop ®/™/©, "Visit the … Store",
     "Brand: …" and "Official Store" wording.  Rule-based, never fuzzy.
  1. Wikidata — find the brand with the wbsearchentities API (exact label or
     alias match only), then read its claims by ID with wbgetentities:
     Companies House company ID (P2622), parent organisation (P749), a single
     current owner (P127) or a single manufacturer (P176, how product brands
     such as Pepsi Max are linked), official website (P856) and LEI (P1278).
     Items whose English label is the brand are considered before items that
     only have it as an alias ("Pepsi" the drink before the payments company
     once code-named PEPSI).  When several items share the name, the one whose website matches the page
     domain wins; otherwise the match must be unambiguous (one item with its own
     CH number, or a lone item with an official website).  Never a guess.
     We never look *down* to a subsidiary: being a group's only UK-registered
     child on record (a pension trustee, an overseas holding company) does not
     make it the company behind the brand.  Live testing showed exactly that.
  2. GLEIF — the LEI (P1278) of the company we display: its own record, if it
     is registered at Companies House.  Never a child's or an ancestor's record,
     whose filings belong to a different company.  Then exact legal-name match
     among GB LEI records registered at Companies House (registration authority
     RA000585), for the brand and then the parent's name; the CH number is the
     record's registeredAs value.
  3. Companies House — exact name search on the free Companies House API, for
     the brand and then the parent's name.  Accepts only when a result's title
     is a case-insensitive exact match.

The page's manufacturer (Amazon's "Manufacturer" row, or JSON-LD) is used two ways,
both exact: its legal name is tried first at GLEIF and Companies House ("Ltd" and
"Limited" count as the same), and when several Wikidata items share the brand name it
picks the one whose own or parent name it starts with ("Unilever UK Ltd" picks Dove
the Unilever brand over Dove the Mars chocolate).

No fuzzy matching at any step.  When the owner is found but no UK company
number is, the owner and how it was matched are still returned, with no
records: hiding a known owner would be less honest than saying none matched.
"Brand not identified" is reserved for when nothing matches at all.

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
_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")


_LEGAL_FORMS = {"limited", "plc", "inc", "llc", "llp", "lp", "corporation", "corp", "company", "co",
                "gmbh", "ag", "sa", "sas", "bv", "nv", "spa", "srl", "ab", "as", "oy", "kk", "pty"}


def legal_name_key(name: str | None) -> str:
    """A company's legal name for exact comparison: case, punctuation, "&"/"and" and
    "Ltd"/"Limited" don't matter; every word still has to match.

    "Sony Interactive Entertainment Europe Ltd" and "SONY INTERACTIVE ENTERTAINMENT
    EUROPE LIMITED" give the same key; "Unilever UK & CN Holdings Limited" does not
    match "Unilever UK Limited".
    """
    s = re.sub(r"[\u200e\u200f]", "", name or "").casefold().replace("&", " and ")
    words = re.sub(r"[^\w\s]", " ", s).split()
    return " ".join("limited" if w == "ltd" else w for w in words)


def _owner_key(name: str | None) -> str:
    """Legal-name key without the trailing legal form ("Unilever UK Limited" → "unilever uk")."""
    words = legal_name_key(name).split()
    while words and words[-1] in _LEGAL_FORMS:
        words.pop()
    return " ".join(words)


def _made_by(manufacturer: str, company_label: str | None) -> bool:
    """The page's manufacturer is this company or a company named after it, whole words only.

    "Unilever UK Ltd" → Unilever (yes); "Sony Interactive Entertainment Europe Ltd" →
    Sony Interactive Entertainment (yes); "Unileverage Ltd" → Unilever (no).
    """
    m, c = _owner_key(manufacturer), _owner_key(company_label)
    return bool(m and c) and (m == c or m.startswith(c + " "))


def tidy_manufacturer(raw: str | None) -> str:
    """Strip direction marks, colons and spaces around a manufacturer value."""
    s = re.sub(r"[\u200e\u200f]", "", raw or "")
    return re.sub(r"\s+", " ", s).strip(" :")


def clean_brand(raw: str | None) -> str:
    """Rule-based clean-up of the brand text a page gives us. Never fuzzy.

    "Visit the Pepsi Max Store" → "Pepsi Max"; "Brand: Dove" → "Dove";
    "PEPSI MAX®" → "PEPSI MAX"; "Andrex Official Store" → "Andrex".
    """
    s = re.sub(r"[®™©]", "", raw or "")
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^visit the (.+?) store$", s, re.I)
    if m:
        s = m.group(1)
    s = re.sub(r"^brand:\s*", "", s, flags=re.I)
    s = re.sub(r"\s+(?:official\s+)?(?:store|shop)$", "", s, flags=re.I)
    return s.strip(" -–|,")

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
    """Parent organisation (P749); else the owner (P127), else the manufacturer (P176),
    each only if there is exactly one.

    P127 on a big company often lists many shareholders.  Calling one of them
    "the parent" would be a guess, so several owners mean no parent.  Product
    brands (Pepsi Max, Walkers) are usually linked to their company only by
    manufacturer, so a single manufacturer counts as the parent.
    """
    parents = _claim_ids(entity, "P749")
    if parents:
        return parents
    for prop in ("P127", "P176"):
        ids = _claim_ids(entity, prop)
        if len(ids) == 1:
            return ids
    return []


def _lei(entity: dict) -> str | None:
    for v in _claim_values(entity, "P1278"):
        if isinstance(v, str) and _LEI_RE.match(v.strip().upper()):
            return v.strip().upper()
    return None


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


def _substantial(entities: dict[str, dict]) -> dict[str, dict]:
    return {
        q: e for q, e in entities.items()
        if not _is_human(e) and (_claim_values(e, "P2622") or _parent_ids(e) or _site_hosts(e))
    }


async def _pick_by_manufacturer(http: httpx.AsyncClient, candidates: dict[str, dict], manufacturer: str) -> str | None:
    """Of several same-name items, the one the page's manufacturer names (itself or its parent).

    Only decides when exactly one candidate fits; otherwise it is still ambiguous.
    """
    cands = _substantial(candidates)
    parent_ids = list(dict.fromkeys(p for e in cands.values() for p in _parent_ids(e)))[:50]
    parents = await _wd_entities(http, parent_ids) if parent_ids else {}
    fits = [
        q for q, e in cands.items()
        if _made_by(manufacturer, _entity_label(e))
        or any(_made_by(manufacturer, _entity_label(parents[p])) for p in _parent_ids(e) if p in parents)
    ]
    return fits[0] if len(fits) == 1 else None


async def _wikidata_lookup(
    http: httpx.AsyncClient, brand: str, domain: str, manufacturer: str = "",
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (parent_name, ch_number, match_via, parent_lei), or all None.

    ``parent_name`` can come back without a CH number: the owner is still worth
    showing.  Any network or parsing failure counts as "not found" so the later
    steps still run.
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
        ids, label_ids = [], set()
        for hit in resp.json().get("search") or []:
            text = ((hit.get("match") or {}).get("text") or hit.get("label") or "")
            if text.strip().casefold() == wanted and hit.get("id"):
                ids.append(hit["id"])
                if (hit.get("label") or "").strip().casefold() == wanted:
                    label_ids.add(hit["id"])
        if not ids:
            return None, None, None, None

        entities = await _wd_entities(http, ids)
        # The brand's own name beats a nickname: try label matches first, then everything.
        by_label = {q: e for q, e in entities.items() if q in label_ids}
        qid = _pick_candidate(by_label, domain) if by_label else None
        if qid is None:
            qid = _pick_candidate(entities, domain)
        via = "Wikidata"
        if qid is None and manufacturer:
            # Several items share the name (Dove soap, Dove chocolate): the page's manufacturer decides.
            qid = (await _pick_by_manufacturer(http, by_label, manufacturer) if by_label else None) \
                or await _pick_by_manufacturer(http, entities, manufacturer)
            if qid:
                via = "Wikidata, told apart by the page's manufacturer"
        if qid is None:
            return None, None, None, None

        entity = entities[qid]
        own_ch = _normalise_ch_number(next(iter(_claim_values(entity, "P2622")), None))
        parents = _parent_ids(entity)
        parent_name: str | None = None
        parent_entity: dict | None = None
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
                parent_entity = next((level[p] for p in frontier if p in level and _entity_label(level[p])), None)
                parent_name = _entity_label(parent_entity) if parent_entity else None
            nxt: list[str] = []
            for pid in frontier:
                pe = level.get(pid)
                if not pe:
                    continue
                if ch is None:
                    pch = _normalise_ch_number(next(iter(_claim_values(pe, "P2622")), None))
                    if pch:
                        ch = pch
                        parent_entity = pe
                        parent_name = _entity_label(pe) or parent_name
                nxt.extend(_parent_ids(pe))
            if ch is not None:
                break
            frontier = nxt

        if ch is None and parent_name is None:
            return None, None, None, None
        # The LEI of the company we will display: the parent shown, or the brand's own
        # company when it has no parent.  Never another ancestor's.
        return parent_name, ch, via, _lei(parent_entity if parent_entity else entity)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.debug("wikidata lookup failed for brand=%s", brand)
        return None, None, None, None


# ---------------------------------------------------------------------------
# GLEIF lookup
# ---------------------------------------------------------------------------

def _gleif_uk_number(record: dict) -> tuple[str | None, str | None]:
    """(legal name, CH number) if this LEI record is registered at Companies House."""
    entity = (record.get("attributes") or {}).get("entity") or {}
    if ((entity.get("registeredAt") or {}).get("id")) != GLEIF_COMPANIES_HOUSE_RA:
        return None, None
    ch = _normalise_ch_number(entity.get("registeredAs"))
    name = ((entity.get("legalName") or {}).get("name") or "").strip() or None
    return (name, ch) if ch else (None, None)


async def _gleif_by_lei(http: httpx.AsyncClient, lei: str) -> tuple[str | None, str | None]:
    """The company with exactly this LEI, if it is registered at Companies House.

    Only the company's own record.  Its children (or parents) are different
    companies with their own filings, so they are never used.
    """
    try:
        own = await http.get(f"{GLEIF_API}/lei-records/{lei}", headers={"Accept": "application/vnd.api+json"}, timeout=TIMEOUT_S)
        own.raise_for_status()
        return _gleif_uk_number(own.json().get("data") or {})
    except (httpx.HTTPError, ValueError):
        log.debug("gleif lei lookup failed for %s", lei)
        return None, None


async def _gleif_lookup(http: httpx.AsyncClient, brand: str) -> tuple[str | None, str | None]:
    """Return (legal_name, ch_number) via GLEIF, or (None, None) on any failure.

    Queries the GB LEI records whose legal name matches, then keeps only a record
    whose legal name equals the brand exactly (case-insensitive) and that is
    registered at Companies House (RA000585).  The CH number is ``registeredAs``.
    """
    # GLEIF's name filter wants the legal form spelled out: "Ltd" finds nothing, "Limited" does.
    spellings = list(dict.fromkeys([brand, re.sub(r"\bLtd\b\.?", "Limited", brand, flags=re.I)]))
    data: dict = {"data": []}
    for spelling in spellings:
        try:
            resp = await http.get(
                f"{GLEIF_API}/lei-records",
                params={
                    "filter[entity.legalName]": spelling,
                    "filter[entity.legalAddress.country]": "GB",
                    "page[size]": 10,
                },
                headers={"Accept": "application/vnd.api+json"},
                timeout=TIMEOUT_S,
            )
            resp.raise_for_status()
            data["data"] += resp.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            log.debug("gleif lookup failed for %s", spelling)

    wanted = legal_name_key(brand)
    for item in data.get("data") or []:
        entity = (item.get("attributes") or {}).get("entity") or {}
        name = ((entity.get("legalName") or {}).get("name") or "").strip()
        if legal_name_key(name) != wanted:
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
        if legal_name_key(title) == legal_name_key(brand) and number:
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
    manufacturer: str | None = None,
) -> dict:
    """Brand → parent → CH number.  Returns the company dict for the response schema.

    Injectable ``http``, ``db_path`` and ``ch_api_key`` for testing.
    Production callers pass nothing; defaults come from env / filesystem.
    """
    brand = clean_brand(brand)
    manufacturer = tidy_manufacturer(manufacturer)
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
            parent, ch, via, parent_lei = await asyncio.wait_for(_wikidata_lookup(http, brand, domain, manufacturer), WIKIDATA_BUDGET_S)
        except asyncio.TimeoutError:
            log.debug("wikidata lookup timed out for brand=%s", brand)
            parent, ch, via, parent_lei = None, None, None, None

        # --- Step 2: GLEIF: the displayed company's own LEI record ---
        if not ch and parent_lei:
            uk_name, uk_ch = await _gleif_by_lei(http, parent_lei)
            if uk_ch:
                ch = uk_ch
                via = f"{via}, then GLEIF: {uk_name}" if via and uk_name else "GLEIF"
                parent = parent or uk_name

        # Exact names to try at GLEIF and Companies House: the page's manufacturer (often
        # the UK company itself), then the brand, then the parent.
        names = list(dict.fromkeys(n for n in (manufacturer, brand, parent) if n))

        def describe(source: str, name: str, legal_name: str | None) -> str:
            if name == manufacturer:
                found = f"UK company from the page's manufacturer ({source}): {legal_name or name}"
                return f"{via}; {found}" if via else found
            if name == brand:
                return source if source == "GLEIF" else f"{source} exact name"
            return f"{via}, then {source} exact name"

        # --- Step 2b: GLEIF (exact legal name) ---
        for name in names:
            if ch:
                break
            gleif_parent, gleif_ch = await _gleif_lookup(http, name)
            if gleif_ch:
                via = describe("GLEIF", name, gleif_parent)
                parent = parent or gleif_parent
                ch = gleif_ch

        # --- Step 3: Companies House exact name ---
        for name in names:
            if ch:
                break
            ch_name, ch_num = await _ch_lookup(http, name, ch_api_key)
            if ch_num:
                via = describe("Companies House", name, ch_name)
                parent = parent or ch_name
                ch = ch_num

        if not ch:
            if parent:
                # The owner is known even though no UK company number is: say so.
                return {"brand": brand, "parent": parent, "ch_number": None, "match_via": via, "records": []}
            return _not_identified(brand)

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
