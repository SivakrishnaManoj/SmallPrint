"""V5 (#27): ASA rulings tests. HTTP faked at the transport boundary.

Done when:
  * A known brand returns dated rulings with source URLs.
  * Summaries use factual language — no verdict words.
  * Only rulings for the brand or its parent are kept (the ASA search is full-text).
  * ASA failure returns [] and doesn't crash the company lookup.

The HTML below is trimmed from a real results page,
https://www.asa.org.uk/codes-and-rulings/rulings.html?q=EE (2026-11-08).
"""
from __future__ import annotations

import httpx
import pytest

from smallprint.asa import (
    ASA_SEARCH_URL, _summarise, _to_record, advertiser_matches, fetch_asa_rulings, parse_rulings_html,
)

# ---------------------------------------------------------------------------
# Recorded ASA results page (trimmed)
# ---------------------------------------------------------------------------


def _item(href: str, advertiser: str, captions: list[str], blurb: str = "An ad was seen.") -> str:
    caps = "".join(
        f"""
\t\t\t\t\t\t\t<li class="meta-listing-item">
\t\t\t\t\t\t\t\t<span class="caption">{c}</span>
\t\t\t\t\t\t\t</li>""" for c in captions)
    return f"""
\t\t<li class="icon-listing-item">
\t\t\t\t<a class="font-icon font-icon-Gavel icon-holder u-perfect-round" href="{href}" target="_blank"></a>
\t\t\t\t<div class="icon-listing-item-content">
\t\t\t\t\t<h4 class="heading"><a href="{href}" target="_blank">{advertiser}</a></h4>
\t\t\t\t\t<ul class="meta-listing">{caps}
\t\t\t\t\t</ul>
\t\t\t\t\t\t\t<p>{blurb}&nbsp; </p>
\t\t\t</div>
\t\t</li>"""


RULINGS_PAGE = f"""<html><body>
<div class="toggle-tabs-panel-item is-active" id="rulings">
\t<a href="#rulings" class="toggle-tabs-panel-item-header tab-button rulings-anchor">Rulings (5)</span></a>
\t<div class="toggle-tabs-panel-item-content">
\t\t<ul class="icon-listing mod-bordered" id="tab-1">
{_item("https://www.asa.org.uk/rulings/ee-ltd-a24-1253564-ee-ltd.html", "EE Ltd t/a EE",
       ["Part upheld", "Internet (on own site)", "21 May 2025"])}
{_item("https://www.asa.org.uk/rulings/ee-ltd-g25-1321697-ee-ltd.html", "EE Ltd t/a EE",
       ["Not Upheld", "Poster (digital static image)", "15 July 2026"], blurb="A misleading claim was alleged.")}
{_item("https://www.asa.org.uk/rulings/bonne-terre-ltd-a23-1189938-bonne-terre-ltd-1.html", "Bonne Terre Ltd t/a Sky Bet",
       ["Upheld", "Social media (paid ad)", "22 October 2025"])}
{_item("https://www.asa.org.uk/rulings/uab-convenity-a25-1281612-uab-convenity.html", "UAB Convenity t/a Huusk",
       ["Upheld", "28 May 2025"])}
{_item("https://evil.example/rulings/ee.html", "EE Ltd t/a EE", ["Upheld", "01 January 2024"])}
\t\t</ul>
\t\t<a class="show-more-link load-more-ruling" data-page="2" data-total-page="2" data-tab="tab-1">Show more</a>
\t</div>
</div>
<div class="toggle-tabs-panel-item " id="informally-resolved">
\t<a href="#informally-resolved" class="toggle-tabs-panel-item-header tab-button">Informally resolved (1)</span></a>
\t<div class="toggle-tabs-panel-item-content">
\t\t<ul class="icon-listing mod-bordered" id="tab-2">
\t\t<li class="icon-listing-item">
\t\t\t<div class="icon-listing-item-content">
\t\t\t\t<h4 class="heading">EE Ltd</h4>
\t\t\t\t<ul class="meta-listing"><li class="meta-listing-item"><span class="caption">11 October 2023</span></li></ul>
\t\t\t</div>
\t\t</li>
\t\t</ul>
\t</div>
</div>
</body></html>"""

NO_RULINGS_PAGE = """<html><body>
<div class="toggle-tabs-panel-item is-active" id="rulings">
\t<ul class="icon-listing mod-bordered" id="tab-1">
\t</ul>
</div>
</body></html>"""


class FakeASATransport(httpx.AsyncBaseTransport):
    def __init__(self, body: str, status: int = 200):
        self.body = body
        self.status = status
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        return httpx.Response(self.status, text=self.body, headers={"content-type": "text/html; charset=utf-8"})


def _client(body: str, status: int = 200):
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


def test_outcome_spellings_all_map_to_factual_sentences():
    for raw, sentence in [("Upheld", "was upheld."), ("Not Upheld", "was not upheld."),
                          ("Part upheld", "was upheld in part."), ("Upheld in part", "was upheld in part.")]:
        s = _summarise({"advertiserName": "EE Ltd", "date": "21 May 2025", "upheld": raw})
        assert s.endswith(sentence), (raw, s)
        assert "2025-05-21" in s


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
# Parsing the results page
# ---------------------------------------------------------------------------

def test_parses_only_the_rulings_tab_and_only_asa_links():
    items = parse_rulings_html(RULINGS_PAGE)
    # 4 formal rulings on asa.org.uk; the off-site link and the informally-resolved tab are dropped.
    assert [i["advertiserName"] for i in items] == [
        "EE Ltd t/a EE", "EE Ltd t/a EE", "Bonne Terre Ltd t/a Sky Bet", "UAB Convenity t/a Huusk"]
    assert all(i["url"].startswith("https://www.asa.org.uk/rulings/") for i in items)


def test_parses_outcome_media_and_date_from_captions():
    first, _, _, no_media = parse_rulings_html(RULINGS_PAGE)
    assert first["upheld"] == "Part upheld"
    assert first["media"] == "Internet (on own site)"
    assert first["date"] == "21 May 2025"
    assert "media" not in no_media


def test_page_without_rulings_tab_gives_nothing():
    assert parse_rulings_html("<html><body>Service unavailable</body></html>") == []


# ---------------------------------------------------------------------------
# Advertiser matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("advertiser,names,expected", [
    ("EE Ltd t/a EE", ["EE", None], True),
    ("Pure Gym Ltd", ["PureGym", None], True),
    ("Sky UK Ltd t/a NOW", ["Sky", "Sky UK Limited"], True),
    ("Bonne Terre Ltd t/a Sky Bet", ["Sky", "Sky UK Limited"], False),
    ("Bonne Terre Ltd t/a Sky Bet", ["Sky Bet", None], True),
    ("Juniper Technologies UK Ltd t/a Juniper", ["Sky", None], False),
    ("The Ltd", ["Ltd", None], False),
    ("EE Ltd", [None, None], False),
])
def test_advertiser_matches(advertiser, names, expected):
    assert advertiser_matches(advertiser, names) is expected


# ---------------------------------------------------------------------------
# fetch_asa_rulings end-to-end
# ---------------------------------------------------------------------------

async def test_known_brand_returns_its_dated_rulings_newest_first():
    http, t = _client(RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("EE", parent="EE Limited", http=http)

    assert [r["date"] for r in records] == ["2026-07-15", "2025-05-21"]
    assert all(r["kind"] == "asa_ruling" for r in records)
    assert records[0]["source_url"] == "https://www.asa.org.uk/rulings/ee-ltd-g25-1321697-ee-ltd.html"
    assert records[0]["summary"] == (
        "ASA published a ruling on 2026-07-15 concerning an advertisement by EE Ltd t/a EE. "
        "Media: Poster (digital static image). The complaint was not upheld.")
    assert len(t.calls) == 1
    assert t.calls[0].startswith(ASA_SEARCH_URL)
    assert "q=EE" in t.calls[0]


async def test_rulings_for_other_advertisers_are_dropped():
    http, _ = _client(RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("Sky", parent="Sky UK Limited", http=http)
    assert records == []  # "Sky Bet" is a different company


async def test_parent_name_also_matches():
    http, _ = _client(RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("Huusk Knives", parent="UAB Convenity", http=http)
    assert [r["date"] for r in records] == ["2025-05-28"]


async def test_the_asa_blurb_is_never_shown():
    http, _ = _client(RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("EE", http=http)
    assert records
    assert not any("misleading" in r["summary"].lower() for r in records)


async def test_no_rulings_returns_empty_list():
    http, _ = _client(NO_RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("UnknownBrand", http=http)
    assert records == []


async def test_http_error_returns_empty_list_does_not_raise():
    http, _ = _client("Server error", status=500)
    async with http:
        records = await fetch_asa_rulings("EE", http=http)
    assert records == []


async def test_network_error_returns_empty_list():
    class BrokenTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _):
            raise httpx.ConnectError("refused")
    async with httpx.AsyncClient(transport=BrokenTransport()) as http:
        records = await fetch_asa_rulings("EE", http=http)
    assert records == []


async def test_empty_brand_returns_empty_without_http_call():
    records = await fetch_asa_rulings("")
    assert records == []


async def test_no_verdict_words_in_any_summary():
    http, _ = _client(RULINGS_PAGE)
    async with http:
        records = await fetch_asa_rulings("EE", http=http)

    verdict_words = ["guilty", "convicted", "unethical", "illegal", "broke the law", "corrupt", "misleading"]
    for r in records:
        for word in verdict_words:
            assert word not in r["summary"].lower(), f"verdict word '{word}' in: {r['summary']}"
