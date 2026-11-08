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
    async def fake_lookup(brand, domain):
        return result
    monkeypatch.setattr(pipeline, "get_company_lookup", lambda: fake_lookup)
    [(name, got, payload)] = await pipeline.company_source(_request("Pepsi Max"))
    assert (name, got, payload) == ("company", state, result)
