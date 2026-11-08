# extension/

Owned by Siv. MV3 Chrome extension: purchase detection, side panel host, DOM scraping, price-drift tracking.

Do not edit from other workstreams.

## Current state (H1–H6)

**Purchase detection (W3).** `src/detect/` has one pure function, `detectPurchase(url, document)`. It returns either a purchase request, in the `/analyse` body shape, or `{ status: "none" }`, plus a `checkout` flag. It only reads the DOM: it never changes it and makes no `chrome.*` or network calls. It runs in the content script and in Node tests alike. The detectors are tried in this order, and the first hit wins:

1. `amazon.ts`: the Amazon adapter (product pages on any Amazon storefront).
2. `jsonld.ts`: a generic schema.org `Product` + `Offer` in JSON-LD.
3. `wording.ts`: subscription or contract wording plus a price, for pages with no structured data.

The shared steps add the T&C-type links (`links.ts`), short snippets about money or terms (`snippets.ts`) and the purchase-type signals. The snippets drop anything that looks like an email address, postcode, phone or card number, or a "Delivering to…" line. On checkout pages no page text is sent at all (`contracts/README.md`, rule 5); the request carries only the item and the T&C links. Checkout pages (`checkout.ts`) light the toolbar badge "£". The content script stores each tab's result in `chrome.storage.session`, and the side panel analyses the active tab's result. If there's no purchase, it says so and offers the demo request. No other site adapters before H10.

**First run and privacy.** Installing the extension opens a setup tab (`options.html`). It asks only for the cost horizon (12 or 24 months) and which company record kinds to flag. **Skip** saves 12 months and every kind, and the panel works straight away. Settings live in `chrome.storage.local`. The panel's **Settings** button reopens the form, and if the setup tab was closed unanswered, the panel shows the form itself.

On install the extension makes a random UUID (`crypto.randomUUID()`) and stores it as `install_id`. Every `/analyse` call sends it as the `X-Install-Id` header. That header is the only thing about the user that leaves the browser. The body is rebuilt from an allowlist of page-data fields, and the request goes with `credentials: "omit"` and `referrerPolicy: "no-referrer"`. Settings and any postcode never leave the device.

To check it yourself: open the panel, right-click → **Inspect** → **Network**, and select the `/analyse` request.

The side panel POSTs the active tab's detected purchase to the backend's `/analyse`, reads the SSE stream and renders each card as it arrives. The card components come from `panel/src` through the `~panel` alias, so the panel workstream stays the single source of the UI. The canned request (`fixtures/requests/req_sodastream.json`) is only offered on non-purchase pages in development builds (`npm run watch`), as a developer aid.

```
src/detect/              detectPurchase(url, document): pure, tested over fixtures/pages without a browser
src/content.ts           runs detectPurchase on each page (read-only), reports to the service worker
src/background.ts        toolbar icon opens the side panel; install → UUID + setup tab; checkout badge
src/options/main.tsx     first-run / settings tab (FirstRunForm without the postcode field)
src/settings.ts          settings + setup_done flag in chrome.storage.local
src/install.ts           anonymous install UUID
src/sidepanel/App.tsx    panel UI: setup gate, Settings link, analyses the active tab's detection, Re-run / Retry
src/sse.ts               POST + SSE client with connect/idle/total timeouts
src/config.ts            default server URL, canned request, timeouts
public/manifest.json     MV3 manifest (copied into dist/)
```

## Run it

```bash
# 1. backend
cd backend && uvicorn server.main:app --port 8000

# 2. extension
cd extension && npm install && npm run build
```

Then open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick `extension/dist`. Open a product, subscription or checkout page, click the SmallPrint toolbar icon (pin it from the puzzle-piece menu), and the side panel opens with the six cards appearing one at a time. The backend serves fixtures instead of real analysis when it has no `OPENAI_API_KEY` (mock mode).

- To use another backend (ngrok, Railway), click **Server** in the panel. The URL is saved in `chrome.storage.local`. You can also build with `VITE_SERVER_URL=https://… npm run build`. Hosts outside `localhost`, `*.ngrok-free.app` and `*.up.railway.app` must be added to `host_permissions` in the manifest.
- `npm run watch` rebuilds on change. Then click reload on the extension card and reopen the panel.

## T&C fetcher (W4)

Before posting the request, the panel fetches up to 3 of the page's T&C links (`src/terms/fetchTerms.ts`), preferring terms, then contract summary, subscription, cancel, price guide, returns and warranty. It sends them as `terms` (see `contracts/request.schema.json`):

| Fetched | Sent as |
|---|---|
| HTML or plain-text page | `{url, kind, text}`; the backend strips the HTML. Pages over 500,000 characters are cut, not dropped. |
| PDF (by content type, or bytes starting `%PDF-`) | `{url, kind, pdf_b64}`, up to about 15 MB |
| HTTP error, network error, 10 s timeout, empty, unsupported type, too large | `{url, kind, fetch_failed: true, error}`, so the backend falls back to search |

It's a plain `fetch`: the browser's own User-Agent, no retries with other headers, no bot evasion. Cookies and the referrer aren't sent. The demo request skips fetching, because its links are fixtures. Access to any site comes from the content script's `http(s)://*/*` match patterns, which Chrome treats as host permissions, so no new permission is needed.

## Saved pages

`fixtures/pages/<name>.html` each has a `<name>.expected.json` beside it, holding the page URL and the reviewed detection. `test/detect.test.ts` checks each page against its expected file, and also covers detector order and that the DOM is left unchanged. The pages are:

- Amazon product
- JSON-LD retailer
- UK gym subscription
- broadband checkout
- an article that only mentions subscriptions
- Amazon search results
- Amazon checkout

The pages are hand-trimmed copies built on the real DOM structure of each site type (Amazon's element IDs, JSON-LD in `@graph`). To add a real one:

1. In Chrome, use **Save page as → Webpage, HTML only** and save it to `fixtures/pages/`.
2. Add its URL to `test/pages.ts`.
3. Write `<name>.expected.json` by hand, and review it before committing.

## The spinner always stops

`streamAnalyse` ends every run with either `event: done` or a thrown `AnalyseError`, and the UI clears its spinner in `finally`. The error kinds are:

| kind | when |
|---|---|
| `network` | server unreachable / CORS / DNS |
| `http` | non-2xx (e.g. 429 rate limit) |
| `not_sse` | response isn't `text/event-stream` (e.g. ngrok interstitial page) |
| `timeout` | no headers in 10 s, no bytes for 20 s, or 60 s total (pings can't keep it alive forever) |
| `ended_early` | stream closed without `event: done` |

## Tests

```bash
npm test                                # detection over saved pages, T&C fetcher, SSE client (vitest, no browser)
npm run build && npm run e2e            # loads dist/ in Chromium against a running backend
npm run test40                          # the 40-URL test on the real internet; prints the pass-bar report (see demo/README.md)
```

Playwright is a devDependency, so `npm ci` installs it. Run `npx playwright install chromium` once if the browser is missing. `npm run e2e` checks these things:

- Installing opens the setup form, which asks only for horizon and record kinds.
- Skip stores the defaults, and the panel then works.
- The network trace shows `X-Install-Id` as the only non-standard header, with no cookie or referer, and a body holding page data only.
- The Settings link reopens the form and saves changes.
- The toolbar icon opens the panel.
- Six cards arrive one by one.
- The spinner clears.
- An unreachable server shows an error instead of spinning.
