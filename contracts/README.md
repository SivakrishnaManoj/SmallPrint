# Contracts

The extension and backend build against these files in parallel. Change them with care.

| File | What it describes |
|---|---|
| `request.schema.json` | The body the extension POSTs to `/analyse`. |
| `response.schema.json` | The full assembled result. Each section is streamed as one card. |
| `stream-event.schema.json` | One SSE event: `card` (with a payload) or `done`. |

The mock response is `fixtures/*.json`. The backend serves it until the real pipeline is live. Request examples are in `fixtures/requests/`.

## Rules

1. **Additive changes only.** Add optional fields. Never rename, remove or retype a field the other side already reads.
2. **Quote or null.** A value without a verified quote is `null`, and its card is `not_found`.
   - `cost_streams[].evidence` needs `quote` and `url`.
   - `small_print[]` needs `quote` and `url` whenever `value` is set.
   - `lock_in.evidence[]` needs one `{field, quote, url}` entry for every non-null lock-in field.
3. **Estimates are ranges.** A `usage` stream carries `units_per_month` as `{low, mid, high}` and a source `url`.
4. **No verdict words.** Write "recorded", "listed", "donated £X to Y on date".
5. **Privacy.** The request must never contain checkout page DOM, price-drift data or settings. Only the install UUID identifies a user.

`backend/server/tests/test_contracts.py` checks rules 2 to 4 on every fixture. Run it before you change a fixture or a schema.

## Decisions on the reconstructed fields

These fields were cut off in the original outline. The decisions below are final unless Johann changes them.

| Field | Decision |
|---|---|
| Cancel method | Named `lock_in.cancel_method` (the outline's `cancel_how` is not used). |
| Lock-in evidence | `lock_in.evidence[]`, one entry per non-null field. `field` is one of `min_term_months`, `exit_fee`, `notice_days`, `auto_renews`, `cancel_method`, `proprietary_refills`. |
| Record text | Named `company.records[].summary`. `kind` is `gender_pay_gap`, `donation` or `modern_slavery`. |
| Card states | `card_states` has `cost`, `lock_in`, `small_print`, `company` and `price_drift`. |
| T&C content | `request.terms[]`, see below. |

## T&C documents in the request

The extension fetches T&C pages and PDFs from the user's browser and sends them in `terms`. The field is optional.

```json
{
  "terms": [
    {"url": "https://example.com/terms", "kind": "terms", "text": "..."},
    {"url": "https://example.com/terms.pdf", "kind": "terms", "pdf_b64": "..."},
    {"url": "https://example.com/blocked", "kind": "terms", "fetch_failed": true, "error": "HTTP 403"}
  ]
}
```

- Send `text` for an HTML page (up to 500,000 characters) or `pdf_b64` for a PDF (base64, up to 20 MB). A document that is not marked `fetch_failed` must have one of them.
- `fetch_failed: true` tells the backend to fall back to Tavily search and label the card with its source. `error` says why, for display and logs.
- No user-agent rotation or other bot evasion. If a fetch fails, report it as failed.

## Check a file

```
python scripts/validate.py response fixtures/netflix.json
python scripts/validate.py request fixtures/requests/req_netflix.json
```
