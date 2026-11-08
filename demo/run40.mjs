#!/usr/bin/env node
// The 40-URL test (J6, #22). Loads the built extension (extension/dist) into Chromium, visits each URL
// in demo/urls40.txt on the real internet, opens the side panel for it and records the final panel state,
// when each card arrived and every value shown. Prints the pass-bar report (rules in run40/score.mjs).
//
//   cd extension && npm run test40                 # builds, then runs against the Railway backend
//   npm run test40 -- --server http://localhost:8000 --only amazon --limit 3
//
// Options:
//   --server URL       backend (default: $SERVER_URL or the extension's Railway default)
//   --urls FILE        URL list (default demo/urls40.txt)
//   --only CATS        comma-separated categories: amazon, subscription, jsonld, no_purchase
//   --limit N          first N URLs only (after --only)
//   --headed / --headless   default: headed if a display is available, so the browser is real Chrome-like
//   --no-second-visit  skip the second visit that times cached T&Cs (the timing bar then stays PENDING)
//   --review FILE      review sheet (default demo/review40.csv)
//   --out DIR          run folders go here (default demo/results)
//
// Exit code: 0 every bar passes, 1 a bar fails, 2 nothing fails but something is pending (value review).
//
// The harness only reads: it never clicks on the shop pages, never fills in forms, and uses Chromium's
// own user agent (no bot evasion). A page that answers with an HTTP error or a bot check is reported as untested.
import { createRequire } from "node:module";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import { parseArgs } from "node:util";
import * as S from "./run40/score.mjs";

const root = resolve(import.meta.dirname, "..");
// Playwright is an extension devDependency.
const { chromium } = createRequire(join(root, "extension/package.json"))("playwright");

const { values: opt } = parseArgs({
  options: {
    server: { type: "string", default: process.env.SERVER_URL ?? "https://smallprint-production.up.railway.app" },
    urls: { type: "string", default: join(root, "demo/urls40.txt") },
    only: { type: "string" },
    limit: { type: "string" },
    headed: { type: "boolean", default: false },
    headless: { type: "boolean", default: false },
    "no-second-visit": { type: "boolean", default: false },
    review: { type: "string", default: join(root, "demo/review40.csv") },
    out: { type: "string", default: join(root, "demo/results") },
    help: { type: "boolean", short: "h" },
  },
});
if (opt.help) {
  console.log(readFileSync(import.meta.filename, "utf8").split("\n").filter((l) => l.startsWith("//")).slice(0, 22).map((l) => l.slice(3)).join("\n"));
  process.exit(0);
}

const server = opt.server.replace(/\/+$/, "");
const dist = join(root, "extension/dist");
if (!existsSync(join(dist, "manifest.json"))) {
  console.error("extension/dist is missing: run `npm run build` in extension/ first (npm run test40 does both).");
  process.exit(1);
}
let urls = S.parseUrls(readFileSync(opt.urls, "utf8"));
if (opt.only) {
  const only = opt.only.split(",").map((c) => c.trim());
  urls = urls.filter((u) => only.includes(u.category));
}
if (opt.limit) urls = urls.slice(0, Number(opt.limit));
if (!urls.length) { console.error("No URLs to visit."); process.exit(1); }

// Check the backend answers before spending 20 minutes on a run that can only fail.
try {
  const r = await fetch(`${server}/health`, { signal: AbortSignal.timeout(15000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
} catch (e) {
  console.error(`Backend ${server} is not answering /health (${e.message}).`);
  process.exit(1);
}

const stamp = new Date().toISOString().replace(/\.\d+Z$/, "").replace(/:/g, "");
const runDir = join(opt.out, stamp);
mkdirSync(runDir, { recursive: true });
const headless = opt.headless ? true : opt.headed ? false : !(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);

const PANEL_CAP_MS = 90_000; // the panel itself gives up after 60 s (extension/src/config.ts TIMEOUTS) plus T&C fetches
const SETTLE_MS = 2_000; // the panel must hold a final state this long (a detection change can start a new run)
const BOT_CHECK = /captcha|robot check|not a robot|are you a (human|robot)|verify (that )?you are (a )?human|unusual traffic|access denied|attention required|pardon our interruption|request unsuccessful|press (&|and) hold|click the button below to continue shopping/i;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const firstLine = (s) => String(s).split("\n")[0].slice(0, 160);

const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "sp-40url-")), {
  headless,
  channel: "chromium", // new headless mode; the old one cannot load extensions
  args: [`--disable-extensions-except=${dist}`, `--load-extension=${dist}`],
  viewport: { width: 1280, height: 900 },
  locale: "en-GB",
  timezoneId: "Europe/London",
});

/** Runs in the panel before its own scripts: records when each card appears and what state it ends in. */
function panelWatcher() {
  const w = (window.__sp = { cards: {}, noPurchaseMs: null, analyse: [] });
  const fetch0 = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input?.url ?? String(input);
    if (/\/analyse(\?|$)/.test(url)) w.analyse.push(Math.round(performance.now()));
    return fetch0.apply(this, arguments);
  };
  const scan = () => {
    const now = Math.round(performance.now());
    const present = new Set();
    for (const el of document.querySelectorAll(".card")) {
      const title = (el.querySelector(".card__title")?.textContent ?? el.textContent).replace(/\s+/g, " ").trim().slice(0, 80);
      const cls = [...el.classList].find((c) => c.startsWith("card--"));
      const state = cls ? cls.slice(6) : "unknown";
      present.add(title);
      const c = w.cards[title];
      // A card that went away and came back belongs to a new analysis run: time it from its return.
      if (!c || c.gone) w.cards[title] = { title, ms: now, state };
      else c.state = state;
    }
    for (const [t, c] of Object.entries(w.cards)) c.gone = !present.has(t);
    if (w.noPurchaseMs == null && document.querySelector('[data-testid="no-purchase"]')) w.noPurchaseMs = now;
  };
  new MutationObserver(scan).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
}

/** The panel's current state, from the DOM and the watcher. */
const panelSnapshot = (panel) => panel.evaluate(() => {
  const w = window.__sp;
  const text = (sel) => document.querySelector(sel)?.textContent.replace(/\s+/g, " ").trim() || null;
  return {
    cards: Object.values(w.cards).filter((c) => !c.gone).map(({ title, ms, state }) => ({ title, ms, state })),
    noPurchase: w.noPurchaseMs != null && document.querySelector('[data-testid="no-purchase"]') ? { ms: w.noPurchaseMs } : null,
    error: document.querySelector('[role="alert"]')?.innerText.split("\n")[0].trim() || null,
    spinner: !!document.querySelector('[data-testid="progress"]'),
    loading: text(".loading"),
    empty: !!document.querySelector(".empty-state"),
    analyseCalls: w.analyse.length,
  };
});

/** Every value the panel shows, with its quote and link if it has one. */
const panelValues = (panel) => panel.evaluate(() => {
  const txt = (el) => el?.textContent.replace(/\s+/g, " ").trim() ?? "";
  const out = [];
  for (const card of document.querySelectorAll(".card")) {
    const title = txt(card.querySelector(".card__title"));
    const add = (label, value, row, evidence) => {
      const q = row?.querySelector("blockquote");
      const a = row?.querySelector("a.source-link");
      out.push({ title, label, value, quote: q ? txt(q) : "", source: a ? a.href : "", evidence });
    };
    if (title === "Purchase") {
      if (card.querySelector(".item__name")) add("Name", txt(card.querySelector(".item__name")), null, "none");
      for (const m of card.querySelectorAll(".item__meta")) {
        const t = txt(m);
        if (t.includes(":")) add(t.slice(0, t.indexOf(":")), t.slice(t.indexOf(":") + 1).trim(), null, "none");
      }
    } else if (title === "Cost over time") {
      const total = card.querySelector('[data-testid="cost-total"]');
      if (total) add("Total", txt(total), null, "none");
      const leaving = card.querySelector('[data-testid="cost-if-leaving"]');
      if (leaving) add("If you leave early", txt(leaving), null, "none");
      for (const r of card.querySelectorAll('[data-testid="cost-stream"]')) add(txt(r.querySelector(".stream__label")), txt(r.querySelector(".stream__detail")), r, "quote");
    } else if (title === "Lock-in") {
      for (const r of card.querySelectorAll('[data-testid="lock-in-row"]')) add(txt(r.querySelector(".lock-in__label")), txt(r.querySelector(".lock-in__value")), r, "quote");
    } else if (title === "Small print") {
      for (const r of card.querySelectorAll('[data-testid="small-print-row"]')) add(txt(r.querySelector("strong")), txt(r.querySelector(".small-print__value")), r, "quote");
    } else if (title === "Who's behind it") {
      const brand = card.querySelector(".company__brand") ?? card.querySelector(".card__body > p > strong");
      if (brand) add("Brand", txt(brand), null, "none");
      for (const m of card.querySelectorAll(".company__meta")) add("Parent", txt(m).replace(/^Parent company:\s*/, ""), null, "none");
      if (card.querySelector('[data-testid="match-via"]')) add("Matched by", txt(card.querySelector('[data-testid="match-via"]')), null, "none");
      for (const r of card.querySelectorAll('[data-testid="record"]')) {
        add(`${txt(r.querySelector(".record-kind"))} · ${txt(r.querySelector(".record-date"))}`, txt(r.querySelector(".record-summary")), r, "source");
      }
    } else if (title === "Price drift" && !card.classList.contains("card--n_a") && !card.classList.contains("card--not_found")) {
      add("Price drift", txt(card.querySelector(".card__body")), null, "none");
    }
  }
  return out;
});

const sourceCache = new Map();
/** The text of a quote's source, fetched again with the context's own cookies and user agent. */
async function sourceText(url, tab, pageUrl) {
  const bare = (u) => u.split("#")[0].replace(/\/$/, "");
  if (bare(url) === bare(pageUrl) || bare(url) === bare(tab.url())) {
    return { text: await tab.evaluate(() => `${document.body?.innerText ?? ""}\n${document.body?.textContent ?? ""}`).catch(() => "") };
  }
  if (!sourceCache.has(url)) {
    sourceCache.set(url, (async () => {
      try {
        const r = await ctx.request.get(url, { timeout: 20000, failOnStatusCode: false });
        if (!r.ok()) return { unchecked: `HTTP ${r.status()}` };
        const type = r.headers()["content-type"] ?? "";
        if (/pdf/i.test(type) || /\.pdf($|\?)/i.test(url)) return { unchecked: "PDF" };
        const body = await r.text();
        return { text: /html|xml/i.test(type) || /^\s*</.test(body) ? S.htmlToText(body) : body };
      } catch (e) {
        return { unchecked: firstLine(e.message) };
      }
    })());
  }
  return sourceCache.get(url);
}

async function checkValues(values, tab, pageUrl) {
  const out = [];
  for (const v of values) {
    const card = S.cardName(v.title) ?? v.title;
    let check = "no_quote_needed";
    if (v.evidence === "quote") {
      if (!v.quote || !/^https:\/\//.test(v.source)) check = "no_evidence";
      else {
        const src = await sourceText(v.source, tab, pageUrl);
        check = src.unchecked ? `unchecked: ${src.unchecked}` : S.quoteIn(v.quote, src.text) ? "verified" : "not_in_source";
      }
    } else if (v.evidence === "source") check = /^https?:\/\//.test(v.source) ? "no_quote_needed" : "no_source";
    out.push({ card, label: v.label, value: v.value, quote: v.quote, source: v.source, check });
  }
  return out;
}

// An extension page that stays open for reading chrome.storage.session and the active tab. (Not the
// service worker: Chrome stops an idle MV3 worker after ~30 s and Playwright's handle to it dies.)
let ctl, extId;
const sessionDetections = () => ctl.evaluate(async () => {
  const all = await chrome.storage.session.get(null);
  return Object.fromEntries(Object.entries(all).filter(([k]) => k.startsWith("detection:")));
});

/** The tab id of the page and its settled detection, or null if the content script never reported. */
async function waitForDetection(tab, before) {
  let tabId, stored;
  const t0 = Date.now();
  for (; Date.now() - t0 < 15000 && tabId === undefined; await sleep(250)) {
    const all = await sessionDetections();
    const hit = Object.entries(all).find(([k, v]) => !(k in before) || v.url === tab.url());
    if (hit) [tabId, stored] = [Number(hit[0].split(":")[1]), hit[1]];
  }
  if (tabId === undefined) {
    // The extension has no "tabs" permission, but it can still see which tab is active.
    await tab.bringToFront();
    tabId = await ctl.evaluate(() => chrome.tabs.query({ active: true, lastFocusedWindow: true }).then(([t]) => t?.id));
    return { tabId, stored: null };
  }
  // Pages that render their product late report again: wait until the detection stops changing.
  const key = `detection:${tabId}`;
  let since = Date.now();
  for (const t1 = Date.now(); Date.now() - t1 < 12000 && Date.now() - since < SETTLE_MS; await sleep(250)) {
    const now = (await sessionDetections())[key];
    if (JSON.stringify(now) !== JSON.stringify(stored)) [stored, since] = [now, Date.now()];
  }
  return { tabId, stored };
}

/** Open the panel pinned to the tab and wait until it holds a final state. */
async function runPanel(tabId) {
  const panel = await ctx.newPage();
  await panel.setViewportSize({ width: 400, height: 1000 });
  await panel.addInitScript(panelWatcher);
  await panel.goto(`chrome-extension://${extId}/sidepanel.html?tabId=${tabId}`);
  let snap, key, since = Date.now();
  const t0 = Date.now();
  for (; Date.now() - t0 < PANEL_CAP_MS; await sleep(250)) {
    snap = await panelSnapshot(panel);
    const final = !snap.spinner && !snap.loading && (snap.noPurchase || snap.error || snap.cards.length > 0 || snap.empty);
    const k = JSON.stringify([final, snap.cards.map((c) => [c.title, c.state]), snap.error, snap.analyseCalls]);
    if (k !== key) [key, since] = [k, Date.now()];
    else if (final && Date.now() - since >= SETTLE_MS) break;
  }
  snap = await panelSnapshot(panel);
  return {
    panel,
    state: { ...snap, capMs: PANEL_CAP_MS, cards: snap.cards.map((c) => ({ ...c, card: S.cardName(c.title), state: c.title.startsWith("Couldn't show") ? "error" : c.state })) },
  };
}

async function visit(entry, { second = false } = {}) {
  const v = { ...entry, finalUrl: null, httpStatus: null, blocked: null, gotoError: null, harnessError: null, detection: null, panel: null, values: [], screenshot: null };
  let tab, panel;
  try {
    const before = await sessionDetections();
    tab = await ctx.newPage();
    try {
      const resp = await tab.goto(entry.url, { waitUntil: "domcontentloaded", timeout: 45000 });
      v.httpStatus = resp?.status() ?? null;
    } catch (e) {
      v.gotoError = firstLine(e.message);
      return v;
    }
    const { tabId, stored } = await waitForDetection(tab, before);
    v.finalUrl = tab.url();
    if (stored) v.detection = { status: stored.detection.status, detector: stored.detection.detector ?? null, checkout: !!stored.detection.checkout };
    const head = await tab.evaluate(() => `${document.title}\n${document.body?.innerText.slice(0, 3000) ?? ""}`).catch(() => "");
    const bot = BOT_CHECK.exec(head);
    if (v.httpStatus >= 400) v.blocked = `page answered HTTP ${v.httpStatus}`;
    else if (bot && v.detection?.status !== "purchase") v.blocked = `bot check ("${bot[0]}")`;
    if (v.blocked && !second) await tab.screenshot({ path: join(runDir, `${String(entry.n).padStart(2, "0")}-${entry.category}-page.png`) }).catch(() => {});
    if (v.blocked || tabId == null) return v;

    ({ panel, state: v.panel } = await runPanel(tabId));
    if (!second) {
      v.screenshot = `${String(entry.n).padStart(2, "0")}-${entry.category}.png`;
      await panel.screenshot({ path: join(runDir, v.screenshot), fullPage: true }).catch(() => {});
      v.values = await checkValues(await panelValues(panel), tab, entry.url);
    }
    return v;
  } catch (e) {
    // One page crashing (or a closed target) must not end the whole run.
    v.harnessError = firstLine(e.message);
    return v;
  } finally {
    await panel?.close().catch(() => {});
    await tab?.close().catch(() => {});
  }
}

const results = [];
let cached = null;
let browserVersion, extensionVersion;
try {
  const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker", { timeout: 15000 }));
  extId = new URL(sw.url()).host;
  browserVersion = ctx.browser()?.version() ?? null;
  extensionVersion = JSON.parse(readFileSync(join(dist, "manifest.json"), "utf8")).version;

  // First run: the install opens the setup form. Skip = the defaults (12 months, every record kind).
  let setup;
  for (const t = Date.now(); !setup && Date.now() - t < 10000; await sleep(100)) setup = ctx.pages().find((p) => p.url().includes("options.html"));
  if (!setup) throw new Error("the first-run form did not open on install");
  await setup.getByText("Skip (use defaults)").click();
  await setup.getByTestId("setup-saved").waitFor();
  await setup.evaluate((u) => chrome.storage.local.set({ smallprint_server_url: u }), server);
  ctl = setup;

  console.log(`Visiting ${urls.length} URLs against ${server} (${headless ? "headless" : "headed"}); run folder ${relative(process.cwd(), runDir)}`);
  for (const [i, entry] of urls.entries()) {
    const t = Date.now();
    const v = await visit(entry);
    results.push(v);
    const problems = S.stateProblems(v);
    const found = S.foundCards(v);
    console.log(`  ${String(i + 1).padStart(2)}/${urls.length} #${String(entry.n).padEnd(2)} ${problems.length ? "FAIL" : "ok  "} ${entry.category.padEnd(12)} ${((Date.now() - t) / 1000).toFixed(0).padStart(3)} s  ${found.length ? `found: ${found.join(",")}` : ""}${problems.length ? ` ✗ ${problems[0]}` : ""}  ${entry.url}`);
  }

  if (!opt["no-second-visit"]) {
    const again = results.filter((v) => !S.untestedReason(v) && v.detection?.status === "purchase" && v.panel);
    console.log(`Second visit to ${again.length} purchase pages, to time cached T&Cs`);
    cached = [];
    for (const first of again) cached.push(await visit(urls.find((u) => u.url === first.url), { second: true }));
  }
} finally {
  await ctx.close();
}

const existing = existsSync(opt.review) ? S.parseCsv(readFileSync(opt.review, "utf8")) : [];
const review = S.mergeReview(existing, results, stamp);
writeFileSync(opt.review, S.toCsv(review.rows));
const summary = S.summarise(results, { cachedVisits: cached, review });
const report = S.formatReport(summary, {
  stamp, server, headless, browserVersion, extensionVersion,
  reviewPath: relative(process.cwd(), opt.review), runDir: relative(process.cwd(), runDir),
});
writeFileSync(join(runDir, "results.json"), JSON.stringify({ stamp, server, headless, browserVersion, extensionVersion, urls: opt.urls, results, secondVisit: cached }, null, 2));
writeFileSync(join(runDir, "report.txt"), report + "\n");
console.log("\n" + report);
process.exit(S.exitCode(summary));
