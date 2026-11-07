# Small Print

**Pitch:** A Chrome extension that shows the real cost of whatever you're about to buy, what you'd be locked into, and the public record of the company behind it. It works on any shopping, subscription or contract page. Evidence, not verdicts.

**Tracks:** Lloyds is primary. G-Research (make the invisible visible) and HRT (data for decisions) are secondary.

**Product review (source of truth for scope):** https://claude.ai/artifact/UHNMVFrABemkAfuSdSbWL4

## Scope

**In (must ship):**
1. **Purchase detection.** Amazon adapter, generic JSON-LD, and subscription/contract wording. On any other page the badge greys out and the panel shows one card: "No purchase detected on this page — try a product, subscription or checkout page."
2. **Lifetime cost for subscriptions and contracts.** Trial then full price, renewals, setup fees, annual rises and exit fee over a 12 or 24 month horizon.
3. **Lock-in and small print.** Minimum term, auto-renewal, notice period, how to cancel, exit fee, returns window, warranty and real seller, each with a verbatim quote and a link.
4. **Who's behind it, plus the company record.** Brand → parent → Companies House number via Wikidata → GLEIF → Companies House. Records come from gender pay gap, political donations and modern slavery statements, filtered by the user's values.
5. **Side panel and first-run form.** Cards stream in over SSE. The first-run form asks only for horizon and values, and Skip sets the defaults (12 months, every kind of record shown).

**Gated:** refill cost for products. It ships only if, at hour 10, at least 7 of 10 Amazon test products return a refill price with a source.

**Cut order (after must-ship is green):** price drift, then the "Wrong company?" link (only after the 40-URL test passes), then ASA rulings, then the browser-use refill agent.

**Out:** travel cost, postcode, geocoding, B Corp, ethics scores, fuzzy company matching, adapters beyond Amazon and JSON-LD before hour 10, Chrome Web Store publishing.

## Repo layout
- `extension/`: MV3 extension in TypeScript with a Preact UI and `chrome.sidePanel`. It detects purchases, fetches T&C pages and PDFs from the user's browser, and recalculates usage sliders locally.
- `backend/`: Python FastAPI on Railway. It runs `POST /analyse`, which streams cards over SSE using `asyncio.gather` across lookups, and uses httpx, trafilatura, PyMuPDF, the Anthropic SDK and Tavily.
- `data/`: loaders that turn the three government CSVs into `data/records.sqlite`, keyed on Companies House number.
- `shared/schema.json`: the response schema below, plus `shared/mock.json`, which the backend serves until the real pipeline is live.
- `demo/`: `urls40.txt`, the 40-URL test script and its results, and pre-warm lists.

## Response schema (`shared/schema.json`)
Some lines in outline v2 were cut off in the PDF. Fields marked `*` are reconstructed and need Rory to confirm them.
```json
{
  "purchase_types": ["product", "subscription", "contract"],
  "item": {"name": "", "brand": "", "seller": "", "url": "", "id": ""},
  "cost_streams": [
    {"label": "Monthly fee", "type": "recurring", "amount": 29.99, "from_month": 1, "to_month": 24, "evidence": {"quote": "", "url": ""}},
    {"label": "Annual rise", "type": "step_change", "amount": 3.00, "month": 13, "evidence": {"quote": "", "url": ""}},
    {"label": "Device", "type": "one_off", "amount": 89.99, "evidence": {"quote": "", "url": ""}},
    {"label": "CO2 cylinder", "type": "usage", "unit_price": 14.99, "units_per_month": {"low": 0, "mid": 0, "high": 0}, "evidence": {"source": "", "url": ""}}
  ],
  "lock_in": {"min_term_months": 24, "exit_fee": "", "notice_days": 30, "auto_renews": true, "cancel_how*": "", "evidence*": [{"field": "", "quote": "", "url": ""}]},
  "small_print": [{"field": "", "value": "", "quote": "", "url": ""}],
  "company": {"brand": "", "parent": "", "ch_number": "", "match_via": "", "records": [{"kind*": "gender_pay_gap|donation|modern_slavery", "date*": "", "text*": "", "source_url*": ""}]},
  "price_drift": {"first_seen": 25.00, "at_checkout": 31.50, "added": []},
  "card_states": {"cost": "found|estimated|not_found|n_a", "lock_in*": "", "company*": "", "records*": "", "price_drift*": ""}
}
```
Keep the schema backward-compatible. The extension and backend teams build against it in parallel.

## Checkpoints (hours from build start; 24-hour event)
- **H1:** The backend skeleton is on Railway, and `/analyse` streams `shared/mock.json`. The extension renders the mock.
- **H2:** `data/records.sqlite` is built. Check whether the modern slavery CSV has a company number. If it doesn't, join on exact name only.
- **H6:** Must-ship works end to end on Amazon and on 3 UK subscription pages.
- **H10:** Refill gate (7 of 10). Run the first full 40-URL test.
- **H18:** Feature freeze. After this point there's only polish, the pre-warm of about 50 sites, and the pitch.
- **H19:** Record the backup demo video.

## Definition of done: the 40-URL test
URLs are picked by someone who didn't build the adapters: about 15 Amazon products, 10 UK subscriptions, 10 other JSON-LD retailers and 5 pages that aren't purchases.
- 100% show a correct state (found, estimated, not found or doesn't apply), with no spinner that never resolves.
- Zero wrong values.
- At least 60% show one or more found cards.
- Page-derived cards in under 2 s, company and cached T&Cs in under 5 s, new T&C extraction streamed within about 20 s.

## Rules for agents working in this repo
- **Quote or null.** Every extracted field needs a verbatim quote, and code checks it appears in the source text before it's emitted. If the check fails, the card shows `not_found`. Never show an LLM value without a verified quote.
- **Estimates are labelled.** Usage and refill numbers are `{low, mid, high}` ranges with a source and the state `estimated`.
- **No verdict words.** Write "recorded", "listed", "donated £X to Y on <date>". Never "unethical" or "broke the law". Show lawsuits only as allegations.
- **No fuzzy matches.** Records join only on Companies House number or exact displayed name. Otherwise show "No public records matched".
- **Privacy.** Settings stay in `chrome.storage.local`. Checkout page DOM and price-drift data never leave the browser. The backend receives only product, offer and T&C content plus the install UUID header.
- **No bot evasion.** No user-agent rotation. If the extension's fetch fails, fall back to Tavily search and label the card that way.
- **LLM.** Use `claude-haiku-5-5` with constrained JSON output. Chunk T&Cs to about 6k tokens, cap input at 8k tokens per call, and log a daily spend limit per install.
- **Read-only.** Never click, fill in a form or complete a purchase for the user.
- **Scope.** Don't add features that aren't listed under In. Ask first.

## Agent skills

### Issue tracker

Issues and specs are GitHub issues on j0h4nn1410/SmallPrint, managed with the gh CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
