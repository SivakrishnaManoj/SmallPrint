# Pre-demo reliability review

Branch `review/pre-demo` off `main` at `ae8566a` (merge of #85), 8 November 2026. Scope: find bugs
that could show a wrong value, hang the panel or leak user data, prove each one, fix the ones worth
fixing, tidy the repo. No features added, no refill gate switched on, contracts unchanged.

## 1. Baseline

Checks run from a clean install (`.venv` with `requirements.txt`, `npm ci` in `extension/` and `panel/`).

| Check | Before this branch | After this branch |
|---|---|---|
| `pytest` (repo root, `testpaths = backend`) | 351 passed, 1 skipped | 356 passed, 1 skipped |
| `pytest data/` (not in `testpaths`) | 17 passed | 17 passed |
| `panel/`: `npm test` | 44 passed | 47 passed |
| `panel/`: `npm run build` (tsc + vite) | ok | ok |
| `extension/`: `npm test` | 96 passed | 97 passed |
| `extension/`: `npm run build` (tsc + two vite builds) | ok | ok |

Nothing failed at baseline. The new tests (9) each failed before their fix and pass after it.

## 2. Story trace

Status: **done**, **partial**, **missing**, **diverges**. "Where" names the code that delivers it.

| # | Story | Status | Where / note |
|---|---|---|---|
| 1 | First-run form opens on install | done | `extension/src/background.ts` opens `options.html` on `INSTALL`; e2e |
| 2 | Choose 12 or 24 months | done | `panel/src/components/FirstRunForm.tsx` |
| 3 | Choose record kinds | done | `FirstRunForm.tsx`; kinds donation, gender_pay_gap, modern_slavery, asa_ruling |
| 4 | Skip sets defaults | done | `FirstRunForm.handleSkip` → `DEFAULT_SETTINGS` (12 months, every kind) |
| 5 | Change settings from the panel | done | `App.tsx` Settings button; options tab |
| 6 | Settings stay in the browser | done | `sse.ts buildBody` allowlist; e2e checks the trace |
| 7 | Judge installs, Skip, working panel in a minute | done | `demo/INSTALL.txt`, zip recipe in `demo/DEMO.md`; outsider test (#24) still open |
| 8 | Amazon product page lights the badge | done | `detect/amazon.ts`; colour icon via `background.ts setBadge` |
| 9 | JSON-LD retailers | done | `detect/jsonld.ts` (Product/ProductGroup, AggregateOffer, @graph) |
| 10 | Subscription/contract wording | done | `detect/wording.ts` (needs a recurring price or two cues + a price) |
| 11 | Checkout page lights the badge | done | `detect/checkout.ts` → "£" badge |
| 12 | Non-purchase: grey badge, one card | done | `App.tsx noPurchasePage`; `ItemCard` n_a text matches the story |
| 13 | SPA re-detection | done | `content.ts` URL poll + MutationObserver; `reportGate.ts` holds a transient "none" |
| 14 | Trial price → full price with the month | done | `extractor.build_cards` Trial + Monthly fee windows; **now needs both prices** (F5) |
| 15 | Annual / mid-contract rise as a step in the total | partial | Only a fixed £ rise (`annual_rise_gbp`, month 13). CPI/percentage rises go to small print as text (`price_rise_terms`), not into the total |
| 16 | Setup and exit fees itemised | done | Setup fee one_off; exit fee in Lock-in and the "if you leave" line |
| 17 | One total over the horizon | done | `panel/src/cost/lifetimeCost.ts` |
| 18 | Quote and link per cost stream | done | `CostCard` filters on `hasEvidence`, shows `Evidence` |
| 19 | Unstated cost → not found, never a guess | done | `verify.py` + `verify_extraction`; `CostCard` counts only quoted streams |
| 20 | Horizon switch recalculates instantly | done | `CostCard` local state; tested |
| 21–23 | Minimum term, auto-renew, notice and cancel method | done | `LOCK_IN_FIELDS`, `LockInCard` |
| 24 | Returns window and warranty | done | small print `returns_window` (duration rule), `warranty` |
| 25 | Real seller on a marketplace | partial | Page seller from Amazon DOM in the Item card; extracted "Seller" has known wrong rows (`demo/DEMO.md`) |
| 26 | Verbatim sentence and link per small-print field | done | `SmallPrintCard` + `Evidence` |
| 27 | Statutory rights separate, "not legal advice" | done | `StatutoryRights.tsx`, shown after the cards |
| 28 | Fallback to web search is said and linked | **fixed here** | Backend labelled `source_step=tavily_search`; the panel never showed it (F7) |
| 29 | PDF T&Cs are read | done | `fetchTerms.ts` → `pdf_b64` → PyMuPDF |
| 30 | Parent company | done | `smallprint/company` Wikidata P749/P127/P176 |
| 31 | How it was matched | done | `match_via` shown as "Matched by" |
| 32 | No lookalikes | done | exact label/legal-name matches only; "No public records matched" |
| 33 | Gender pay gap with year and link | done | `data/load_records.py` → `records.sqlite` |
| 34 | Donations as "donated £X to Y on date" | done | `load_records.py` (PR #75) |
| 35 | Modern slavery statement with year and link | done | records index; ADR-0001 |
| 36 | Ticked kinds first, rest one tap away | done | `CompanyCard` top/rest split |
| 37 | No score, no verdict words | done | `test_contracts.test_no_verdict_words`; `asa._VERDICT_WORDS` |
| 38 | Cards stream one by one | done | `pipeline.stream_real` as_completed; live: item 0.2 s, company 1.2 s, T&C 3–4 s |
| 39 | Page ≈2 s, company/cached ≈5 s, new extraction ≈20 s | partial | Page and company inside target live. T&C budget is 25 s; Vodafone first visit measured 27 s → not_found (`demo/DEMO.md`). Company had no cap at all (F3) |
| 40 | Four honest states on every card | done | plus the contract's fifth, `limit_reached`, now rendered instead of dropped (F6) |
| 41 | Estimates as a range with a source | done | usage streams; refill (gated) uses `{low,mid,high}` |
| 42 | Never clicks, fills or buys | done | content script read-only; fetcher is a plain GET with no retries |
| 43–46 | Refill cost (gated) | built, off | `SMALLPRINT_REFILL` unset on Railway and in `.env.example`; `refill_enabled()` false → no refill path runs |
| 47 | Mock stream from hour 1 | done | `main.py` mock mode (fixtures) |
| 48 | Records index keyed on CH number | done | `data/records.sqlite` committed (#75) |
| 49 | 40-URL harness with pass bar | done | `demo/run40.mjs`, `demo/review40.csv` |
| 50 | Per-domain cache, ~50 sites pre-warmed | done, **changed** | `tc_cache.py`; the site cache is now filled only by the pre-warm run or server-found documents (F1) |
| 51 | Per-install spend limit and token cap | done | `spend.py` (8k in / 4k out per call, $0.20/day); a fresh UUID is a fresh budget (by design, see R4) |
| 52 | Zip with a three-line README | done | `demo/INSTALL.txt`; zip is gitignored, built per `demo/DEMO.md` |

Cut list: price drift (V3) is in the browser only and never sent (checked `buildBody`); "Wrong match?" (V4) is in the panel and posts to `/flag/company-match`; ASA rulings (V5) are live in the company card; the browser-use refill agent (V6) is code only, behind the refill gate. None of these were touched.

## 3. Findings

Rated by demo impact. P0: wrong value, hang, or an invariant breach. P1: visible defect or spec divergence on the demo path. P2: everything else.

| # | P | Finding | How to reproduce | Status |
|---|---|---|---|---|
| F1 | P0 | **Cache poisoning through the per-site T&C cache.** `pipeline.terms_source` wrote `cache.put_site(site, found_terms)` from text the client sent, keyed on the page host. Any later install visiting the same host without T&C documents (no T&C links, or every fetch failed) was served those fields as `found`. The verifier passed them because the quotes were in the attacker's text, never the real page. | `test_site_cache_is_never_filled_from_text_a_client_sent`: install A posts gym T&C text with `item.url` on vodafone.co.uk; install B posts a vodafone.co.uk page with `terms: []` and gets A's cost, lock-in and small print as found. | fixed (`258828e`): site cache filled only when `install_id == "prewarm"` or every document has a server `source` (search). Per-document cache unchanged. |
| F2 | P1 | **Spoofable pre-warm id.** `X-Install-Id: prewarm` without the key still became the install id, so once the real pre-warm had run, a spoofer shared its $5 daily limit; with F1's fix it would also have marked text as trusted. | `test_the_prewarm_install_id_without_the_key_is_refused` | fixed (`258828e`): 403 unless `is_prewarm` |
| F3 | P1 | **No timeout on the company lookup.** Wikidata (3.5 s budget) + GLEIF by LEI (4 s) + GLEIF names (up to 3 names × 2 spellings × 4 s) + Companies House (3 × 4 s) + ASA (6 s) can pass 40 s. The panel aborts at 60 s with an error banner over the cards it has, and `done` waited on the slowest registry. | `test_a_hanging_company_lookup_still_ends_the_stream_in_time` (lookup sleeps 10 s, budget patched to 0.5 s; `done` must arrive within 5 s) | fixed (`5235cc5`): `COMPANY_TIMEOUT_S = 20`, card `not_found` on timeout |
| F4 | P1 | **Digit check accepted a truncated price.** `_number_in_quote(24, "costs £24.99 a month")` was True (only a following digit was refused), so a model that returned 24 for £24.99 verified, and the panel would show £24.00 a month with a correct quote. | `test_number_in_quote` new asserts | fixed (`46f5c1d`): also refuse a following `.<digit>` |
| F5 | P1 | **Trial without its full price gave a £0 total as found.** `build_cards` emitted a lone Trial stream when `monthly_price` wasn't verified; the panel totalled it over the horizon ("Total over 12 months: £0.00", Found). | `test_a_trial_without_its_full_price_gives_no_cost_total` | fixed (`a0cc92d`): the Trial stream needs `monthly_price`; otherwise cost is not_found |
| F6 | P1 | **`limit_reached` cards were dropped by the extension.** `sse.ts CARD_STATES` knew four states; the backend sends `limit_reached` for cost, lock-in and small print after the $0.20/day limit (about 55 extraction calls, or one long T&C page, see F11). The cards vanished, placeholders showed "Checking… 3 of 6" until done, no explanation. `panel/src/types.ts CardState` lacked the state too. | `extension/test/sse.test.ts` "keeps limit_reached cards"; `cards.test.tsx` "limit_reached" | fixed (`b54a621`): accepted, typed, rendered with a "Limit reached" badge and a reset note |
| F7 | P1 | **Story 28 not delivered in the panel.** Values from the search fallback carry `source_step: "tavily_search"` but no card said so. | `cards.test.tsx` "search fallback (story 28)" | fixed (`ff1ad3a`): `Evidence` prints "found by web search, not from the page's own T&C link" |
| F8 | P2 | **Mock mode served the SodaStream fixture for any Amazon URL** (V1 #29 item, never done). Live is not in mock mode today (see §5), but a missing `OPENAI_API_KEY` after a variable edit would switch it on silently and show invented figures as found. | `test_mock_mode_never_shows_the_sodastream_fixture_as_found_for_another_product` | fixed (`6734b71`): keyword must be the product, not the host |
| F9 | P2 | **Suspected: price drift never records a first-seen price.** `content.ts` calls `chrome.storage.session.get/set` from the content script. Chrome exposes `storage.session` to content scripts only after `setAccessLevel({accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS"})`, which nothing calls; the rejection is swallowed by `.catch(() => {})`. Cut-list feature (V3); the card shows n_a either way. | Needs Chrome: open a product page, then `chrome.storage.session.get()` from the service worker and look for `pricedrift_firstseen_<host>`. | suspected, open |
| F10 | P2 | **Suspected: T&C timeout discards page-text values.** `terms_source` runs page-snippet extraction then T&C extraction inside one 25 s `wait_for`; on timeout `result` is `None`, so values already verified from the page snippets are lost and all three cards say not_found. | Make the T&C extraction slow in `FakeLLM(delay=…)` with page snippets present; page values disappear. Not written as a test because the behaviour is a degradation, not a wrong value. | suspected, open |
| F11 | P2 | **One long T&C page can use most of a day's budget.** 500,000 characters ≈ 21 chunks × $0.0036 reserved = $0.075 per document; three documents ≈ $0.20, the whole daily limit for that install. The next page shows `limit_reached` (visible since F6). | Arithmetic from `spend.py` and `text.py`; Audible's terms were 46 k characters (2 chunks) on 2026-11-08. | open; mitigation R4 |
| F12 | P2 | `/flag/company-match` (V4) is posted from `App.tsx` without `credentials: "omit"` / `referrerPolicy: "no-referrer"`, unlike `/analyse`. Nothing user-specific beyond the install id and page URL is in the body. | read `extension/src/sidepanel/App.tsx onFlagCompany` | open (extension/, for Siv) |
| F13 | P2 | Schema / model / type drift: TS `CardState` lacked `limit_reached` and `LockInEvidence` lacked `source_step` (both fixed in F6/F7). Pydantic `LinkIn.kind` and `purchase_type_signals` are plain `str` where the schema has enums (more permissive, harmless). `AnalyseRequest` allows extra fields the schema forbids (harmless). | `contracts/*.schema.json` vs `backend/server/models.py` vs `panel/src/types.ts` | mostly fixed; remainder accepted |
| F14 | P2 | Brands with no parent and no UK number (Netflix, PureGym) are "No public records matched" although Wikidata identifies them: `_wikidata_lookup` returns nothing when neither a CH number nor a parent is found, and GLEIF/Companies House need the legal name ("Netflix, Inc."). By design (no fuzzy matching); the demo pages avoid it (Vodafone matches with 9 records). | `scripts/company_coverage.py SodaStream "Pepsi Max" Vodafone` → 0, owner only, full match | accepted; see R7 |
| F15 | P2 | A fresh install UUID is a fresh $0.20 budget and a fresh rate-limit bucket. A judge can't reach it by accident; someone scripting requests can. There is no per-IP limit. | `spend.py`, `rate_limit.py` | accepted for the demo; see R4 |
| F16 | P2 | Deploy drift: `backend/Procfile` and `backend/nixpacks.toml` were stale (Railway uses Railpack from `railway.json`/`railpack.json`). `backend/requirements.txt` duplicates the root file; kept because `test_llm_provider.py` reads it. | `git log -- backend/Procfile` | Procfile and nixpacks removed (`55d4a43`) |

Leads checked and rejected:

- **SSE buffering behind Railway.** Response carries `x-accel-buffering: no`; events arrived at 0.2 s, 1.2 s and 3.x s in the live smoke test, so nothing is buffered.
- **CORS from `chrome-extension://`.** Preflight against live returns `access-control-allow-origin: chrome-extension://…` and the requested headers. `host_permissions` include `https://*.up.railway.app/*`.
- **Mock mode on live.** A probe with no page text and no T&C (no LLM call) returned `cost n_a`, `small_print not_found`, a live company lookup and no `MOCK:` markers: the real pipeline is running.
- **Event loop blocked by HTML/PDF parsing.** trafilatura on a 500,000-character page: 0.17 s. Not a risk for the 20 s idle timer.
- **Pre-warm key timing.** `secrets.compare_digest` after a presence check: constant time.
- **8k input cap.** Enforced in `SpendTracker.guard` on every call, and chunking stays under it (`test_long_document_is_chunked_under_the_input_cap`).
- **Spend / rate-limit state under concurrency.** Single asyncio loop; the reservation has no await between check and write; the rate limiter holds a lock. In memory by design (one instance).
- **Timeouts vs the extension's limits.** Headers arrive in 0.2 s (< 10 s connect); sse-starlette pings every 15 s (< 20 s idle); T&C 25 s + company 20 s now both sit inside 60 s total. The T&C fetch phase (≤ 10 s per document, in parallel) runs before the stream and is not counted in the 60 s.
- **Lifetime cost edge cases.** Trial window inclusive of `to_month`; step change at month 13 applies to months 13–24 only; `to_month` is clamped to the horizon; a window ending before it starts or a month < 1 throws and the card shows not found; rounding happens once at the end (`toPence`). 18 existing tests plus a manual read found no off-by-one.
- **Privacy of the body.** `buildBody` allowlist; checkout pages send no page text; snippets drop emails, postcodes, phones, card numbers and "Delivering to" lines; `credentials: "omit"`, `no-referrer`. Price drift stays in `chrome.storage.session`.
- **T&C fetcher limits.** 15,000,000 PDF bytes → exactly 20,000,000 base64 characters, the contract's and the Pydantic model's `maxLength`. Consistent. A 20 MB JSON body through Railway's proxy is untested but off the demo path.

## 4. Housekeeping (separate commits)

- Removed `backend/Procfile`, `backend/nixpacks.toml`, `backend/smallprint/terms/__init__.py` (stub, unused), `.gitkeep` in five non-empty directories, `panel/src/assets/{hero.png,preact.svg,vite.svg}` (unreferenced). `main.py`'s mock-mode docstring no longer points at the stub.
- `.env.example` now lists `SMALLPRINT_COMPANY_LOOKUP`, `FLAGS_DB` and `VITE_SERVER_URL`, and says a missing `OPENAI_API_KEY` means mock mode.
- `extension/README.md`: the "canned request" and "six mock cards" paragraphs described the H1 skeleton.
- Not changed, worth knowing: `backend/requirements.txt` duplicates the root file; `scripts/run_coverage.py` is the pre-harness smoke test V1 said to keep; `main-base/` in this worktree is an untracked local worktree from an earlier session, not part of the repo; `data/test_load_records.py` is outside `testpaths` and only runs with `pytest data/`.

## 5. Live smoke test (Railway, 8 Nov 2026, ~08:20 UTC)

`GET /health` → `{"ok": true}` in 0.2 s. Then `POST /analyse` with each `fixtures/requests/*.json` (no `terms`, four page snippets each: one small LLM call per request). Every card event validated against `stream-event.schema.json`; found cards checked for quote + URL.

| Fixture | item / price_drift | company | cost · lock_in · small_print | done |
|---|---|---|---|---|
| req_gym (PureGym) | 0.24 s | 1.17 s not_found | 3.60 s found (£24.99) · found (cancel_method) · not_found | 3.60 s |
| req_netflix | 0.19 s | 1.25 s not_found | 3.18 s found (£4.99) · found (auto_renews, cancel_method) · not_found | 3.18 s |
| req_sodastream (product) | 0.21 s | 1.32 s not_found | 3.01 s n_a · n_a · found (Returns window, Seller) | 3.01 s |

No contract problems. Live company matching (free, direct): SodaStream not identified; Pepsi Max → PepsiCo, no UK number; Vodafone → 01833679 with 9 records, 1.6 s. The 40-URL harness was not run (it needs your go-ahead).

## 6. Demo path risk register

Path: install from the zip → Skip → Amazon product page → cards stream → switch horizon → open the company card → open a non-purchase page.

| # | Risk | Mitigation |
|---|---|---|
| R1 | Venue wifi drops: the panel shows "Couldn't reach the SmallPrint server" with Retry (no hang). | Phone hotspot ready; backup video (`demo/DEMO.md` H19). |
| R2 | Cold cache: Vodafone's first visit took 27 s on 2026-11-08, over the 25 s T&C budget, so its T&C cards say not found. | Run `scripts/prewarm.py` after the final deploy (needs `SMALLPRINT_PREWARM_KEY` on Railway: after F1 only the pre-warm run fills the site cache), then open each demo page twice within 30 minutes. The per-document cache still warms on a visit when the fetched text is identical. |
| R3 | Railway restarts or redeploys: cache and spend counters are in memory and reset. | Re-run the pre-warm after any deploy; freeze deploys before the pitch; check Railway shows the last deploy Active. |
| R4 | Judges playing freely hit the $0.20 daily limit; cards now say "Limit reached" instead of disappearing. One long T&C page can take most of it (F11). | Set `SMALLPRINT_DAILY_LIMIT_USD=2` for the day (`demo/DEMO.md`). A fresh Chrome profile is a fresh UUID and budget. |
| R5 | Mock mode by accident (key removed or renamed in Railway variables) shows fixture data. | Before the pitch, POST the SodaStream probe with no page text: the real pipeline answers `cost n_a`; mock mode answers the SodaStream fixture with `MOCK:` text. F8 makes other Amazon pages say not found rather than show SodaStream figures. |
| R6 | Amazon reassigns the demo ASIN (B09X7FXHVJ is now a SanDisk card, not the grinder). | Open the page the morning of the demo; keep the Philips Hue backup ASIN. Say "memory card", not "grinder". |
| R7 | A judge opens a big brand with no UK number and no parent (Netflix) and sees "No public records matched". | Explain: exact matching only, no lookalikes (story 32). Keep Vodafone as the company example. |
| R8 | The company lookup is slow on an unfamiliar brand. | Capped at 20 s now; the card resolves not_found and the stream still ends. |
| R9 | The non-purchase step: a page where the content script can't run (chrome://, Web Store, PDF viewer) also shows "No purchase detected", with a grey icon. | Use the BBC page from `demo/demo-urls.txt` (0.1 s). |
| R10 | Install from zip: Chrome shows the "disable developer mode extensions" prompt on restart. | Dismiss; it doesn't unload the extension. Issue #24's outsider install is still to be done. |
| R11 | Spinner during the T&C fetch phase ("Reading the terms…") lasts up to 10 s before the stream starts, on top of the 60 s stream cap. | Demo pages measured ≤ 27 s end to end; say "each value is checked against its source" and wait. |

## 7. Questions only the team can answer

1. Was the refill gate (#21, 7 of 10) measured and what was the result? The ticket is closed; `SMALLPRINT_REFILL` must stay unset unless it passed.
2. Is `SMALLPRINT_PREWARM_KEY` set on Railway, and who runs `scripts/prewarm.py` after the final deploy? With F1 fixed, nothing else fills the site cache.
3. Should "Wrong match?" (V4, cut order 2, "only after the 40-URL test passes") be in the demo build? If yes, Siv may want F12's two fetch options added.
4. PR #87 joins three new record kinds on exact name with `ch_number = NULL`. Is a name-only join acceptable under story 32 for the demo, and should `test_default_record_kinds_match_data_kinds` learn the new kinds?
5. PR #76 adds two 359,221-line CSVs to `data/`. Are they meant for the repo (Railway builds the whole root)?
6. What daily limit do you want on the day (R4)?
7. Netflix and PureGym show "No public records matched" (F14). Acceptable messaging, or should the card say "identified, no UK filing" when Wikidata knows the brand but no parent or number exists?
8. Extension changes in this PR (`src/sse.ts`, `test/sse.test.ts`) are listed separately in the PR for Siv.
