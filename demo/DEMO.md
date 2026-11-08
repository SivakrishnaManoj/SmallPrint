# Demo: pages, backup video script, pre-pitch checklist

## Demo pages

Checked with the harness on 2026-11-08 (all reached a correct state; first-visit times shown). Open them in this order, after the pre-warm.

| # | Page | What it shows | Found (first visit) |
|---|---|---|---|
| 1 | https://www.audible.co.uk/ep/whats-audible | Cost over time: £0.99/mo for 3 months, then £5.99/mo; lock-in with quotes | cost, lock-in, small print (16 s) |
| 2 | https://www.amazon.co.uk/dp/B09X7FXHVJ | Amazon product (DeLonghi grinder): returns window "within 30 days of receipt"; cost and lock-in "don't apply" (PR #78) | small print (needs #78 merged; before it, the cost card shows the price as a wrong monthly fee) |
| 3 | https://www.vodafone.co.uk/mobile/best-sim-only-deals | Who's behind it: Vodafone → Companies House 01833679, modern slavery statement, ASA rulings | company, cost, lock-in, small print (27 s; pre-warm it) |
| 4 | https://www.bbc.co.uk/news/technology | Badge greys out; one card: "No purchase detected on this page" | n/a (0.1 s) |

Backups: Spotify Premium https://www.spotify.com/gb/premium/ (cost, lock-in in 8 s); Amazon Philips Hue kit https://www.amazon.co.uk/dp/B09F72J3SG.

Check on screen before recording: Amazon's "Seller" row is quoted from "Credit broker: Amazon EU S.A.R.L.", which doesn't show who sells the item. Don't point at it. Leave Currys out of the demo (it shows a finance offer as a monthly fee).

Not for the demo: Tesco Clubcard Plus is detected, but the page calls its brand "Clubcard Plus", so the company card correctly shows no match (no fuzzy matching). Tesco grocery product pages answer HTTP 403 to automated browsers.

## Backup video script (about 2 minutes, record at H19)

Record the browser window only, at 1080p, with the side panel open. Use a fresh Chrome profile so the first-run form shows.

1. **0:00 – Problem (10 s).** "The headline price is rarely what you pay. Small Print shows the real cost, the lock-in and the public record of the company, from evidence on the page."
2. **0:10 – Install and first run (15 s).** Show the extension pinned. Open page 1, click the icon. The first-run form asks only for horizon and values. Press **Skip**.
3. **0:25 – Lifetime cost (30 s).** Page 1. Cards stream in. Point at the 12-month total, then switch the horizon to 24 months. Open one quote and its source link: "Every number has a verbatim quote, and the code checks the quote is in the source before it shows it."
4. **0:55 – Lock-in and small print (25 s).** Same page: the lock-in terms it found (auto-renewal, how to cancel, notice), each with its quote. Rows it didn't find are not shown; never fill them in by voice.
5. **1:20 – Product (15 s).** Page 2. The returns window with its quote. Cost and lock-in say they don't apply to a one-off product: "It doesn't invent a monthly fee for a coffee grinder."
6. **1:35 – Who's behind it (20 s).** Page 3. Vodafone → Companies House 01833679 → records with dates and source links. Say "recorded" and "published", never a verdict.
7. **1:55 – Not a purchase (5 s).** Page 4. The badge greys out and one card says no purchase was detected.
8. **2:00 – Close.** "Evidence, not verdicts."

Words to avoid on camera: unethical, scam, broke the law, bad, good. Say "recorded", "listed", "published", "donated £X to Y on <date>".

## Pre-pitch checklist

- [ ] All PRs for the demo merged; Railway shows the final deploy as **Active**.
- [ ] `curl -s https://smallprint-production.up.railway.app/health` returns `{"ok": true}`.
- [ ] Railway variables (Johann sets them): `SMALLPRINT_PREWARM_KEY` set; `SMALLPRINT_DAILY_LIMIT_USD` raised for the demo (for example 2).
- [ ] Pre-warm **after** the final deploy (the cache is in memory; a redeploy empties it):
      `SMALLPRINT_PREWARM_KEY=… .venv/bin/python scripts/prewarm.py --server https://smallprint-production.up.railway.app --out demo/prewarm_results.csv`
- [ ] Open each demo page once in the demo profile after the pre-warm; every card resolves, no spinner.
- [ ] Build the zip: `cd extension && npm ci && npm run build && (cd dist && zip -r ../../demo/smallprint.zip .)`; add `demo/INSTALL.txt` to the zip.
- [ ] Someone outside the team installs from the zip and sees a working panel (issue #24 done-when).
- [ ] Backup video recorded and saved locally and in the team drive.
- [ ] Demo laptop: Wi-Fi checked, notifications off, browser zoom 110%, other tabs closed.
