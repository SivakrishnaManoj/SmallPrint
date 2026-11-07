#!/usr/bin/env python3
"""Coverage test: POST each URL in urls.csv to /analyse, collect card states.

Usage:
    python scripts/run_coverage.py [--server http://localhost:8000] [--out results/coverage.csv]
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    sys.exit("Install httpx: pip install httpx")

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
FIXTURE_REQ_DIR = REPO_ROOT / "fixtures" / "requests"

CARD_NAMES = ["item", "cost", "price_drift", "lock_in", "small_print", "company"]


def load_fixture_request(url: str) -> dict[str, Any] | None:
    """Return a saved request fixture if one exists for this URL's domain."""
    url_lower = url.lower()
    for path in FIXTURE_REQ_DIR.glob("*.json"):
        req = json.loads(path.read_text())
        if req.get("item", {}).get("url", "").lower() == url_lower:
            return req
    return None


def build_minimal_request(url: str, install_id: str = "coverage-test-runner") -> dict[str, Any]:
    """Build the smallest valid request body for a URL."""
    return {
        "item": {"name": None, "brand": None, "price": None, "seller": None, "url": url, "id": None},
        "purchase_type_signals": [],
        "links": [],
        "page_text_snippets": [],
        "price_drift": {"first_seen": None, "current": None},
        "install_id": install_id,
    }


def collect_sse_events(response: httpx.Response) -> tuple[list[dict], str | None]:
    """Parse SSE lines into card events; return (cards, error_message)."""
    cards: list[dict] = []
    event_name: str | None = None
    try:
        for line in response.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                try:
                    data = json.loads(data_str)
                    if event_name == "card":
                        cards.append(data)
                    elif event_name == "done":
                        break
                except json.JSONDecodeError:
                    pass
                event_name = None
    except Exception as exc:
        return cards, str(exc)
    return cards, None


def summarise(results: list[dict]) -> None:
    total = len(results)
    detected = sum(1 for r in results if r["detected"])
    wrong_type = sum(1 for r in results if r["wrong_type"])
    crashes = sum(1 for r in results if r["crash"])
    state_counts: dict[str, int] = {}
    for r in results:
        for state in r.get("states", {}).values():
            state_counts[state] = state_counts.get(state, 0) + 1

    print(f"\n=== Coverage summary ({total} URLs) ===")
    print(f"Purchase detected:    {detected}/{total}")
    print(f"Wrong type:           {wrong_type}")
    print(f"Crashes:              {crashes}")
    print("Card states:")
    for state, count in sorted(state_counts.items()):
        print(f"  {state:<12} {count}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--out", default="results/coverage.csv")
    args = parser.parse_args()

    urls_path = SCRIPTS_DIR / "urls.csv"
    if not urls_path.exists():
        sys.exit(f"urls.csv not found at {urls_path}")

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with open(urls_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        url_rows = list(reader)

    print(f"Testing {len(url_rows)} URLs against {args.server}")

    fieldnames = ["url", "expected_type", "detected", "detected_types", "wrong_type",
                  "states_csv", "crash", "error", "latency_s", "notes"]

    with httpx.Client(timeout=30) as client:
        for i, row in enumerate(url_rows, 1):
            url = row["url"].strip()
            expected_type = row["expected_type"].strip()
            notes = row.get("notes", "")
            print(f"[{i:02d}/{len(url_rows)}] {url[:70]}", end="", flush=True)

            request_body = load_fixture_request(url) or build_minimal_request(url)
            start = time.monotonic()
            crash = False
            error_msg = ""
            cards: list[dict] = []

            try:
                with client.stream("POST", f"{args.server}/analyse", json=request_body) as resp:
                    if resp.status_code != 200:
                        crash = True
                        error_msg = f"HTTP {resp.status_code}"
                    else:
                        cards, err = collect_sse_events(resp)
                        if err:
                            error_msg = err
            except Exception as exc:
                crash = True
                error_msg = str(exc)

            latency = round(time.monotonic() - start, 2)

            # Determine detection and states
            item_card = next((c for c in cards if c.get("card") == "item"), None)
            detected = item_card is not None and item_card.get("state") not in ("n_a",)
            detected_types_raw = request_body.get("purchase_type_signals", [])

            states = {c["card"]: c.get("state", "?") for c in cards}
            states_csv_str = "|".join(f"{k}={v}" for k, v in states.items())

            # Simple wrong-type check: n_a when product/subscription/contract expected, or vice versa
            wrong_type = False
            if expected_type == "none" and detected:
                wrong_type = True
            elif expected_type != "none" and not detected and not crash:
                wrong_type = True

            result = {
                "url": url,
                "expected_type": expected_type,
                "detected": detected,
                "detected_types": ",".join(detected_types_raw),
                "wrong_type": wrong_type,
                "states_csv": states_csv_str,
                "crash": crash,
                "error": error_msg,
                "latency_s": latency,
                "notes": notes,
            }
            rows.append(result)

            status = "WRONG_TYPE" if wrong_type else ("CRASH" if crash else "ok")
            print(f"  [{status}] {latency}s")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nResults written to {out_path}")
    summarise(rows)


if __name__ == "__main__":
    main()
