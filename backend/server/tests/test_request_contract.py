"""S2 (#3): install UUID header and the agreed request payload."""
from __future__ import annotations
import json
from pathlib import Path

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app

ROOT = Path(__file__).parent.parent.parent.parent
REQUEST_SCHEMA = json.loads((ROOT / "contracts" / "request.schema.json").read_text())

_REQ = {
    "item": {"name": "Netflix Standard", "brand": "Netflix", "url": "https://www.netflix.com/gb/signup"},
    "purchase_type_signals": ["subscription"],
    "links": [],
    "page_text_snippets": [],
    "price_drift": {"first_seen": None, "current": 4.99},
    "terms": [
        {"url": "https://help.netflix.com/legal/termsofuse", "text": "You can cancel at any time."},
        {"url": "https://example.com/contract.pdf", "pdf_b64": "JVBERi0xLjQK"},
        {"url": "https://example.com/blocked", "fetch_failed": True},
    ],
}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _first_event(client: AsyncClient, body: dict, headers: dict) -> int:
    async with client.stream("POST", "/analyse", json=body, headers=headers) as resp:
        return resp.status_code


async def test_install_id_header_is_accepted(client):
    assert await _first_event(client, _REQ, {"X-Install-Id": "hdr-install-1"}) == 200


async def test_body_install_id_still_works(client):
    assert await _first_event(client, {**_REQ, "install_id": "body-install-1"}, {}) == 200


async def test_missing_install_id_is_rejected(client):
    resp = await client.post("/analyse", json=_REQ)
    assert resp.status_code == 422


async def test_blank_install_id_header_is_rejected(client):
    resp = await client.post("/analyse", json=_REQ, headers={"X-Install-Id": "   "})
    assert resp.status_code == 422


def test_example_request_conforms_to_schema():
    jsonschema.validate(_REQ, REQUEST_SCHEMA)


@pytest.mark.parametrize("path", sorted((ROOT / "fixtures" / "requests").glob("*.json")), ids=lambda p: p.name)
def test_request_fixtures_conform_to_schema(path):
    jsonschema.validate(json.loads(path.read_text()), REQUEST_SCHEMA)
