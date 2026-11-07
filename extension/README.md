# extension/

Owned by Siv. MV3 Chrome extension: purchase detection, side panel host, DOM scraping, price-drift tracking.

Do not edit from other workstreams.

## Current state (H1–H4)

**First run and privacy.** Installing the extension opens a setup tab (`options.html`). It asks only for the cost horizon (12 or 24 months) and which company record kinds to flag. **Skip** saves 12 months and every kind, and the panel works straight away. Settings live in `chrome.storage.local`. The panel's **Settings** button reopens the form, and if the setup tab was closed unanswered, the panel shows the form itself.

On install the extension makes a random UUID (`crypto.randomUUID()`) and stores it as `install_id`. Every `/analyse` call sends it as the `X-Install-Id` header. That header is the only thing about the user that leaves the browser. The body is rebuilt from an allowlist of page-data fields, and the request goes with `credentials: "omit"` and `referrerPolicy: "no-referrer"`. Settings and any postcode never leave the device.

To check it yourself: open the panel, right-click → **Inspect** → **Network**, and select the `/analyse` request.

The side panel POSTs a **canned request** (`fixtures/requests/req_sodastream.json`) to the backend's `/analyse`. It reads the SSE stream and renders each card as it arrives. The card components come from `panel/src` through the `~panel` alias, so the panel workstream stays the single source of the UI. Purchase detection and scraping come later.

```
src/background.ts        service worker: toolbar icon opens the side panel; on install makes the UUID and opens setup
src/options/main.tsx     first-run / settings tab (FirstRunForm without the postcode field)
src/settings.ts          settings + setup_done flag in chrome.storage.local
src/install.ts           anonymous install UUID
src/sidepanel/App.tsx    panel UI: setup gate, Settings link, auto-runs, Re-run / Retry, server URL
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

Then open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick `extension/dist`. Click the SmallPrint toolbar icon (pin it from the puzzle-piece menu). The side panel opens, and the six mock cards appear one at a time.

- To use another backend (ngrok, Railway), click **Server** in the panel. The URL is saved in `chrome.storage.local`. You can also build with `VITE_SERVER_URL=https://… npm run build`. Hosts outside `localhost`, `*.ngrok-free.app` and `*.up.railway.app` must be added to `host_permissions` in the manifest.
- `npm run watch` rebuilds on change. Then click reload on the extension card and reopen the panel.

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
npm test                                # SSE parser + client unit tests (vitest)
npm run build && npm run e2e            # loads dist/ in Chromium against a running backend
```

`npm run e2e` needs Playwright and Chromium available (`NODE_PATH=$(npm root -g)` if Playwright is installed globally). It checks these things:

- Installing opens the setup form, which asks only for horizon and record kinds.
- Skip stores the defaults, and the panel then works.
- The network trace shows `X-Install-Id` as the only non-standard header, with no cookie or referer, and a body holding page data only.
- The Settings link reopens the form and saves changes.
- The toolbar icon opens the panel.
- Six cards arrive one by one.
- The spinner clears.
- An unreachable server shows an error instead of spinning.
