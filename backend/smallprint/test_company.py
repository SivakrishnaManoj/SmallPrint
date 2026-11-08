"""J5 (#17): company matcher tests.  Network calls faked at the httpx transport boundary.

Done when:
  * A known brand resolves to a parent and CH number via Wikidata.
  * An unknown brand returns "Brand not identified" with no records.
  * No output uses verdict words.
  * Records from the index appear only when the CH number matches exactly.
"""
from __future__ import annotations

import json
import re
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

from smallprint.company import (
    _extract_domain,
    _load_records,
    _normalise_ch_number,
    _parent_ids,
    _pick_candidate,
    company_lookup,
)

# ---------------------------------------------------------------------------
# Fake Wikidata API responses (wbsearchentities and wbgetentities shapes)
# ---------------------------------------------------------------------------

def _claim(prop: str, value, *, rank: str = "normal", ended: bool = False) -> dict:
    snak = {"datatype": "string", "datavalue": {"value": value, "type": "string"}}
    claim: dict = {"mainsnak": {"property": prop, **snak}, "rank": rank}
    if ended:
        claim["qualifiers"] = {"P582": [{"property": "P582"}]}
    return {prop: [claim]}


def _item_claim(prop: str, qid: str, **kw) -> dict:
    c = _claim(prop, {"entity-type": "item", "id": qid}, **kw)
    return c


def _entity(qid: str, label: str, *claim_dicts: dict) -> dict:
    claims: dict = {}
    for d in claim_dicts:
        for prop, lst in d.items():
            claims.setdefault(prop, []).extend(lst)
    return {"id": qid, "labels": {"en": {"language": "en", "value": label}}, "claims": claims}


def _search_hits(*pairs: tuple[str, str]) -> dict:
    return {"search": [{"id": q, "label": lbl, "match": {"type": "label", "text": lbl}} for q, lbl in pairs]}


def _wikidata(search: dict, entities: dict[str, dict]):
    """A route callable that answers wbsearchentities and wbgetentities like the real API."""
    def answer(request: httpx.Request):
        params = request.url.params
        if params.get("action") == "wbsearchentities":
            return search
        ids = params.get("ids", "").split("|")
        return {"entities": {q: entities.get(q, {"id": q, "missing": ""}) for q in ids}}
    return answer


# SodaStream has no UK number of its own; its single parent has one.
_SODASTREAM_WIKIDATA = _wikidata(
    _search_hits(("Q1127717", "SodaStream")),
    {
        "Q1127717": _entity("Q1127717", "SodaStream", _item_claim("P749", "Q131688"),
                            _claim("P856", "https://sodastream.com/")),
        "Q131688": _entity("Q131688", "PepsiCo", _claim("P2622", "SC127671")),
    },
)

# Tesco: own CH number, several shareholders under P127 (so no "parent"), and a
# store item with the same label that must not be picked.
_TESCO_WIKIDATA = _wikidata(
    _search_hits(("Q487494", "Tesco"), ("Q138568738", "Tesco")),
    {
        "Q487494": _entity("Q487494", "Tesco", _claim("P2622", "445790"),
                           _item_claim("P127", "Q1"), _item_claim("P127", "Q2"),
                           _claim("P856", "https://www.tescoplc.com/")),
        "Q138568738": _entity("Q138568738", "Tesco", _item_claim("P749", "Q487494")),
    },
)

# Two items with the same name and the same kind of evidence: ambiguous.
_AMBIGUOUS_WIKIDATA = _wikidata(
    _search_hits(("Q10", "Fernly"), ("Q11", "Fernly")),
    {
        "Q10": _entity("Q10", "Fernly", _claim("P856", "https://fernly.example/")),
        "Q11": _entity("Q11", "Fernly", _claim("P856", "https://fernly.example.org/")),
    },
)

_EMPTY_WIKIDATA = _wikidata({"search": []}, {})

_GLEIF_AUTOCOMPLETE_EMPTY = {"data": []}


def _gleif(name: str, number: str | None, authority: str = "RA000585") -> dict:
    return {"data": [{"id": "LEI0000000000000001", "attributes": {"entity": {
        "legalName": {"name": name}, "registeredAt": {"id": authority}, "registeredAs": number,
    }}}]}

_CH_EXACTMATCH = {
    "items": [
        {"title": "FERNLINE HOLDINGS PLC", "company_number": "01234567", "company_status": "active"},
        {"title": "FERNLINE SERVICES LTD",  "company_number": "09876543", "company_status": "active"},
    ]
}

_CH_NO_MATCH = {"items": [{"title": "SOMETHING ELSE LTD", "company_number": "00000001"}]}

_CH_EMPTY = {"items": []}

# ---------------------------------------------------------------------------
# Fake HTTP transport
# ---------------------------------------------------------------------------

class FakeTransport(httpx.AsyncBaseTransport):
    """Routes requests by URL prefix to pre-recorded JSON responses."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if body is None:
                    return httpx.Response(404, json={"error": "not found"})
                if callable(body):
                    body = body(request)
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})


def _client(routes: dict) -> tuple[httpx.AsyncClient, FakeTransport]:
    t = FakeTransport(routes)
    return httpx.AsyncClient(transport=t), t


# ---------------------------------------------------------------------------
# In-memory records DB
# ---------------------------------------------------------------------------

def _make_db(records: list[tuple]) -> Path:
    """Write a temp SQLite DB and return its path."""
    db = Path(pytest.tmp_path_factory.mktemp("db") / "records.sqlite")  # type: ignore[attr-defined]
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE records (
        id INTEGER PRIMARY KEY, ch_number TEXT, company_name TEXT,
        kind TEXT, date TEXT, summary TEXT, source_url TEXT)""")
    con.executemany(
        "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
        records,
    )
    con.commit()
    con.close()
    return db


@pytest.fixture()
def tmp_path_factory(tmp_path_factory):
    return tmp_path_factory


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "records.sqlite"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE records (
        id INTEGER PRIMARY KEY, ch_number TEXT, company_name TEXT,
        kind TEXT, date TEXT, summary TEXT, source_url TEXT)""")
    con.executemany(
        "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
        [
            ("SC127671", "PepsiCo", "gender_pay_gap", "2024-04-04",
             "Mean gender pay gap of 11.2% in favour of men (2023 to 2024 reporting year).",
             "https://gender-pay-gap.service.gov.uk/employer/pepsico"),
            ("SC127671", "PepsiCo", "donation", "2023-06-01",
             "Donated £50,000 to the Example Party (accepted 1 June 2023).",
             None),
            ("01234567", "Fernline Holdings plc", "gender_pay_gap", "2024-01-01",
             "Mean gender pay gap of 9.1% in favour of men (2023 to 2024 reporting year).",
             "https://gender-pay-gap.service.gov.uk/employer/fernline"),
        ],
    )
    con.commit()
    con.close()
    return p


# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------

def test_extract_domain_strips_www():
    assert _extract_domain("https://www.sodastream.co.uk/products/terra") == "sodastream.co.uk"


def test_extract_domain_handles_bare_domain():
    assert _extract_domain("netflix.com") == "netflix.com"


def test_extract_domain_empty():
    assert _extract_domain("") == ""


# ---------------------------------------------------------------------------
# Wikidata matching rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("00445790", "00445790"),
    ("445790", "00445790"),        # Wikidata often drops leading zeros
    (" sc127671 ", "SC127671"),
    ("GB123", None),
    ("not a number", None),
    ("", None),
    (None, None),
])
def test_normalise_ch_number(raw, expected):
    assert _normalise_ch_number(raw) == expected


def test_several_owners_mean_no_parent():
    shareholders = _entity("Q1", "X", _item_claim("P127", "Q2"), _item_claim("P127", "Q3"))
    assert _parent_ids(shareholders) == []


def test_single_owner_is_the_parent_and_parent_org_wins():
    assert _parent_ids(_entity("Q1", "X", _item_claim("P127", "Q2"))) == ["Q2"]
    both = _entity("Q1", "X", _item_claim("P749", "Q5"), _item_claim("P127", "Q2"))
    assert _parent_ids(both) == ["Q5"]


def test_ended_or_deprecated_ownership_is_ignored():
    old = _entity("Q1", "X", _item_claim("P127", "Q2", ended=True))
    assert _parent_ids(old) == []


def test_pick_prefers_domain_match():
    cands = {
        "Q1": _entity("Q1", "A", _claim("P856", "https://a.example.com/")),
        "Q2": _entity("Q2", "A", _claim("P856", "https://b.example.org/")),
    }
    assert _pick_candidate(cands, "b.example.org") == "Q2"


def test_pick_single_item_with_own_ch_number():
    cands = {
        "Q1": _entity("Q1", "A", _claim("P2622", "00445790")),
        "Q2": _entity("Q2", "A", _item_claim("P749", "Q1")),
    }
    assert _pick_candidate(cands, "") == "Q1"


def test_pick_refuses_when_ambiguous():
    cands = {
        "Q1": _entity("Q1", "A", _claim("P856", "https://a.example/")),
        "Q2": _entity("Q2", "A", _claim("P856", "https://b.example/")),
    }
    assert _pick_candidate(cands, "other.example") is None


def test_pick_refuses_lone_item_without_website_or_ch_number():
    cands = {"Q1": _entity("Q1", "Apple", _item_claim("P749", "Q312"))}
    assert _pick_candidate(cands, "apple.com") is None


def test_pick_ignores_people():
    person = _entity("Q1", "BT", _item_claim("P31", "Q5"), _claim("P856", "https://bt.example/"))
    assert _pick_candidate({"Q1": person}, "bt.example") is None


# ---------------------------------------------------------------------------
# company_lookup end-to-end
# ---------------------------------------------------------------------------

async def test_known_brand_resolves_via_wikidata(db):
    http, transport = _client({
        "https://www.wikidata.org": _SODASTREAM_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup(
            "SodaStream", "https://www.amazon.co.uk/dp/B09QYK3LZX",
            http=http, db_path=db, ch_api_key="test-key",
        )

    assert result["ch_number"] == "SC127671"
    assert result["parent"] == "PepsiCo"
    assert result["match_via"] == "Wikidata"
    assert any(r["kind"] == "gender_pay_gap" for r in result["records"])
    assert any(r["kind"] == "donation" for r in result["records"])


async def test_unknown_brand_returns_not_identified(db):
    http, transport = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_NO_MATCH,
    })
    async with http:
        result = await company_lookup(
            "Completely Unknown Brand Ltd", "https://unknown.example.co.uk",
            http=http, db_path=db, ch_api_key="test-key",
        )

    assert result["ch_number"] is None
    assert result["match_via"] == "Brand not identified"
    assert result["records"] == []
    assert result["brand"] == "Completely Unknown Brand Ltd"


async def test_name_only_ethics_match_without_ch_number(db):
    """A foreign parent with no UK CH entry still surfaces name-keyed ethics records (ADR 0002)."""
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
        (None, "PepsiCo", "lgbtq_rights", None,
         "Listed by Accountable for Equality as a corporate donor to US candidates "
         "or committees with voting records opposing LGBTQ+ rights.", None),
    )
    con.commit()
    con.close()

    http, _ = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_NO_MATCH,
    })
    async with http:
        result = await company_lookup(
            "PepsiCo", "https://www.pepsico.com",
            http=http, db_path=db, ch_api_key="test-key",
        )

    assert result["ch_number"] is None
    assert result["match_via"] == "Brand name match"
    assert any(r["kind"] == "lgbtq_rights" for r in result["records"])


async def test_ch_fallback_on_exact_name_match(db):
    http, transport = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_EXACTMATCH,
    })
    async with http:
        result = await company_lookup(
            "FERNLINE HOLDINGS PLC", "https://www.fernline.co.uk",
            http=http, db_path=db, ch_api_key="test-key",
        )

    assert result["ch_number"] == "01234567"
    assert result["match_via"] == "Companies House exact name"
    assert any(r["kind"] == "gender_pay_gap" for r in result["records"])


async def test_ch_fallback_does_not_accept_partial_match(db):
    http, _ = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_EXACTMATCH,
    })
    async with http:
        # "Fernline" != "FERNLINE HOLDINGS PLC" — partial, must not match
        result = await company_lookup(
            "Fernline", "https://www.fernline.co.uk",
            http=http, db_path=db, ch_api_key="test-key",
        )
    assert result["ch_number"] is None
    assert result["match_via"] == "Brand not identified"


async def test_records_joined_on_ch_number_only(db):
    """A matched CH number returns its records; a different CH number's records don't appear."""
    http, _ = _client({
        "https://www.wikidata.org": _SODASTREAM_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup(
            "SodaStream", "sodastream.co.uk",
            http=http, db_path=db, ch_api_key="",
        )

    ch_numbers = {r.get("ch_number") for r in result["records"]}  # type: ignore[attr-defined]
    # Only SC127671 records should appear, not 01234567 (Fernline)
    assert all(r["kind"] in ("gender_pay_gap", "donation") for r in result["records"])
    assert not any("Fernline" in r["summary"] for r in result["records"])


# ---------------------------------------------------------------------------
# Exact-name join for the ethics datasets (ch_number = NULL). ADR 0002.
# ---------------------------------------------------------------------------

def test_name_join_surfaces_null_ch_records(db):
    """A ch_number=NULL ethics record joins by exact brand or parent name."""
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
        (None, "PepsiCo", "climate", "2025-01-01",
         "Has a Science Based Targets initiative (SBTi) validated near-term emissions reduction target.",
         "https://sciencebasedtargets.org/companies-taking-action/"),
    )
    con.commit()
    con.close()

    # CH SC127671 has the two PepsiCo CH-keyed records; the name match adds climate.
    records = _load_records("SC127671", db, names=("PepsiCo", ""))
    kinds = [r["kind"] for r in records]
    assert "climate" in kinds
    assert "gender_pay_gap" in kinds and "donation" in kinds


def test_name_join_is_exact_only(db):
    """A partial or different name must not pull in a null-CH record."""
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
        (None, "PepsiCo", "climate", "2025-01-01", "SBTi target.", "https://sciencebasedtargets.org/"),
    )
    con.commit()
    con.close()

    assert not any(r["kind"] == "climate" for r in _load_records("SC127671", db, names=("Pepsi", "")))
    # Case-insensitive exact match still works.
    assert any(r["kind"] == "climate" for r in _load_records("SC127671", db, names=("pepsico", "")))


async def test_no_verdict_words_in_output(db):
    http, _ = _client({
        "https://www.wikidata.org": _SODASTREAM_WIKIDATA,
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup(
            "SodaStream", "sodastream.co.uk",
            http=http, db_path=db, ch_api_key="",
        )

    verdict_words = ["unethical", "illegal", "broke the law", "corrupt", "guilty", "misconduct"]
    all_text = json.dumps(result).lower()
    for word in verdict_words:
        assert word not in all_text, f"verdict word '{word}' found in output"


async def test_empty_brand_returns_not_identified(db):
    result = await company_lookup("", "", db_path=db)
    assert result["match_via"] == "Brand not identified"
    assert result["ch_number"] is None


async def test_wikidata_http_error_falls_through_to_ch(db):
    """A Wikidata failure is not fatal — CH lookup still runs."""
    routes = {
        "https://www.wikidata.org": None,  # will 404
        "https://api.gleif.org":      _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_EXACTMATCH,
    }
    t = FakeTransport(routes)
    http = httpx.AsyncClient(transport=t)
    async with http:
        result = await company_lookup(
            "FERNLINE HOLDINGS PLC", "fernline.co.uk",
            http=http, db_path=db, ch_api_key="key",
        )
    assert result["ch_number"] == "01234567"
    assert result["match_via"] == "Companies House exact name"


# ---------------------------------------------------------------------------
# Wikidata edge cases, GLEIF and the live check
# ---------------------------------------------------------------------------

async def test_own_ch_number_wins_and_shareholders_are_not_a_parent(db):
    http, _ = _client({
        "https://www.wikidata.org": _TESCO_WIKIDATA,
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup("Tesco", "https://www.tesco.com/x", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] == "00445790"   # padded from "445790"
    assert result["parent"] is None
    assert result["match_via"] == "Wikidata"


async def test_ambiguous_wikidata_match_is_not_guessed(db):
    http, _ = _client({
        "https://www.wikidata.org": _AMBIGUOUS_WIKIDATA,
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_NO_MATCH,
    })
    async with http:
        result = await company_lookup("Fernly", "https://fernly.example", http=http, db_path=db, ch_api_key="key")
    assert result["ch_number"] is None
    assert result["match_via"] == "Brand not identified"


async def test_gleif_exact_name_at_companies_house(db):
    http, transport = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org": _gleif("FERNLINE HOLDINGS PLC", "01234567"),
    })
    async with http:
        result = await company_lookup("Fernline Holdings plc", "fernline.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] == "01234567"
    assert result["match_via"] == "GLEIF"
    assert result["parent"] == "FERNLINE HOLDINGS PLC"
    assert any("api.gleif.org/api/v1/lei-records" in u for u in transport.calls)


async def test_gleif_ignores_partial_name_and_other_registries(db):
    for body in (
        _gleif("FERNLINE HOLDINGS PLC", "01234567"),                          # brand is only "Fernline"
        _gleif("Fernline", "01234567", authority="RA000665"),                 # not Companies House
        _gleif("Fernline", None),                                             # no registration number
    ):
        http, _ = _client({"https://www.wikidata.org": _EMPTY_WIKIDATA, "https://api.gleif.org": body})
        async with http:
            result = await company_lookup("Fernline", "fernline.co.uk", http=http, db_path=db, ch_api_key="")
        assert result["match_via"] == "Brand not identified"


async def test_wikidata_timeout_falls_through(db):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)
    http, _ = _client({
        "https://www.wikidata.org": slow,
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_EXACTMATCH,
    })
    async with http:
        result = await company_lookup("FERNLINE HOLDINGS PLC", "fernline.co.uk", http=http, db_path=db, ch_api_key="key")
    assert result["ch_number"] == "01234567"
    assert result["match_via"] == "Companies House exact name"


@pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="live network test: set RUN_LIVE_TESTS=1")
async def test_live_known_brand_resolves_quickly(tmp_path):
    """Real Wikidata: catches a query that is too slow or reads the wrong property.

    The faked tests above cannot, which is how a SPARQL query that timed out on every
    real brand once passed them.
    """
    import time
    started = time.monotonic()
    result = await company_lookup("Tesco", "https://www.tesco.com/", db_path=tmp_path / "none.sqlite", ch_api_key="")
    assert result["ch_number"] == "00445790"
    assert result["match_via"] == "Wikidata"
    assert time.monotonic() - started < 5


# ---------------------------------------------------------------------------
# Gaps found with Pepsi Max: owner kept without a CH number, manufacturer links,
# looking down to one UK subsidiary, the parent's LEI, parent names, brand clean-up
# ---------------------------------------------------------------------------

from smallprint.company import clean_brand  # noqa: E402

_PEPSICO_LEI = "549300PEPSICOUSA0012"


def _pepsi_max(pepsico: dict, extra: dict | None = None):
    """Pepsi Max linked to PepsiCo only by manufacturer (P176), as product brands usually are."""
    return _wikidata(
        _search_hits(("Q100", "Pepsi Max")),
        {
            "Q100": _entity("Q100", "Pepsi Max", _item_claim("P176", "Q200"), _claim("P856", "https://www.pepsimax.co.uk/")),
            "Q200": pepsico,
            **(extra or {}),
        },
    )


_PEPSICO_NO_UK = _entity("Q200", "PepsiCo", _claim("P856", "https://www.pepsico.com/"))


async def test_owner_kept_when_no_uk_company_number(db):
    """Pepsi Max → PepsiCo, nothing registered in the UK: show the owner, not "not identified"."""
    http, _ = _client({"https://www.wikidata.org": _pepsi_max(_PEPSICO_NO_UK), "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Pepsi Max", "https://www.amazon.co.uk/dp/X", http=http, db_path=db, ch_api_key="")
    assert result == {"brand": "Pepsi Max", "parent": "PepsiCo", "ch_number": None, "match_via": "Wikidata", "records": []}


async def test_manufacturer_counts_only_when_single(db):
    two_makers = _wikidata(
        _search_hits(("Q100", "Pepsi Max")),
        {"Q100": _entity("Q100", "Pepsi Max", _item_claim("P176", "Q200"), _item_claim("P176", "Q201"),
                         _claim("P856", "https://www.pepsimax.co.uk/"))},
    )
    http, _ = _client({"https://www.wikidata.org": two_makers, "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Pepsi Max", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["match_via"] == "Brand not identified" and result["parent"] is None


async def test_a_lone_uk_subsidiary_is_never_used(db):
    """Live testing: Walkers matched "PepsiCo UK Pension Plan Trustee Limited" this way.
    Being a group's only UK subsidiary on record doesn't make it the company behind the brand."""
    pepsico = _entity("Q200", "PepsiCo", _claim("P856", "https://www.pepsico.com/"), _item_claim("P355", "Q300"))
    extra = {"Q300": _entity("Q300", "PepsiCo UK Pension Plan Trustee Limited", _claim("P2622", "02484669"))}
    http, transport = _client({"https://www.wikidata.org": _pepsi_max(pepsico, extra), "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Pepsi Max", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] is None and result["records"] == []
    assert result["parent"] == "PepsiCo"  # the owner is still shown
    assert not any("Q300" in u for u in transport.calls)  # subsidiaries aren't even fetched


def _lei_record(name: str, ch: str | None, authority: str = "RA000585") -> dict:
    return {"attributes": {"entity": {"legalName": {"name": name}, "registeredAt": {"id": authority}, "registeredAs": ch}}}


async def test_displayed_owners_own_lei_record_gives_the_ch_number(db):
    pepsico = _entity("Q200", "PepsiCo", _claim("P856", "https://www.pepsico.com/"), _claim("P1278", _PEPSICO_LEI))
    http, _ = _client({
        "https://www.wikidata.org": _pepsi_max(pepsico),
        f"https://api.gleif.org/api/v1/lei-records/{_PEPSICO_LEI}": {"data": _lei_record("PEPSICO INTERNATIONAL LIMITED", "SC127671")},
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup("Pepsi Max", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] == "SC127671"
    assert result["match_via"] == "Wikidata, then GLEIF: PEPSICO INTERNATIONAL LIMITED"
    assert result["records"]


async def test_gleif_children_are_never_used(db):
    """The owner's LEI is registered outside the UK: its UK children are other companies."""
    pepsico = _entity("Q200", "PepsiCo", _claim("P856", "https://www.pepsico.com/"), _claim("P1278", _PEPSICO_LEI))
    http, transport = _client({
        "https://www.wikidata.org": _pepsi_max(pepsico),
        f"https://api.gleif.org/api/v1/lei-records/{_PEPSICO_LEI}/direct-children": {"data": [
            _lei_record("PEPSICO UK PENSION PLAN TRUSTEE LIMITED", "02484669")]},
        f"https://api.gleif.org/api/v1/lei-records/{_PEPSICO_LEI}": {"data": _lei_record("PepsiCo, Inc.", "2685000", authority="RA000602")},
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup("Pepsi Max", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] is None and result["parent"] == "PepsiCo"
    assert not any("direct-children" in u for u in transport.calls)


async def test_an_ancestors_lei_beyond_the_displayed_owner_is_not_used(db):
    """Live testing: Virgin Media showed "Virgin Media O2" with a grandparent's company number."""
    grand_lei = "213800LIBERTYGLOBA12"
    chain = _wikidata(
        _search_hits(("Q100", "Virgin Media")),
        {
            "Q100": _entity("Q100", "Virgin Media", _item_claim("P749", "Q200"), _claim("P856", "https://www.virginmedia.com/")),
            "Q200": _entity("Q200", "Virgin Media O2", _item_claim("P749", "Q300")),
            "Q300": _entity("Q300", "Liberty Global", _claim("P1278", grand_lei)),
        },
    )
    http, transport = _client({
        "https://www.wikidata.org": chain,
        f"https://api.gleif.org/api/v1/lei-records/{grand_lei}": {"data": _lei_record("LIBERTY GLOBAL HOLDINGS LIMITED", "08379990")},
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup("Virgin Media", "virginmedia.com", http=http, db_path=db, ch_api_key="")
    assert result["parent"] == "Virgin Media O2"
    assert result["ch_number"] is None
    assert not any(grand_lei in u for u in transport.calls)


async def test_exact_search_also_tries_the_parent_name(db):
    """GLEIF and Companies House exact-name searches run for the parent too."""
    fernline = _wikidata(
        _search_hits(("Q100", "Fernline Fibre")),
        {"Q100": _entity("Q100", "Fernline Fibre", _item_claim("P749", "Q200"), _claim("P856", "https://fernline.example/")),
         "Q200": _entity("Q200", "FERNLINE HOLDINGS PLC")},
    )
    http, transport = _client({
        "https://www.wikidata.org": fernline,
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
        "https://api.company-information.service.gov.uk": _CH_EXACTMATCH,
    })
    async with http:
        result = await company_lookup("Fernline Fibre", "fernline.example", http=http, db_path=db, ch_api_key="key")
    assert result["ch_number"] == "01234567"
    assert result["parent"] == "FERNLINE HOLDINGS PLC"
    assert result["match_via"] == "Wikidata, then Companies House exact name"
    assert sum("search/companies" in u for u in transport.calls) == 2  # brand first, then parent


@pytest.mark.parametrize("raw,expected", [
    ("Visit the Pepsi Max Store", "Pepsi Max"),
    ("Brand: Dove", "Dove"),
    ("PEPSI MAX®", "PEPSI MAX"),
    ("Andrex Official Store", "Andrex"),
    ("Walkers™ ", "Walkers"),
    ("  Tesco  ", "Tesco"),
    ("Storey & Co", "Storey & Co"),   # "store" only removed as a trailing word
    ("", ""),
])
def test_clean_brand(raw, expected):
    assert clean_brand(raw) == expected


async def test_page_brand_text_is_cleaned_before_the_exact_search(db):
    http, transport = _client({"https://www.wikidata.org": _pepsi_max(_PEPSICO_NO_UK), "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Visit the Pepsi Max® Store", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["brand"] == "Pepsi Max" and result["parent"] == "PepsiCo"


async def test_new_match_descriptions_have_no_verdict_words(db):
    pepsico = _entity("Q200", "PepsiCo", _claim("P856", "https://www.pepsico.com/"), _claim("P1278", _PEPSICO_LEI))
    http, _ = _client({
        "https://www.wikidata.org": _pepsi_max(pepsico),
        f"https://api.gleif.org/api/v1/lei-records/{_PEPSICO_LEI}": {"data": _lei_record("PEPSICO INTERNATIONAL LIMITED", "SC127671")},
        "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY,
    })
    async with http:
        result = await company_lookup("Pepsi Max", "amazon.co.uk", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] == "SC127671"
    assert not re.search(r"\b(good|bad|ethical|unethical|score|rating|verdict|avoid)\b", json.dumps(result), re.I)


async def test_label_match_beats_alias_match(db):
    """Live case: "Pepsi" the drink vs the European Payments Initiative, aliased "Pepsi"
    (its old code name). Both have websites, so before this the match was ambiguous."""
    pepsi = _wikidata(
        {"search": [
            {"id": "Q47719", "label": "Pepsi", "match": {"type": "label", "text": "Pepsi"}},
            {"id": "Q96743053", "label": "European Payments Initiative", "match": {"type": "alias", "text": "Pepsi"}},
        ]},
        {
            "Q47719": _entity("Q47719", "Pepsi", _item_claim("P749", "Q334800"), _claim("P856", "https://www.pepsi.com/")),
            "Q96743053": _entity("Q96743053", "European Payments Initiative", _claim("P856", "https://epicompany.eu/")),
            "Q334800": _entity("Q334800", "PepsiCo", _claim("P856", "https://www.pepsico.com/")),
        },
    )
    http, _ = _client({"https://www.wikidata.org": pepsi, "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Pepsi", "https://www.amazon.co.uk/dp/X", http=http, db_path=db, ch_api_key="")
    assert result["parent"] == "PepsiCo" and result["match_via"] == "Wikidata"


async def test_alias_match_still_used_when_no_label_match_qualifies(db):
    """BT Group is labelled "BT Group" but aliased "BT": with no qualifying label match, the alias wins."""
    bt = _wikidata(
        {"search": [
            {"id": "Q1", "label": "BT", "match": {"type": "label", "text": "BT"}},  # a musician
            {"id": "Q2", "label": "BT Group", "match": {"type": "alias", "text": "BT"}},
        ]},
        {
            "Q1": _entity("Q1", "BT", _item_claim("P31", "Q5"), _claim("P856", "https://btmusic.com/")),
            "Q2": _entity("Q2", "BT Group", _claim("P2622", "04190816"), _claim("P856", "https://www.bt.com/")),
        },
    )
    http, _ = _client({"https://www.wikidata.org": bt, "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("BT", "bt.com", http=http, db_path=db, ch_api_key="")
    assert result["ch_number"] == "04190816"


# ---------------------------------------------------------------------------
# The page's manufacturer (Amazon "Manufacturer" row): exact UK company, and the
# tie-break between brands that share a name.  Cases from live testing.
# ---------------------------------------------------------------------------

from smallprint.company import _made_by, legal_name_key, tidy_manufacturer  # noqa: E402


@pytest.mark.parametrize("a,b,same", [
    ("Sony Interactive Entertainment Europe Ltd", "SONY INTERACTIVE ENTERTAINMENT EUROPE LIMITED", True),
    ("Unilever UK Ltd.", "UNILEVER UK LIMITED", True),
    ("Marks & Spencer plc", "MARKS AND SPENCER PLC", True),
    ("Unilever UK Limited", "UNILEVER UK & CN HOLDINGS LIMITED", False),
    ("Sony Ltd", "Sony Europe Ltd", False),
])
def test_legal_name_key(a, b, same):
    assert (legal_name_key(a) == legal_name_key(b)) is same


@pytest.mark.parametrize("manufacturer,company,made_by", [
    ("Unilever UK Ltd", "Unilever", True),
    ("Sony Interactive Entertainment Europe Ltd", "Sony Interactive Entertainment", True),
    ("Unilever", "Unilever", True),
    ("Unileverage Ltd", "Unilever", False),     # whole words only
    ("Mars Wrigley UK", "Unilever", False),
    ("Unilever UK Ltd", None, False),
])
def test_made_by(manufacturer, company, made_by):
    assert _made_by(manufacturer, company) is made_by


def test_tidy_manufacturer():
    assert tidy_manufacturer("‏ : ‎ Sony Interactive Entertainment Europe Ltd ") == "Sony Interactive Entertainment Europe Ltd"


def _gleif_by_name(records: dict[str, dict]):
    """GLEIF name search: answers only the exact spelling it is asked for, like the live API."""
    def answer(request: httpx.Request):
        name = request.url.params.get("filter[entity.legalName]", "")
        return {"data": [records[name]]} if name in records else {"data": []}
    return answer


async def test_manufacturer_gives_the_uk_company(db):
    """PlayStation 5 Pro → Sony Interactive Entertainment (US), page says
    "Manufacturer: Sony Interactive Entertainment Europe Ltd" → its UK company."""
    ps5 = _wikidata(
        _search_hits(("Q1", "PlayStation 5 Pro")),
        {"Q1": _entity("Q1", "PlayStation 5 Pro", _item_claim("P176", "Q2"), _claim("P856", "https://www.playstation.com/")),
         "Q2": _entity("Q2", "Sony Interactive Entertainment", _claim("P856", "https://www.sie.com/"))},
    )
    http, transport = _client({
        "https://www.wikidata.org": ps5,
        "https://api.gleif.org": _gleif_by_name({
            # Only the "Limited" spelling exists, as at GLEIF: "Ltd" finds nothing.
            "Sony Interactive Entertainment Europe Limited": _lei_record("SONY INTERACTIVE ENTERTAINMENT EUROPE LIMITED", "01234567"),
        }),
    })
    async with http:
        result = await company_lookup("PlayStation 5 Pro", "https://www.amazon.co.uk/dp/X", http=http, db_path=db,
                                      ch_api_key="", manufacturer="Sony Interactive Entertainment Europe Ltd")
    assert result["ch_number"] == "01234567"
    assert result["parent"] == "Sony Interactive Entertainment"
    assert result["match_via"] == ("Wikidata; UK company from the page's manufacturer (GLEIF): "
                                   "SONY INTERACTIVE ENTERTAINMENT EUROPE LIMITED")
    assert result["records"]  # joined on that number


_TWO_DOVES = _wikidata(
    _search_hits(("Q962709", "Dove"), ("Q3038279", "Dove")),
    {
        "Q962709": _entity("Q962709", "Dove", _item_claim("P749", "Q157062"), _claim("P856", "https://www.dove.com/")),
        "Q3038279": _entity("Q3038279", "Dove", _claim("P856", "https://www.dovechocolate.com/")),
        "Q157062": _entity("Q157062", "Unilever", _claim("P2622", "00041424")),
    },
)


async def test_manufacturer_tells_apart_brands_that_share_a_name(db):
    http, _ = _client({"https://www.wikidata.org": _TWO_DOVES, "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
    async with http:
        result = await company_lookup("Dove", "https://www.amazon.co.uk/dp/X", http=http, db_path=db,
                                      ch_api_key="", manufacturer="Unilever UK Ltd")
    assert result["parent"] == "Unilever" and result["ch_number"] == "00041424"
    assert result["match_via"] == "Wikidata, told apart by the page's manufacturer"


async def test_same_name_brands_stay_ambiguous_without_a_fitting_manufacturer(db):
    for manufacturer in (None, "Some Distributor Ltd"):
        http, _ = _client({"https://www.wikidata.org": _TWO_DOVES, "https://api.gleif.org": _GLEIF_AUTOCOMPLETE_EMPTY})
        async with http:
            result = await company_lookup("Dove", "https://www.amazon.co.uk/dp/X", http=http, db_path=db,
                                          ch_api_key="", manufacturer=manufacturer)
        assert result["match_via"] == "Brand not identified", manufacturer


async def test_manufacturer_near_miss_legal_name_is_rejected(db):
    http, _ = _client({
        "https://www.wikidata.org": _EMPTY_WIKIDATA,
        "https://api.gleif.org": _gleif_by_name({
            "Unilever UK Limited": _lei_record("UNILEVER UK & CN HOLDINGS LIMITED", "00077912"),
        }),
    })
    async with http:
        result = await company_lookup("Unbranded", "amazon.co.uk", http=http, db_path=db, ch_api_key="",
                                      manufacturer="Unilever UK Limited")
    assert result["match_via"] == "Brand not identified"
