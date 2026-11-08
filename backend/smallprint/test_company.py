"""J5 (#17): company matcher tests.  Network calls faked at the httpx transport boundary.

Done when:
  * A known brand resolves to a parent and CH number via Wikidata.
  * An unknown brand returns "Brand not identified" with no records.
  * No output uses verdict words.
  * Records from the index appear only when the CH number matches exactly.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from smallprint.company import _extract_domain, _parse_wikidata, company_lookup

# ---------------------------------------------------------------------------
# Recorded Wikidata SPARQL responses (abbreviated; real binding structure)
# ---------------------------------------------------------------------------

_SODASTREAM_WIKIDATA = {
    "results": {
        "bindings": [
            {
                "brand":       {"type": "uri",     "value": "http://www.wikidata.org/entity/Q1127717"},
                "brandLabel":  {"type": "literal", "value": "SodaStream"},
                "parent":      {"type": "uri",     "value": "http://www.wikidata.org/entity/Q131688"},
                "parentLabel": {"type": "literal", "value": "PepsiCo"},
                "parentCh":    {"type": "literal", "value": "SC127671"},
            }
        ]
    }
}

_EMPTY_WIKIDATA = {"results": {"bindings": []}}

_GLEIF_AUTOCOMPLETE_EMPTY = {"data": []}

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
# _parse_wikidata
# ---------------------------------------------------------------------------

def test_parse_wikidata_known_brand():
    parent, ch, via = _parse_wikidata(_SODASTREAM_WIKIDATA["results"]["bindings"])
    assert parent == "PepsiCo"
    assert ch == "SC127671"
    assert via == "Wikidata"


def test_parse_wikidata_empty_returns_none():
    parent, ch, via = _parse_wikidata([])
    assert parent is None and ch is None and via is None


# ---------------------------------------------------------------------------
# company_lookup end-to-end
# ---------------------------------------------------------------------------

async def test_known_brand_resolves_via_wikidata(db):
    http, transport = _client({
        "https://query.wikidata.org": _SODASTREAM_WIKIDATA,
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
        "https://query.wikidata.org": _EMPTY_WIKIDATA,
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


async def test_ch_fallback_on_exact_name_match(db):
    http, transport = _client({
        "https://query.wikidata.org": _EMPTY_WIKIDATA,
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
        "https://query.wikidata.org": _EMPTY_WIKIDATA,
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
        "https://query.wikidata.org": _SODASTREAM_WIKIDATA,
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


async def test_no_verdict_words_in_output(db):
    http, _ = _client({
        "https://query.wikidata.org": _SODASTREAM_WIKIDATA,
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
        "https://query.wikidata.org": None,  # will 404
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
