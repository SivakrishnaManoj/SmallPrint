"""T&C extractor: Haiku with constrained JSON for costs, lock-in and small print (S3, #13).

Flow per document:
  text -> chunks of ~6k tokens -> one Haiku call per chunk (JSON schema output)
  -> every field through the quote verifier against that chunk -> merge -> cards.

Quote or null: a field reaches a card only if its quote is verbatim in the
chunk the model read (smallprint.verify), and for numbers, the number also
appears in the quote. Anything else is dropped and the card shows not_found.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from smallprint.verify import verify_field

from .text import CHUNK_TOKENS, chunk_text, estimate_tokens

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
MAX_INPUT_TOKENS = 8_000  # hard cap per call (CLAUDE.md)
MAX_OUTPUT_TOKENS = 4_000

# field -> JSON type of its value
FIELDS: dict[str, str] = {
    "monthly_price": "number",     # £ per month after any trial
    "trial_months": "integer",
    "trial_price": "number",       # £ per month during the trial (0 if free)
    "setup_fee": "number",         # £ one-off
    "annual_rise_gbp": "number",   # £ per month added each year
    "price_rise_terms": "string",  # e.g. "CPI + 3.9% each April"
    "min_term_months": "integer",
    "exit_fee": "string",
    "notice_days": "integer",
    "auto_renews": "boolean",
    "cancel_method": "string",
    "returns_window": "string",
    "warranty": "string",
    "seller": "string",
}
NUMERIC = {k for k, t in FIELDS.items() if t in ("number", "integer")}

LOCK_IN_FIELDS = ("min_term_months", "exit_fee", "notice_days", "auto_renews", "cancel_method")
SMALL_PRINT_LABELS = {
    "price_rise_terms": "Price rises",
    "returns_window": "Returns window",
    "warranty": "Warranty",
    "seller": "Seller",
}


def _field_schema(value_type: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "value": {"anyOf": [{"type": value_type}, {"type": "null"}]},
            "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["value", "quote"],
        "additionalProperties": False,
    }


OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {name: _field_schema(t) for name, t in FIELDS.items()},
    "required": list(FIELDS),
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""You extract facts from UK terms and conditions for a consumer browser extension.

Rule: every field needs a quote. The quote must be copied character for character from the document: a whole sentence or clause, not a summary, not reworded, not stitched from two places. If you cannot quote it, return null for both value and quote. Never guess, infer or use outside knowledge.

Fields (value type in brackets):
- monthly_price (number): monthly price in GBP after any trial.
- trial_months (integer), trial_price (number): length and monthly price of an introductory period. 0 for free.
- setup_fee (number): one-off joining, setup or activation fee in GBP.
- annual_rise_gbp (number): fixed GBP amount the monthly price rises by each year.
- price_rise_terms (string): how prices rise if it is not a fixed GBP amount, e.g. "CPI + 3.9% each April".
- min_term_months (integer): minimum contract term.
- exit_fee (string): fee for leaving early, as stated.
- notice_days (integer): notice period in days.
- auto_renews (boolean): whether the contract renews automatically.
- cancel_method (string): how to cancel, e.g. "online in your account" or "by phone".
- returns_window (string): time allowed to return a product.
- warranty (string): warranty or guarantee length.
- seller (string): legal name of the company the customer contracts with.

Numbers must appear as digits in the quote. If the document writes "one month", leave notice_days null.

Example. Document: "Membership costs £24.99 per month. You can cancel at any time."
Output: monthly_price = {{"value": 24.99, "quote": "Membership costs £24.99 per month."}}, min_term_months = {{"value": null, "quote": null}}, cancel_method = {{"value": "at any time", "quote": "You can cancel at any time."}}, and every other field {{"value": null, "quote": null}}.
"""

_SYSTEM_TOKENS = estimate_tokens(SYSTEM_PROMPT) + estimate_tokens(json.dumps(OUTPUT_SCHEMA))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _number_in_quote(value: float | int, quote: str) -> bool:
    """The number must appear as digits in the quote (29.99, 29, 1,000 ...)."""
    plain = quote.replace(",", "")
    forms = {f"{value:.2f}"}
    if float(value).is_integer():
        forms |= {str(int(value)), f"{int(value)}.00"}
    else:
        forms.add(f"{value:g}")
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", plain) for f in forms)


def verify_extraction(raw: dict[str, Any], source: str) -> dict[str, dict]:
    """Keep only fields whose quote is verbatim in ``source``. Returns {field: {value, quote}}."""
    kept: dict[str, dict] = {}
    for name, vtype in FIELDS.items():
        item = raw.get(name)
        if not isinstance(item, dict):
            continue
        ok = verify_field(item, source)
        if ok is None:
            continue
        value = ok["value"]
        if vtype == "boolean" and not isinstance(value, bool):
            continue
        if name in NUMERIC:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not _number_in_quote(value, ok["quote"]):
                continue
            if vtype == "integer":
                if not float(value).is_integer():
                    continue
                value = int(value)
        if vtype == "string" and not (isinstance(value, str) and value.strip()):
            continue
        kept[name] = {"value": value, "quote": ok["quote"]}
    return kept


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _extract_chunk(client: AsyncAnthropic, chunk: str) -> dict[str, Any]:
    if _SYSTEM_TOKENS + estimate_tokens(chunk) > MAX_INPUT_TOKENS:
        raise ValueError("chunk exceeds the 8k input cap")
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"<document>\n{chunk}\n</document>"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    if response.stop_reason != "end_turn":
        # refusal, max_tokens, ...: treat the chunk as giving nothing.
        log.warning("extractor stop_reason=%s; chunk skipped", response.stop_reason)
        return {}
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("extractor returned invalid JSON; chunk skipped")
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class Document:
    url: str
    text: str


async def extract_fields(client: AsyncAnthropic, docs: list[Document]) -> dict[str, dict]:
    """Verified fields across all documents. First verified value per field wins.

    Returns {field: {"value", "quote", "url"}}.
    """
    found: dict[str, dict] = {}
    for doc in docs:
        # Chunk size leaves room for the system prompt and schema inside the 8k cap.
        chunk_tokens = min(CHUNK_TOKENS, MAX_INPUT_TOKENS - _SYSTEM_TOKENS)
        for chunk in chunk_text(doc.text, chunk_tokens):
            raw = await _extract_chunk(client, chunk)
            for name, item in verify_extraction(raw, chunk).items():
                found.setdefault(name, {**item, "url": doc.url})
    return found


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def _evidence(f: dict) -> dict:
    return {"quote": f["quote"], "url": f["url"]}


def build_cards(found: dict[str, dict]) -> dict:
    """Map verified fields onto the response contract slices + card states."""
    cost_streams: list[dict] = []
    trial_months = found.get("trial_months", {}).get("value")
    trial = found.get("trial_price")
    has_trial = trial is not None and trial_months
    if has_trial:
        cost_streams.append({"label": "Trial", "type": "recurring", "amount": trial["value"],
                             "from_month": 1, "to_month": trial_months, "evidence": _evidence(trial)})
    if "monthly_price" in found:
        f = found["monthly_price"]
        cost_streams.append({"label": "Monthly fee", "type": "recurring", "amount": f["value"],
                             "from_month": trial_months + 1 if has_trial else 1, "evidence": _evidence(f)})
    if "setup_fee" in found:
        f = found["setup_fee"]
        cost_streams.append({"label": "Setup fee", "type": "one_off", "amount": f["value"], "evidence": _evidence(f)})
    if "annual_rise_gbp" in found and "monthly_price" in found:
        f = found["annual_rise_gbp"]
        cost_streams.append({"label": "Annual rise", "type": "step_change", "amount": f["value"],
                             "month": 13, "evidence": _evidence(f)})

    lock_in: dict[str, Any] = {name: found[name]["value"] if name in found else None for name in LOCK_IN_FIELDS}
    # Contract: one {field, quote, url} entry per non-null lock-in field.
    lock_in["evidence"] = [
        {"field": name, "quote": found[name]["quote"], "url": found[name]["url"]}
        for name in LOCK_IN_FIELDS if name in found
    ]

    small_print = [
        {"field": label, "value": _as_text(found[name]["value"]), "quote": found[name]["quote"], "url": found[name]["url"]}
        for name, label in SMALL_PRINT_LABELS.items() if name in found
    ]

    def state(present: bool) -> str:
        return "found" if present else "not_found"

    return {
        "cost_streams": cost_streams,
        "lock_in": lock_in,
        "small_print": small_print,
        "card_states": {
            "cost": state(bool(cost_streams)),
            "lock_in": state(bool(lock_in["evidence"])),
            "small_print": state(bool(small_print)),
        },
    }


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


async def analyse_documents(client: AsyncAnthropic, docs: list[Document]) -> dict:
    return build_cards(await extract_fields(client, docs))
