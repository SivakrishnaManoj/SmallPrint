# `POST /analyse` request

The machine-readable version is `contracts/request.schema.json`.

## Headers

| Header | Required | Value |
|---|---|---|
| `Content-Type` | yes | `application/json` |
| `X-Install-Id` | yes | the install UUID from `chrome.storage.local` |

`install_id` in the body still works but is deprecated. Move it to the header.

## Body

```json
{
  "item": {"name": "Netflix Standard", "brand": "Netflix", "seller": null, "price": 4.99, "url": "https://www.netflix.com/gb/signup", "id": null},
  "purchase_type_signals": ["subscription"],
  "links": [{"url": "https://help.netflix.com/legal/termsofuse", "text": "Terms of Use", "kind": "terms"}],
  "page_text_snippets": ["Cancel anytime."],
  "price_drift": {"first_seen": null, "current": null},
  "terms": [
    {"url": "https://help.netflix.com/legal/termsofuse", "text": "<T&C page text>"},
    {"url": "https://example.com/contract.pdf", "pdf_b64": "<base64 PDF bytes>"},
    {"url": "https://example.com/blocked", "fetch_failed": true}
  ]
}
```

| Field | What it is |
|---|---|
| `item` | The detected item. `url` is the page URL. |
| `purchase_type_signals` | Any of `product`, `subscription`, `contract`. |
| `links` | T&C, returns, cancel and similar links found on the page. |
| `page_text_snippets` | Page text the extension thinks is relevant (offer, price, terms wording). |
| `terms` | T&C documents fetched in the user's browser. HTML pages send `text`, PDFs send `pdf_b64`, and a failed fetch sends `fetch_failed: true` with no content (the backend then falls back to Tavily and labels the card). |
| `price_drift` | Being removed in V1 (#29): price-drift data must not leave the browser. The schema still requires the field until #45 removes it, so send both values as `null`. |

## Response

`text/event-stream`. One `card` event per card, then a `done` event:

```
event: card
data: {"card": "cost", "state": "found", "payload": {...}}

event: done
data: {}
```

Each `card` event conforms to `contracts/stream-event.schema.json`.

## Try it

```bash
curl -N -X POST http://localhost:8000/analyse \
  -H "Content-Type: application/json" \
  -H "X-Install-Id: test-install" \
  -d @fixtures/requests/req_netflix.json
```
