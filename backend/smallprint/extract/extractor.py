"""T&C extractor: OpenAI model with constrained JSON for costs, lock-in and small print (S3, #13).

Flow per document:
  text -> chunks of ~6k tokens -> one LLM call per chunk (JSON schema output)
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

from openai import AsyncOpenAI

from smallprint.spend import MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, SpendLimitReached, SpendTracker
from smallprint.tc_cache import TermsCache
from smallprint.verify import verify_field

from .text import CHUNK_TOKENS, chunk_text, estimate_tokens

log = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

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
- returns_window (string): time allowed to return a product, as a length of time with digits, e.g. "30 days". Not a condition ("in new and unused condition") or a cost ("free returns").
- warranty (string): warranty or guarantee length.
- seller (string): legal name of the company the customer contracts with. Not a credit broker or lender.

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


# "30 days", "28 calendar days", "2-week", "12 months"
_DURATION = re.compile(r"(?<![\d.])(\d+)\s*-?\s*(?:[a-z]+\s+)?(?:day|week|month|year)s?\b", re.IGNORECASE)


def _is_duration_in_quote(value: str, quote: str) -> bool:
    """A returns window is a length of time: digits plus a unit, and the number is in the quote.

    40-URL run 2026-11-08: Amazon pages gave "for free", "in new and unused condition" and
    "for a full refund with no deduction for return shipping": verbatim quotes, not a window.
    """
    m = _DURATION.search(value)
    return bool(m) and _number_in_quote(int(m.group(1)), quote)


def _names_a_credit_broker(quote: str) -> bool:
    """Amazon's "Credit broker: Amazon EU S.A.R.L." is the finance offer, not who sells the item."""
    return "credit broker" in quote.lower()


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
        if name == "returns_window" and not _is_duration_in_quote(value, ok["quote"]):
            continue
        if name == "seller" and (_names_a_credit_broker(ok["quote"])
                                 or value.strip().lower() not in ok["quote"].lower()):
            continue  # a company name is quoted as written ("Spotify Ltd" from a line without it, 2026-11-08)
        kept[name] = {"value": value, "quote": ok["quote"]}
    return kept


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _extract_chunk(client: AsyncOpenAI, chunk: str, install_id: str | None,
                         tracker: SpendTracker | None, system: str | None = None,
                         schema: dict | None = None) -> dict[str, Any] | None:
    """The model's JSON for one chunk, or None if this chunk failed (refusal, cut off, bad JSON).

    ``system`` and ``schema`` default to the T&C extraction prompt and schema.
    """
    system = system or SYSTEM_PROMPT
    schema = schema or OUTPUT_SCHEMA
    input_tokens = estimate_tokens(system) + estimate_tokens(json.dumps(schema)) + estimate_tokens(chunk)
    if input_tokens > MAX_INPUT_TOKENS:
        raise ValueError("chunk exceeds the 8k input cap")

    async def call():
        return await client.chat.completions.create(
            model=MODEL,
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"<document>\n{chunk}\n</document>"},
            ],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "extraction", "strict": True, "schema": schema}},
        )

    if tracker is None:
        response = await call()
    else:
        # Raises SpendLimitReached before the call if today's limit is used up.
        async with tracker.guard(install_id or "", input_tokens, MAX_OUTPUT_TOKENS) as usage:
            response = await call()
            usage.input_tokens = response.usage.prompt_tokens
            usage.output_tokens = response.usage.completion_tokens
    choice = response.choices[0]
    if choice.finish_reason != "stop" or choice.message.refusal:
        # refusal, length cut-off, content filter: treat the chunk as giving nothing.
        log.warning("extractor finish_reason=%s; chunk skipped", choice.finish_reason)
        return None
    text = choice.message.content
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("extractor returned invalid JSON; chunk skipped")
        return None
    return data if isinstance(data, dict) else None


@dataclass
class Document:
    url: str
    text: str
    # None: fetched by the user's browser. Otherwise how we got it, e.g. "tavily_search";
    # every value from this document is labelled with it (source_step).
    source: str | None = None


async def extract_fields(client: AsyncOpenAI, docs: list[Document], install_id: str | None = None,
                         tracker: SpendTracker | None = None,
                         cache: TermsCache | None = None) -> tuple[dict[str, dict], bool]:
    """Verified fields across all documents. First verified value per field wins.

    With a ``tracker``, every call is charged to ``install_id``; once the daily
    limit is reached no further calls are made.

    With a ``cache``, a document whose exact text was extracted before is served
    from the cache with no LLM call, and a fully extracted document is stored.
    A document is only stored if every chunk succeeded, so a refusal or a spend
    limit hit is never cached as "nothing found".

    Returns ({field: {"value", "quote", "url", "source"}}, limit_reached).
    """
    found: dict[str, dict] = {}
    for doc in docs:
        cached = cache.get_doc(doc.url, doc.text, doc.source) if cache else None
        if cached is not None:
            for name, item in cached.items():
                found.setdefault(name, item)
            continue

        doc_fields: dict[str, dict] = {}
        complete = True
        # Chunk size leaves room for the system prompt and schema inside the 8k cap.
        chunk_tokens = min(CHUNK_TOKENS, MAX_INPUT_TOKENS - _SYSTEM_TOKENS)
        for chunk in chunk_text(doc.text, chunk_tokens):
            try:
                raw = await _extract_chunk(client, chunk, install_id, tracker)
            except SpendLimitReached:
                for name, item in doc_fields.items():
                    found.setdefault(name, item)
                return found, True
            if raw is None:
                complete = False
                continue
            for name, item in verify_extraction(raw, chunk).items():
                doc_fields.setdefault(name, {**item, "url": doc.url, "source": doc.source})
        if cache and complete:
            cache.put_doc(doc.url, doc.text, doc.source, doc_fields)
        for name, item in doc_fields.items():
            found.setdefault(name, item)
    return found, False


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def _labelled(row: dict, f: dict) -> dict:
    """Add source_step when the value came from a fallback source (e.g. search)."""
    if f.get("source"):
        row["source_step"] = f["source"]
    return row


def _evidence(f: dict) -> dict:
    return _labelled({"quote": f["quote"], "url": f["url"]}, f)


def build_cards(found: dict[str, dict], limit_reached: bool = False) -> dict:
    """Map verified fields onto the response contract slices + card states.

    If the spend limit cut extraction short, a card with nothing verified shows
    ``limit_reached`` instead of ``not_found``: we didn't look, rather than
    looked and found nothing. Verified values found before the limit still show.
    """
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
        _labelled({"field": name, "quote": found[name]["quote"], "url": found[name]["url"]}, found[name])
        for name in LOCK_IN_FIELDS if name in found
    ]

    small_print = [
        _labelled({"field": label, "value": _as_text(found[name]["value"]), "quote": found[name]["quote"],
                   "url": found[name]["url"]}, found[name])
        for name, label in SMALL_PRINT_LABELS.items() if name in found
    ]

    def state(present: bool) -> str:
        if present:
            return "found"
        return "limit_reached" if limit_reached else "not_found"

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


async def analyse_documents(client: AsyncOpenAI, docs: list[Document], install_id: str | None = None,
                            tracker: SpendTracker | None = None) -> dict:
    found, limit_reached = await extract_fields(client, docs, install_id, tracker)
    return build_cards(found, limit_reached)
