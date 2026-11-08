"""The company card is "found" when the owner is known, even with no UK company number."""
import pytest

from server import pipeline
from server.models import AnalyseRequest


def _request(brand: str) -> AnalyseRequest:
    return AnalyseRequest.model_validate({
        "item": {"name": "Pepsi Max Cola 330ml 8 pack", "brand": brand, "url": "https://www.amazon.co.uk/dp/X"},
        "purchase_type_signals": ["product"], "links": [], "page_text_snippets": [],
    })


@pytest.mark.parametrize("result,state", [
    ({"brand": "Pepsi Max", "parent": "PepsiCo", "ch_number": None, "match_via": "Wikidata", "records": []}, "found"),
    ({"brand": "Pepsi Max", "parent": "PepsiCo", "ch_number": "SC127671", "match_via": "Wikidata", "records": []}, "found"),
    ({"brand": "Unknown", "parent": None, "ch_number": None, "match_via": "Brand not identified", "records": []}, "not_found"),
])
async def test_company_card_state(monkeypatch, result, state):
    async def fake_lookup(brand, domain, **_):
        return result
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: fake_lookup)
    [(name, got, payload)] = await pipeline.company_source(_request("Pepsi Max"))
    assert (name, got, payload) == ("company", state, result)


async def test_records_matched_by_name_alone_make_the_card_found(monkeypatch):
    result = {"brand": "PepsiCo", "parent": None, "ch_number": None, "match_via": "Brand name match",
              "records": [{"kind": "lgbtq_rights", "summary": "Listed by ...", "date": None, "source_url": None}]}
    async def fake_lookup(brand, domain, **_):
        return result
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: fake_lookup)
    [(_, state, _)] = await pipeline.company_source(_request("PepsiCo"))
    assert state == "found"


async def test_the_pages_manufacturer_reaches_the_lookup(monkeypatch):
    """Regression: a merge dropped manufacturer= from the call, so #85's exact UK match never ran."""
    seen = {}
    async def fake_lookup(brand, domain, **kwargs):
        seen.update(kwargs)
        return {"brand": brand, "parent": None, "ch_number": None, "match_via": "Brand not identified", "records": []}
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: fake_lookup)
    request = _request("PlayStation")
    request.item.manufacturer = "Sony Interactive Entertainment Europe Ltd"
    await pipeline.company_source(request)
    assert seen.get("manufacturer") == "Sony Interactive Entertainment Europe Ltd"


# Mock mode (no OPENAI_API_KEY): the company card comes from the real lookup, not the fixture.
from server import main  # noqa: E402

_FIXTURE = {"company": {"brand": "SodaStream", "parent": "PepsiCo (MOCK)", "records": []},
            "card_states": {"cost": "found", "company": "found"}}


async def test_mock_mode_uses_the_real_company_lookup(monkeypatch):
    owner = {"brand": "Pepsi", "parent": "PepsiCo", "ch_number": None, "match_via": "Wikidata", "records": []}
    async def fake_lookup(brand, domain, **_):
        assert brand == "Pepsi"
        return owner
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: fake_lookup)
    out = await main.company_source(_request("Pepsi"), _FIXTURE)
    assert out["company"] == owner
    assert out["card_states"] == {"cost": "found", "company": "found"}  # other states kept


async def test_mock_mode_not_identified_is_not_found(monkeypatch):
    out = await main.company_source(_request("Pepsi"), _FIXTURE)  # conftest stub: not identified
    assert out["company"]["match_via"] == "Brand not identified"
    assert out["card_states"]["company"] == "not_found"


async def test_fixture_company_on_request(monkeypatch):
    monkeypatch.setenv("SMALLPRINT_COMPANY_LOOKUP", "fixture")
    out = await main.company_source(_request("Pepsi"), _FIXTURE)
    assert out == {"company": _FIXTURE["company"]}
