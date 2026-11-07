"""S6 (#15): Tavily search for T&C pages the browser couldn't fetch. Tavily is faked at HTTP."""
from __future__ import annotations

import json

import httpx
import pytest

from smallprint.search_fallback import SOURCE, TAVILY_URL, TavilySearch, from_env, site_of


def tavily(results: list[dict] | None = None, status: int = 200, raise_exc: Exception | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if raise_exc:
            raise raise_exc
        if status != 200:
            return httpx.Response(status, json={"detail": {"error": "nope"}})
        return httpx.Response(200, json={"query": "q", "answer": None, "images": [], "response_time": 0.4,
                                         "results": results or []})

    search = TavilySearch("tvly-test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return search, seen


def result(url: str, raw: str | None = "Full terms text.", content: str = "snippet") -> dict:
    return {"title": "Terms", "url": url, "content": content, "score": 0.9, "raw_content": raw}


async def test_request_is_one_plain_tavily_search_restricted_to_the_site():
    search, seen = tavily([result("https://www.fitbox.example/legal/terms")])
    await search.find_terms("https://www.fitbox.example/terms", "Fitbox", "terms")

    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == TAVILY_URL and req.method == "POST"
    assert req.headers["Authorization"] == "Bearer tvly-test"
    body = json.loads(req.content)
    assert body["include_domains"] == ["fitbox.example"]
    assert body["query"] == "Fitbox terms and conditions"
    assert body["search_depth"] == "basic"  # 1 credit
    assert body["include_raw_content"] == "text"
    assert "api_key" not in body  # key only in the header


async def test_results_become_labelled_documents_with_their_own_urls():
    search, _ = tavily([
        result("https://fitbox.example/legal/terms", raw="Full terms."),
        result("https://help.fitbox.example/cancel", raw=None, content="Cancel online."),
    ])
    docs = await search.find_terms("https://fitbox.example/terms", "Fitbox")
    assert [(d.url, d.text, d.source) for d in docs] == [
        ("https://fitbox.example/legal/terms", "Full terms.", SOURCE),
        ("https://help.fitbox.example/cancel", "Cancel online.", SOURCE),  # snippet when no raw content
    ]


async def test_other_sites_empty_and_duplicate_results_are_dropped():
    search, _ = tavily([
        result("https://rival-gym.example/terms"),          # another company: never
        result("https://notfitbox.example/terms"),          # look-alike domain: never
        result("https://fitbox.example/terms", raw="", content=" "),
        result("https://fitbox.example/legal"),
        result("https://fitbox.example/legal"),
    ])
    docs = await search.find_terms("https://fitbox.example/terms", "Fitbox")
    assert [d.url for d in docs] == ["https://fitbox.example/legal"]


@pytest.mark.parametrize("kind,query", [("returns", "Acme returns policy"), ("cancel", "Acme how to cancel"),
                                        ("unknown-kind", "Acme terms and conditions")])
async def test_query_follows_the_document_kind(kind, query):
    search, seen = tavily([])
    await search.find_terms("https://acme.example/x", "Acme", kind)
    assert json.loads(seen[0].content)["query"] == query


@pytest.mark.parametrize("kw", [{"status": 401}, {"status": 432}, {"status": 500},
                                {"raise_exc": httpx.ConnectTimeout("slow")}])
async def test_any_tavily_failure_gives_no_documents(kw):
    search, _ = tavily(**kw)
    assert await search.find_terms("https://fitbox.example/terms", "Fitbox") == []


async def test_url_without_a_host_makes_no_call():
    search, seen = tavily([result("https://fitbox.example/terms")])
    assert await search.find_terms("not a url", "Fitbox") == []
    assert seen == []


def test_site_of():
    assert site_of("https://www.Fitbox.example/terms?x=1") == "fitbox.example"
    assert site_of("https://help.fitbox.example/") == "help.fitbox.example"
    assert site_of("nope") is None


def test_no_key_no_fallback(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert from_env() is None
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    assert isinstance(from_env(), TavilySearch)
