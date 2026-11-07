"""S7 (#16): scripts/prewarm.py, run against the real app with the LLM faked.

The script's HTTP goes through a transport that serves T&C pages and forwards
/analyse to the FastAPI app, so the whole pre-warm path is exercised.
"""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from server import main

from .test_pipeline import GYM_TERMS, FakeLLM, tracker, use_llm  # noqa: F401

ROOT = Path(__file__).parent.parent.parent.parent
spec = importlib.util.spec_from_file_location("prewarm", ROOT / "scripts" / "prewarm.py")
prewarm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prewarm)


def write_list(tmp_path: Path, rows: str) -> Path:
    p = tmp_path / "prewarm.csv"
    p.write_text("page_url,terms_url,name\n# a comment row\n" + rows, encoding="utf-8")
    return p


def test_read_list_skips_comments_and_blanks(tmp_path):
    rows = prewarm.read_list(write_list(tmp_path, "https://a.example/,https://a.example/terms,A\n,,\nhttps://b.example/,,B\n"))
    assert [(r["page_url"], r["terms_url"], r["name"]) for r in rows] == [
        ("https://a.example/", "https://a.example/terms", "A"), ("https://b.example/", "", "B")]


def test_request_matches_the_contract():
    import json
    import jsonschema
    schema = json.loads((ROOT / "contracts" / "request.schema.json").read_text())
    for terms in ({"url": "https://a.example/t", "kind": "terms", "text": "x"},
                  {"url": "https://a.example/t", "kind": "terms", "fetch_failed": True, "error": "HTTP 403"}):
        jsonschema.validate(prewarm.build_request({"page_url": "https://a.example/", "name": "A"}, terms), schema)


def _site_transport(app_client: TestClient):
    pdf_bytes = b"%PDF-fake"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == prewarm.USER_AGENT  # honest, fixed UA
        if request.url.host == "test" and request.url.path == "/analyse":
            r = app_client.post("/analyse", content=request.content, headers=dict(request.headers))
            return httpx.Response(r.status_code, content=r.content, headers={"content-type": "text/event-stream"})
        if request.url.path == "/terms":
            return httpx.Response(200, text=GYM_TERMS, headers={"content-type": "text/html"})
        if request.url.path == "/terms.pdf":
            return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})
        return httpx.Response(403)

    return handler, pdf_bytes


def test_fetch_terms_text_pdf_and_failure():
    handler, pdf_bytes = _site_transport(None)
    with httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": prewarm.USER_AGENT}) as http:
        assert prewarm.fetch_terms(http, "https://a.example/terms")["text"] == GYM_TERMS
        assert base64.b64decode(prewarm.fetch_terms(http, "https://a.example/terms.pdf")["pdf_b64"]) == pdf_bytes
        failed = prewarm.fetch_terms(http, "https://a.example/blocked")
        assert failed["fetch_failed"] is True and failed["error"] == "HTTPStatusError"


def test_prewarm_run_fills_the_cache(monkeypatch, tmp_path, tracker, capsys):
    llm = use_llm(monkeypatch, FakeLLM())
    monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", "k")
    lst = write_list(tmp_path, "https://www.fitbox.example/join,https://www.fitbox.example/terms,Fitbox\n")

    with TestClient(main.app) as app_client:
        handler, _ = _site_transport(app_client)
        real_client = httpx.Client
        monkeypatch.setattr(prewarm.httpx, "Client",
                            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
        out = tmp_path / "results.csv"
        assert prewarm.main(["--server", "http://test", "--list", str(lst), "--out", str(out)]) == 0

    assert llm.calls == 1
    assert "1/1 sites have at least one found T&C card cached" in capsys.readouterr().out
    assert "found" in out.read_text()
    assert main.get_cache().get_site("fitbox.example") is not None


@pytest.mark.parametrize("env,exists", [(None, True), ("k", False)])
def test_refuses_to_run_without_key_or_list(monkeypatch, tmp_path, env, exists):
    if env:
        monkeypatch.setenv("SMALLPRINT_PREWARM_KEY", env)
    else:
        monkeypatch.delenv("SMALLPRINT_PREWARM_KEY", raising=False)
    lst = write_list(tmp_path, "") if exists else tmp_path / "missing.csv"
    assert prewarm.main(["--list", str(lst)]) == 2
