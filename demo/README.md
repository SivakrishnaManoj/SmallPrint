# demo/

## The 40-URL test (definition of done)

One command loads the built extension into Chromium, visits each URL in `urls40.txt` on the real internet and opens the side panel for it. It records the final panel state, the time at which each card arrived and every value shown. Then it prints the pass-bar report.

```sh
cd extension && npm ci && npm run test40          # builds the extension, then runs against the Railway backend
npm run test40 -- --server http://localhost:8000  # another backend
npm run test40 -- --only amazon --limit 3         # a quick partial run
```

A full run takes about 20 to 30 minutes. A browser window opens if a display is available (WSLg, macOS, Linux desktop). Use `--headless` to hide it. Some sites show bot checks more often to headless browsers. Other options: `--urls FILE`, `--no-second-visit`, `--review FILE`, `--out DIR`, `-h`.

Exit code: `0` every bar passes, `1` a bar fails, `2` nothing fails but something is still pending (normally values not reviewed yet).

### What each bar checks

| Bar | Rule |
|---|---|
| Correct state | Purchase pages: a purchase is detected and all six cards arrive in `found`, `estimated`, `not_found` or `n_a`. There's no spinner, error banner or failed card. `limit_reached` fails, because the spend cap makes the run invalid. Non-purchase pages: exactly one card, "No purchase detected…". A page that doesn't load, returns HTTP 4xx/5xx or shows a bot check is **untested**, and it counts against this bar. Replace the URL or run headed. |
| Zero wrong values | People decide what is wrong. Every value the panel shows goes to `review40.csv`. The harness fetches each quote's source again and sets `check`. A value that needs a quote and link but has none counts as wrong without review. |
| Found cards | At least 60% of URLs show one or more cards in `found`. The Purchase card isn't counted, because it is found on every detected purchase. |
| Timings | Measured from the moment the panel opens. Item, price-drift and no-purchase cards: ≤ 2 s. Company: ≤ 5 s. Cost, lock-in and small print: ≤ 20 s on the first visit (new extraction) and ≤ 5 s on a second visit to the same page (cached T&Cs). |

### Reviewing values

Open `demo/review40.csv` in a spreadsheet. Rows from the latest run come first, and the suspect rows are at the top. Put `ok` or `wrong` in the `verdict` column and add a `note` if useful. Compare the value with its `quote` and `source`, and with the panel screenshot in the run folder. The `check` column:

- `not_in_source`: the quote wasn't found when the harness fetched the source again. Look at these first.
- `verified`: the quote is in the source. The value may still be read wrongly from it.
- `unchecked: …`: the source couldn't be fetched again (PDF, HTTP 403, …).
- `no_quote_needed`: taken from the page itself (name, brand, total).
- `no_evidence` / `no_source`: shown without a quote or link. This counts as wrong.

Verdicts carry over: the next run reuses the verdict for any value that is the same as before (same URL, card, label, value and quote). The run before the H18 freeze then needs only the new values reviewed. Commit the sheet so the whole team reviews the same file.

Each run also writes `demo/results/<time>/` (gitignored), which holds `report.txt`, `results.json` and one panel screenshot per URL.

### The URL list

`urls40.txt` lines are `category,url,notes`, with categories `amazon`, `subscription`, `jsonld` and `no_purchase`. The definition of done asks for a list picked by someone who didn't build the adapters: about 15, 10, 10 and 5.
