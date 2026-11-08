"""V5 (#27): ASA rulings tests. HTTP faked at the transport boundary.

Done when:
  * A known brand returns dated rulings with source URLs.
  * Summaries use factual language — no verdict words, lawsuits as allegations.
  * ASA failure returns [] and doesn't crash the company lookup.
"""
from __future__ import annotations

import httpx
import pytest

from smallprint.asa import _summarise, _to_record, fetch_asa_rulings

# ---------------------------------------------------------------------------
# Recorded ASA response shapes (abbreviated)
# ---------------------------------------------------------------------------

_SODASTREAM_RULINGS = [
    {
        "advertiserName": "SodaStream Ltd",
        "date": "15/03/2023",
        "slug": "sodastream-ltd-23-03-2023",
        "productCategory": "Food",
        "upheld": True,
    },
    {
        "advertiserName": "SodaStream Ltd",
        "date": "02/09/2022",
        "slug": "sodastream-ltd-09-2022",
        "productCategory": "Food",
        "upheld": False,
    },
]

_EMPTY_RESPONSE: list = []


class FakeASATransport(httpx.AsyncBaseTransport):
    def __init__(self, body: list | dict, status: int = 200):
        self.body = body
        self.status = status
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        return httpx.Response(self.status, json=self.body)


def _client(body, status=200):
    t = FakeASATransport(body, status)
    return httpx.AsyncClient(transport=t), t


# ---------------------------------------------------------------------------
# _summarise language rules
# ---------------------------------------------------------------------------

def test_summary_uses_factual_language_upheld():
    item = {"advertiserName": "Acme Ltd", "date": "2024-01-15", "slug": "acme-jan", "upheld": True, "productCategory": "Electronics"}
    s = _summarise(item)
    assert "ASA published a ruling" in s
    assert "Acme Ltd" in s
    assert "2024-01-15" in s
    assert "upheld" in s.lower()
    assert "guilty" not in s.lower()
    assert "found" not in s.lower() or "not found" in s.lower()


def test_summary_uses_factual_language_not_upheld():
    item = {"advertiserName": "Acme Ltd", "date": "2024-01-15", "upheld": False}
    s = _summarise(item)
    assert "not upheld" in s.lower()


def test_summary_redacts_verdict_words_from_source_data():
    item = {"advertiserName": "Acme Ltd", "date": "2024-01-15", "productCategory": "guilty of fraud", "upheld": True}
    s = _summarise(item)
    assert "guilty" not in s


def test_summary_handles_missing_outcome():
    item = {"advertiserName": "Acme", "date": "2023-06-01"}
    s = _summarise(item)
    assert "ASA published a ruling" in s
    assert "upheld" not in s.lower()


# ---------------------------------------------------------------------------
# _to_record
# ---------------------------------------------------------------------------

def test_to_record_converts_valid_item():
    item = {"advertiserName": "SodaStream Ltd", "date": "15/03/2023", "slug": "sodastream-23", "upheld": True}
    r = _to_record(item)
    assert r is not None
    assert r["kind"] == "asa_ruling"
    assert r["date"] == "2023-03-15"
    assert r["source_url"] == "https://www.asa.org.uk/rulings/sodastream-23"
    assert "SodaStream" in r["summary"]


def test_to_record_returns_none_without_date():
    assert _to_record({"advertiserName": "Acme", "slug": "acme-1"}) is None


# ---------------------------------------------------------------------------
# fetch_asa_rulings end-to-end
# ---------------------------------------------------------------------------

async def test_known_brand_returns_dated_rulings_with_source_urls():
    http, t = _client(_SODASTREAM_RULINGS)
    async with http:
        records = await fetch_asa_rulings("SodaStream", http=http)

    assert len(records) == 2
    assert all(r["kind"] == "asa_ruling" for r in records)
    assert all(r["date"] for r in records)
    assert all(r["source_url"] for r in records)
    assert len(t.calls) == 1
    assert "q=SodaStream" in t.calls[0]


async def test_no_rulings_returns_empty_list():
    http, _ = _client(_EMPTY_RESPONSE)
    async with http:
        records = await fetch_asa_rulings("UnknownBrand", http=http)
    assert records == []


async def test_api_failure_returns_empty_list_does_not_raise():
    http, _ = _client({}, status=500)
    async with http:
        records = await fetch_asa_rulings("SodaStream", http=http)
    assert records == []


async def test_network_error_returns_empty_list():
    class BrokenTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _):
            raise httpx.ConnectError("refused")
    async with httpx.AsyncClient(transport=BrokenTransport()) as http:
        records = await fetch_asa_rulings("SodaStream", http=http)
    assert records == []


async def test_empty_brand_returns_empty_without_http_call():
    records = await fetch_asa_rulings("")
    assert records == []


async def test_no_verdict_words_in_any_summary():
    http, _ = _client(_SODASTREAM_RULINGS)
    async with http:
        records = await fetch_asa_rulings("SodaStream", http=http)

    verdict_words = ["guilty", "convicted", "unethical", "illegal", "broke the law", "corrupt"]
    for r in records:
        for word in verdict_words:
            assert word not in r["summary"].lower(), f"verdict word '{word}' in: {r['summary']}"


async def test_accepts_list_or_items_wrapper():
    """The ASA API might wrap results in {"items": [...]} or return a bare list."""
    wrapped = {"items": _SODASTREAM_RULINGS}
    http, _ = _client(wrapped)
    async with http:
        records = await fetch_asa_rulings("SodaStream", http=http)
    assert len(records) == 2
