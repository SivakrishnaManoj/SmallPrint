// Scoring for the 40-URL test (J6, #22): pure functions, no browser. demo/run40.mjs collects
// one "visit" per URL and hands them here; score.test.mjs covers the rules.
//
// Pass bar (CLAUDE.md, "Definition of done"):
//   1. 100% of URLs show a correct state (found / estimated / not found / doesn't apply), no endless spinner.
//   2. Zero wrong values. A person decides what is wrong: every displayed value goes to the review
//      sheet, and the verdicts carry over between runs.
//   3. At least 60% of URLs show one or more found cards. The Purchase card is not counted: it only
//      repeats the page, so it is "found" on every detected purchase.
//   4. Timings: page-derived cards < 2 s, company and cached T&Cs < 5 s, new T&C extraction < ~20 s.

export const CATEGORIES = ["amazon", "subscription", "jsonld", "no_purchase"];
/** About 15 / 10 / 10 / 5. */
export const EXPECTED_MIX = { amazon: 15, subscription: 10, jsonld: 10, no_purchase: 5 };

export const ALL_CARDS = ["item", "cost", "price_drift", "lock_in", "small_print", "company"];
/** Card titles in panel/src/components → the card names in contracts/stream-event.schema.json. */
export const CARD_TITLES = {
  "Purchase": "item",
  "Cost over time": "cost",
  "Price drift": "price_drift",
  "Lock-in": "lock_in",
  "Small print": "small_print",
  "Who's behind it": "company",
};
/** The four states the pass bar accepts. limit_reached (spend cap) makes the run invalid, so it fails. */
export const RESOLVED = new Set(["found", "estimated", "not_found", "n_a"]);

/** Which source each card comes from (backend/server/pipeline.py), and so which time limit applies. */
export const CARD_CLASS = { item: "page", price_drift: "page", company: "company", cost: "terms", lock_in: "terms", small_print: "terms" };
export const LIMITS_MS = { page: 2000, company: 5000, terms_new: 20000, terms_cached: 5000 };
export const FOUND_BAR = 0.6;

/** `category,url,notes` lines; blank lines and `#` comments are skipped. Notes may contain commas. */
export function parseUrls(text) {
  const out = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith("#") || /^category\s*,\s*url\b/i.test(line)) return;
    const [category, url, ...notes] = line.split(",");
    if (!CATEGORIES.includes(category.trim())) throw new Error(`line ${i + 1}: unknown category "${category}" (use ${CATEGORIES.join(", ")})`);
    if (!/^https?:\/\//.test(url?.trim() ?? "")) throw new Error(`line ${i + 1}: not a URL: "${url}"`);
    out.push({ n: out.length + 1, category: category.trim(), url: url.trim(), notes: notes.join(",").trim() });
  });
  return out;
}

/** "Purchase" → "item"; the error boundary's "Couldn't show this card (cost)" → "cost". */
export function cardName(title) {
  if (title in CARD_TITLES) return CARD_TITLES[title];
  const m = /Couldn't show this card \((\w+)\)/.exec(title ?? "");
  return m && ALL_CARDS.includes(m[1]) ? m[1] : null;
}

const s = (ms) => `${(ms / 1000).toFixed(1)} s`;

/** Why the URL could not be tested at all (the page never loaded, or the site blocked the visit). */
export function untestedReason(v) {
  if (v.gotoError) return `page did not load: ${v.gotoError}`;
  if (v.harnessError) return `harness error: ${v.harnessError}`;
  // `blocked` is set by the harness: `page answered HTTP 404` or `bot check ("…")`.
  if (v.blocked) return `untested: ${v.blocked}`;
  return null;
}

/** Everything wrong with the final panel state. An empty list means the state is correct. */
export function stateProblems(v) {
  const untested = untestedReason(v);
  if (untested) return [untested];
  const p = [];
  const panel = v.panel;
  if (!panel) return ["side panel did not open"];
  if (panel.spinner) p.push(`spinner still up after ${s(panel.capMs)}`);
  if (panel.loading) p.push(`panel stuck on "${panel.loading}"`);
  if (panel.error) p.push(`error banner: ${panel.error}`);
  for (const c of panel.cards) {
    if (!c.card) p.push(`unknown card "${c.title}"`);
    else if (c.state === "error") p.push(`${c.card} card failed to render`);
    else if (!RESOLVED.has(c.state)) p.push(`${c.card}: state "${c.state}"`);
  }
  const det = v.detection;
  if (v.category === "no_purchase") {
    if (det?.status === "purchase") p.push(`purchase detected (${det.detector}) on a non-purchase page`);
    if (!panel.noPurchase) p.push(`no "No purchase detected" card`);
    if (panel.cards.length !== 1) p.push(`${panel.cards.length} cards shown, expected exactly 1`);
  } else {
    if (!det) p.push("content script never reported a detection");
    else if (det.status !== "purchase") p.push(`no purchase detected (${v.category} page)`);
    else {
      const have = new Set(panel.cards.map((c) => c.card));
      const missing = ALL_CARDS.filter((c) => !have.has(c));
      if (missing.length) p.push(`never arrived: ${missing.join(", ")}`);
      if (panel.cards.find((c) => c.card === "item")?.state === "n_a") p.push(`Purchase card says "no purchase"`);
      if (panel.empty) p.push(`"No results came back for this page"`);
    }
  }
  return p;
}

/** Cards other than Purchase in the found state. */
export const foundCards = (v) => (v.panel?.cards ?? []).filter((c) => c.card && c.card !== "item" && c.state === "found").map((c) => c.card);

/**
 * One timing check per card that arrived. `cached`: the second visit, where T&C cards must be < 5 s.
 * On the first pass the T&C cards get the 20 s limit, since the backend may be extracting them fresh.
 */
export function timingChecks(v, { cached = false } = {}) {
  if (untestedReason(v) || !v.panel) return [];
  if (v.category === "no_purchase") {
    const ms = v.panel.noPurchase?.ms;
    return ms == null ? [] : [{ cls: "page", card: "no_purchase", ms, limit: LIMITS_MS.page, ok: ms <= LIMITS_MS.page }];
  }
  return v.panel.cards
    .filter((c) => c.card && c.ms != null && (!cached || CARD_CLASS[c.card] === "terms"))
    .map((c) => {
      const base = CARD_CLASS[c.card];
      const cls = base === "terms" ? (cached ? "terms_cached" : "terms_new") : base;
      return { cls, card: c.card, ms: c.ms, limit: LIMITS_MS[cls] };
    })
    .map((t) => ({ ...t, ok: t.ms <= t.limit }));
}

// ---------------------------------------------------------------------------
// Quote check: the harness looks again for each quote in its source.
// ---------------------------------------------------------------------------

/** Lower case, straight quotes and dashes, one space between words. */
export function normalise(text) {
  return (text ?? "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[‘’‚‛′`]/g, "'")
    .replace(/[“”„‟″]/g, '"')
    .replace(/[‐-―−]/g, "-")
    .replace(/[  -​  　﻿­]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** True if the quote is in the text, ignoring case, quote styles and whitespace. */
export function quoteIn(quote, text) {
  const q = normalise(quote), t = normalise(text);
  if (!q) return false;
  if (t.includes(q)) return true;
  // Tags stripped without a space can join words ("Fees</p><p>Exit" → "FeesExit"), so also compare without spaces.
  return t.replace(/ /g, "").includes(q.replace(/ /g, ""));
}

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", pound: "£", euro: "€", rsquo: "’", lsquo: "‘",
  ldquo: "“", rdquo: "”", ndash: "–", mdash: "—", hellip: "…", copy: "©", reg: "®", trade: "™" };

/** Rough HTML → text, good enough to look for a quote. */
export function htmlToText(html) {
  return (html ?? "")
    .replace(/<(script|style|noscript|template|svg)\b[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
      if (e[0] === "#") return String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
      return ENTITIES[e.toLowerCase()] ?? m;
    });
}

// ---------------------------------------------------------------------------
// Review sheet: every value the panel showed, with a verdict a person fills in.
// ---------------------------------------------------------------------------

export const REVIEW_COLUMNS = ["verdict", "category", "url", "card", "label", "value", "quote", "source", "check", "last_seen", "note"];
/**
 * check:
 *   verified        the quote is in the source (the harness fetched it again)
 *   not_in_source   the quote was not found in the source: look at this one first
 *   unchecked: ...  the source could not be read again (PDF, HTTP error, …)
 *   no_evidence     a value that needs a quote and link was shown without one: counts as wrong
 *   no_source       a company record without a source link: counts as wrong
 *   no_quote_needed a value taken from the page itself (item name, brand, total)
 */
export const AUTO_WRONG = new Set(["no_evidence", "no_source"]);

export function verdictOf(raw) {
  const v = (raw ?? "").trim().toLowerCase();
  if (/^(ok|correct|right|y|yes|✓|✔)$/.test(v)) return "ok";
  if (/^(wrong|incorrect|n|no|x|✗|✘)$/.test(v)) return "wrong";
  return "";
}

export const reviewKey = (r) => [r.url, r.card, r.label, r.value, r.quote].join("␟");

/** Minimal RFC 4180 CSV. */
export function parseCsv(text) {
  const rows = [];
  let row = [], field = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') q = false;
      else field += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += ch;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const [head, ...body] = rows.filter((r) => r.some((f) => f !== ""));
  if (!head) return [];
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h.trim(), r[i] ?? ""])));
}

export function toCsv(rows, columns = REVIEW_COLUMNS) {
  const cell = (v) => {
    const t = String(v ?? "");
    return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => cell(r[c])).join(","))].join("\n") + "\n";
}

/**
 * Merge this run's values into the existing sheet. Verdicts on values seen before are kept;
 * rows from earlier runs stay too (a value can come and go), but only `current` is scored.
 */
export function mergeReview(existing, visits, stamp) {
  const byKey = new Map(existing.map((r) => [reviewKey(r), { ...r, verdict: verdictOf(r.verdict) }]));
  const current = [];
  for (const v of visits) {
    for (const val of v.values ?? []) {
      const row = { category: v.category, url: v.url, card: val.card, label: val.label, value: val.value, quote: val.quote, source: val.source };
      const key = reviewKey(row);
      const prev = byKey.get(key);
      const merged = { ...(prev ?? { verdict: "", note: "" }), ...row, check: val.check, last_seen: stamp };
      byKey.set(key, merged);
      current.push(merged);
    }
  }
  // Values to look at first: suspected wrong, then unreviewed, then reviewed; then by URL order.
  const rank = (r) => (AUTO_WRONG.has(r.check) || r.verdict === "wrong" ? 0 : r.check === "not_in_source" ? 1 : r.verdict ? 3 : 2);
  const order = new Map(visits.map((v, i) => [v.url, i]));
  const rows = [...byKey.values()].sort((a, b) =>
    (b.last_seen === stamp) - (a.last_seen === stamp) || rank(a) - rank(b) || (order.get(a.url) ?? 1e9) - (order.get(b.url) ?? 1e9));
  return { rows, current };
}

export function valueCounts(current) {
  const wrong = current.filter((r) => r.verdict === "wrong" || AUTO_WRONG.has(r.check));
  const pending = current.filter((r) => !r.verdict && !AUTO_WRONG.has(r.check));
  return { total: current.length, wrong: wrong.length, pending: pending.length, suspect: pending.filter((r) => r.check === "not_in_source").length, wrongRows: wrong };
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(0)}%` : "n/a");
const percentile = (xs, p) => {
  if (!xs.length) return null;
  const sorted = [...xs].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
};

export function summarise(visits, { cachedVisits = null, review }) {
  const total = visits.length;
  const perUrl = visits.map((v) => {
    const problems = stateProblems(v);
    const timings = timingChecks(v);
    const cached = cachedVisits?.find((c) => c.url === v.url);
    const cachedTimings = cached ? timingChecks(cached, { cached: true }) : [];
    const cachedProblems = cached ? stateProblems(cached).map((p) => `second visit: ${p}`) : [];
    return { v, untested: untestedReason(v), problems, found: foundCards(v), timings: [...timings, ...cachedTimings], cachedProblems };
  });
  const untested = perUrl.filter((u) => u.untested).length;
  const correct = perUrl.filter((u) => u.problems.length === 0).length;
  const withFound = perUrl.filter((u) => u.found.length > 0).length;
  const timingClasses = ["page", "company", "terms_new", "terms_cached"].map((cls) => {
    const ts = perUrl.flatMap((u) => u.timings.filter((t) => t.cls === cls));
    const ms = ts.map((t) => t.ms);
    return { cls, limit: LIMITS_MS[cls], n: ts.length, over: ts.filter((t) => !t.ok).length, p50: percentile(ms, 50), p95: percentile(ms, 95), max: ms.length ? Math.max(...ms) : null };
  });
  const values = valueCounts(review.current);
  const cachedMeasured = cachedVisits != null;
  const bars = [
    { name: "Correct state", status: correct === total ? "PASS" : "FAIL",
      detail: `${correct}/${total} (${pct(correct, total)}), need 100%${untested ? `; ${untested} untested (page did not load, HTTP error, bot check or harness error)` : ""}` },
    { name: "Zero wrong values", status: values.wrong ? "FAIL" : values.pending ? "PENDING" : "PASS",
      detail: `${values.wrong} wrong, ${values.pending} of ${values.total} values not reviewed yet${values.suspect ? ` (${values.suspect} quotes not found in their source)` : ""}` },
    { name: "Found cards", status: withFound / Math.max(total, 1) >= FOUND_BAR ? "PASS" : "FAIL",
      detail: `${withFound}/${total} (${pct(withFound, total)}) show one or more found cards, need ≥ ${FOUND_BAR * 100}% (Purchase card not counted)` },
    { name: "Timings", status: timingClasses.some((c) => c.over) ? "FAIL" : cachedMeasured ? "PASS" : "PENDING",
      detail: `${timingClasses.reduce((a, c) => a + c.over, 0)} cards over their limit${cachedMeasured ? "" : "; cached T&Cs not measured (second visit skipped)"}` },
  ];
  return { total, perUrl, bars, timingClasses, values };
}

const CLASS_LABEL = { page: "Page cards (item, price drift, no-purchase)", company: "Company", terms_new: "T&C cards, first visit (new extraction)", terms_cached: "T&C cards, second visit (cached)" };
const CAT_SHORT = { amazon: "amzn", subscription: "subs", jsonld: "j-ld", no_purchase: "none" };

export function formatReport(summary, meta) {
  const L = [];
  const mix = Object.fromEntries(CATEGORIES.map((c) => [c, summary.perUrl.filter((u) => u.v.category === c).length]));
  L.push(`SmallPrint 40-URL test · ${meta.stamp}`);
  L.push(`Server ${meta.server} · ${meta.headless ? "headless" : "headed"} Chromium ${meta.browserVersion ?? ""} · extension ${meta.extensionVersion ?? "?"}`);
  L.push(`${summary.total} URLs: ${CATEGORIES.map((c) => `${mix[c]} ${c}`).join(", ")}`);
  const off = CATEGORIES.filter((c) => Math.abs(mix[c] - EXPECTED_MIX[c]) > 2);
  if (off.length) L.push(`  note: the mix differs from the definition of done (about ${CATEGORIES.map((c) => `${EXPECTED_MIX[c]} ${c}`).join(", ")})`);
  L.push("");
  L.push("PASS BAR");
  for (const b of summary.bars) L.push(`  ${`[${b.status}]`.padEnd(10)} ${b.name.padEnd(18)} ${b.detail}`);
  L.push("");
  L.push("TIMINGS (from opening the panel)");
  for (const c of summary.timingClasses) {
    const body = c.n ? `p50 ${s(c.p50)} · p95 ${s(c.p95)} · max ${s(c.max)} · ${c.over}/${c.n} over` : "not measured";
    L.push(`  ${CLASS_LABEL[c.cls].padEnd(44)} limit ${s(c.limit).padStart(6)}  ${body}`);
  }
  L.push("");
  L.push("PER URL");
  L.push(`  ${"#".padStart(2)}  cat   ${"result".padEnd(8)} ${"found".padEnd(30)} ${"slowest".padEnd(18)} url`);
  for (const u of summary.perUrl) {
    const over = u.timings.filter((t) => !t.ok);
    const result = u.untested ? "UNTESTED" : u.problems.length ? "FAIL" : over.length ? "SLOW" : "ok";
    const slowest = u.timings.filter((t) => !t.cls.endsWith("cached")).sort((a, b) => b.ms - a.ms)[0];
    L.push(`  ${String(u.v.n).padStart(2)}  ${CAT_SHORT[u.v.category]}  ${result.padEnd(8)} ${(u.found.join(",") || "-").padEnd(30)} ${(slowest ? `${slowest.card} ${s(slowest.ms)}` : "-").padEnd(18)} ${u.v.url}`);
    for (const p of u.problems) L.push(`        ✗ ${p}`);
    for (const t of over) L.push(`        ⏱ ${t.card}${t.cls === "terms_cached" ? " (second visit)" : ""} ${s(t.ms)} > ${s(t.limit)}`);
    for (const p of u.cachedProblems) L.push(`        · ${p}`);
  }
  if (summary.values.wrongRows.length) {
    L.push("");
    L.push("WRONG VALUES");
    for (const r of summary.values.wrongRows) L.push(`  ${r.url}  ${r.card} · ${r.label}: ${r.value}  (${r.check === "no_evidence" || r.check === "no_source" ? r.check : "marked wrong"})`);
  }
  L.push("");
  L.push(`Review sheet: ${meta.reviewPath} (fill in the verdict column with ok or wrong; verdicts carry over to the next run)`);
  L.push(`Run folder:   ${meta.runDir} (results.json, report.txt, one panel screenshot per URL)`);
  const all = summary.bars.every((b) => b.status === "PASS");
  L.push("");
  const named = (st) => summary.bars.filter((b) => b.status === st).map((b) => b.name).join(", ");
  L.push(all ? "RESULT: PASS" : `RESULT: ${["FAIL", "PENDING"].filter(named).map((st) => `${st} (${named(st)})`).join("; ")}`);
  return L.join("\n");
}

/** 0 = every bar passes, 1 = a bar fails, 2 = nothing fails but something is still pending (review, cached timings). */
export const exitCode = (summary) =>
  summary.bars.some((b) => b.status === "FAIL") ? 1 : summary.bars.some((b) => b.status === "PENDING") ? 2 : 0;
