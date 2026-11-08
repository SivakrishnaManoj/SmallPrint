#!/usr/bin/env python3
"""Pre-warm the T&C cache on a running server (S7, #16).

For each site in the list, fetch its T&C page, POST it to /analyse with the
pre-warm key, and report the card states. After this, a visitor to any of
those sites gets cached T&C cards with no fetch, search or LLM call.

Run it after the final deploy (the cache is in memory, so a redeploy empties it):

    SMALLPRINT_PREWARM_KEY=... python scripts/prewarm.py --server https://smallprint-production.up.railway.app

The server needs the same SMALLPRINT_PREWARM_KEY set. Without it the requests
are treated as a normal install and hit the normal daily spend limit.

List format (CSV, header row): page_url,terms_url,name
  page_url   a shopping or sign-up page on the site (its domain is the cache key)
  terms_url  the T&C page or PDF; leave blank to let the server find it with search
  name       brand or product name (used in the search query)

No bot evasion: one plain GET per T&C page with an honest user agent. If a
site refuses, the request says so (fetch_failed) and the server falls back to search.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LIST = REPO / "demo" / "prewarm.csv"
USER_AGENT = "SmallPrint-prewarm/0.1 (+https://github.com/j0h4nn1410/SmallPrint)"
TERMS_CARDS = ("cost", "lock_in", "small_print")


def read_list(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        # k is None for overflow cells (e.g. commas in a comment row): ignore them.
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in csv.DictReader(f)]
    return [r for r in rows if r.get("page_url") and not r["page_url"].startswith("#")]


def fetch_terms(http: httpx.Client, url: str) -> dict:
    """One T&C document for the request: text, pdf_b64, or fetch_failed."""
    try:
        resp = http.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"url": url, "kind": "terms", "fetch_failed": True, "error": type(e).__name__}
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return {"url": url, "kind": "terms", "pdf_b64": base64.b64encode(resp.content).decode()}
    if not resp.text.strip():
        return {"url": url, "kind": "terms", "fetch_failed": True, "error": "empty"}
    return {"url": url, "kind": "terms", "text": resp.text[:500_000]}


def build_request(row: dict, terms: dict) -> dict:
    return {
        "item": {"name": row.get("name") or None, "brand": row.get("name") or None, "url": row["page_url"]},
        "purchase_type_signals": [],
        "links": [],
        "page_text_snippets": [],
        "terms": [terms],
    }


def parse_sse(lines) -> dict[str, str]:
    """{card: state} from an /analyse SSE stream."""
    states: dict[str, str] = {}
    event = None
    for line in lines:
        line = line.strip()
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event == "card":
            data = json.loads(line.split(":", 1)[1].strip())
            states[data["card"]] = data["state"]
    return states


def prewarm_one(http: httpx.Client, server: str, key: str, row: dict) -> dict:
    terms = fetch_terms(http, row["terms_url"]) if row.get("terms_url") else \
        {"url": row["page_url"], "kind": "terms", "fetch_failed": True, "error": "no terms_url in list"}
    start = time.monotonic()
    with http.stream("POST", f"{server.rstrip('/')}/analyse", json=build_request(row, terms),
                     headers={"X-Install-Id": "prewarm", "X-Prewarm-Key": key}, timeout=60) as resp:
        resp.raise_for_status()
        states = parse_sse(resp.iter_lines())
    return {
        "page_url": row["page_url"],
        "fetched": "failed" if terms.get("fetch_failed") else "ok",
        **{c: states.get(c, "missing") for c in TERMS_CARDS},
        "seconds": round(time.monotonic() - start, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--list", type=Path, default=DEFAULT_LIST)
    ap.add_argument("--out", type=Path, default=None, help="optional CSV of results")
    args = ap.parse_args(argv)

    key = os.environ.get("SMALLPRINT_PREWARM_KEY")
    if not key:
        print("Set SMALLPRINT_PREWARM_KEY (the same value as on the server).", file=sys.stderr)
        return 2
    if not args.list.exists():
        print(f"No site list at {args.list}. Copy demo/prewarm.example.csv to it and fill it in.", file=sys.stderr)
        return 2

    rows = read_list(args.list)
    results = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True) as http:
        for i, row in enumerate(rows, 1):
            try:
                r = prewarm_one(http, args.server, key, row)
            except httpx.HTTPError as e:
                r = {"page_url": row["page_url"], "fetched": "?", **{c: f"error: {type(e).__name__}" for c in TERMS_CARDS},
                     "seconds": 0}
            results.append(r)
            print(f"[{i}/{len(rows)}] {r['page_url']}  fetch={r['fetched']}  "
                  + "  ".join(f"{c}={r[c]}" for c in TERMS_CARDS) + f"  {r['seconds']}s")

    warmed = sum(any(r[c] == "found" for c in TERMS_CARDS) for r in results)
    print(f"\n{warmed}/{len(results)} sites have at least one found T&C card cached.")
    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]) if results else ["page_url"])
            w.writeheader()
            w.writerows(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
