// node --test demo/run40
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as S from "./score.mjs";

const cards = (states, ms = {}) =>
  Object.entries(states).map(([card, state]) => ({ card, title: Object.keys(S.CARD_TITLES).find((t) => S.CARD_TITLES[t] === card), state, ms: ms[card] ?? 500 }));
const panel = (over = {}) => ({ cards: [], noPurchase: null, error: null, spinner: false, loading: null, empty: false, capMs: 90000, ...over });
const purchase = (states, extra = {}) => ({
  n: 1, category: "amazon", url: "https://www.amazon.co.uk/dp/X",
  detection: { status: "purchase", detector: "amazon" },
  panel: panel({ cards: cards(states, extra.ms) }), values: [], ...extra,
});
const SIX = { item: "found", price_drift: "n_a", cost: "found", lock_in: "not_found", small_print: "estimated", company: "found" };

test("demo/urls40.txt parses into the four categories", () => {
  const urls = S.parseUrls(readFileSync(resolve(import.meta.dirname, "../urls40.txt"), "utf8"));
  assert.equal(urls.length, 40);
  assert.deepEqual(new Set(urls.map((u) => u.category)), new Set(S.CATEGORIES));
  assert.deepEqual(urls.map((u) => u.n), [...Array(40).keys()].map((i) => i + 1));
});

test("parseUrls keeps commas in notes and rejects unknown categories", () => {
  assert.equal(S.parseUrls("category,url,notes\njsonld,https://a.example/p,Bosch, 10kg")[0].notes, "Bosch, 10kg");
  assert.throws(() => S.parseUrls("shop,https://a.example/p,x"), /unknown category "shop"/);
  assert.throws(() => S.parseUrls("amazon,www.amazon.co.uk/dp/X,x"), /not a URL/);
});

test("cardName maps titles and error boundaries", () => {
  assert.equal(S.cardName("Who's behind it"), "company");
  assert.equal(S.cardName("Couldn't show this card (lock_in)"), "lock_in");
  assert.equal(S.cardName("Something new"), null);
});

test("a purchase page with six resolved cards is correct", () => {
  assert.deepEqual(S.stateProblems(purchase(SIX)), []);
});

test("purchase page failures", () => {
  const { company, ...five } = SIX;
  assert.match(S.stateProblems(purchase(five)).join(), /never arrived: company/);
  assert.match(S.stateProblems(purchase({ ...SIX, cost: "limit_reached" })).join(), /cost: state "limit_reached"/);
  assert.match(S.stateProblems(purchase({ ...SIX, cost: "error" })).join(), /cost card failed to render/);
  const spinning = purchase(SIX);
  spinning.panel.spinner = true;
  assert.match(S.stateProblems(spinning).join(), /spinner still up/);
  assert.match(S.stateProblems({ ...purchase({}), detection: { status: "none" } }).join(), /no purchase detected \(amazon page\)/);
  assert.match(S.stateProblems({ ...purchase({}), detection: null }).join(), /never reported a detection/);
  assert.match(S.stateProblems({ ...purchase(SIX), panel: panel({ cards: cards(SIX), error: "HTTP 500" }) }).join(), /error banner: HTTP 500/);
});

test("non-purchase page must show exactly the one no-purchase card", () => {
  const good = { category: "no_purchase", detection: { status: "none" }, panel: panel({ cards: cards({ item: "n_a" }), noPurchase: { ms: 300 } }) };
  assert.deepEqual(S.stateProblems(good), []);
  const bad = { ...good, detection: { status: "purchase", detector: "jsonld" }, panel: panel({ cards: cards(SIX) }) };
  const p = S.stateProblems(bad).join(" | ");
  assert.match(p, /purchase detected \(jsonld\) on a non-purchase page/);
  assert.match(p, /6 cards shown, expected exactly 1/);
});

test("blocked or unloaded pages are untested, and count against the state bar", () => {
  const v = { ...purchase(SIX), blocked: 'bot check ("not a robot")' };
  assert.deepEqual(S.stateProblems(v), ['untested: bot check ("not a robot")']);
  assert.deepEqual(S.stateProblems({ ...purchase(SIX), blocked: "page answered HTTP 404" }), ["untested: page answered HTTP 404"]);
  assert.deepEqual(S.timingChecks(v), []);
});

test("found cards leave out the Purchase card", () => {
  assert.deepEqual(S.foundCards(purchase(SIX)), ["cost", "company"]);
  assert.deepEqual(S.foundCards(purchase({ item: "found", cost: "estimated" })), []);
});

test("timing limits per card source", () => {
  const v = purchase(SIX, { ms: { item: 2500, price_drift: 100, company: 4900, cost: 19000, lock_in: 21000, small_print: 100 } });
  const over = S.timingChecks(v).filter((t) => !t.ok).map((t) => `${t.card}:${t.cls}`);
  assert.deepEqual(over.sort(), ["item:page", "lock_in:terms_new"]);
  const cached = S.timingChecks(v, { cached: true });
  assert.deepEqual(cached.map((t) => t.card).sort(), ["cost", "lock_in", "small_print"]);
  assert.deepEqual(cached.filter((t) => !t.ok).map((t) => t.card).sort(), ["cost", "lock_in"]);
  const none = { category: "no_purchase", panel: panel({ cards: cards({ item: "n_a" }), noPurchase: { ms: 2100 } }) };
  assert.deepEqual(S.timingChecks(none).map((t) => [t.card, t.ok]), [["no_purchase", false]]);
});

test("quoteIn ignores case, curly quotes, dashes and spacing", () => {
  const html = "<p>You can cancel at any time&nbsp;&ndash; we’ll stop</p><p>Exit fee: &pound;5</p><script>var x='nope'</script>";
  const text = S.htmlToText(html);
  assert.ok(S.quoteIn("you can cancel at any time - we'll stop", text));
  assert.ok(S.quoteIn("Exit fee: £5", text));
  assert.ok(!S.quoteIn("nope", text));
  assert.ok(S.quoteIn("stopExit", "stop</p><p>Exit".replace(/<[^>]+>/g, "")));
  assert.ok(!S.quoteIn("", "anything"));
});

test("CSV round trip keeps commas, quotes and new lines", () => {
  const rows = [{ verdict: "ok", url: "https://a/b", quote: 'He said "24, months"\nthen', value: "£1,000" }];
  const back = S.parseCsv(S.toCsv(rows));
  assert.equal(back[0].quote, rows[0].quote);
  assert.equal(back[0].value, "£1,000");
  assert.equal(back[0].card, "");
});

test("review verdicts carry over between runs; auto failures count as wrong", () => {
  const value = { card: "lock_in", label: "Minimum term", value: "24 months", quote: "minimum term of 24 months", source: "https://t", check: "verified" };
  const visits = [{ category: "subscription", url: "https://u", values: [value, { ...value, label: "Exit fee", value: "£5", quote: "", source: "", check: "no_evidence" }] }];
  const first = S.mergeReview([], visits, "run1");
  assert.deepEqual(S.valueCounts(first.current), { total: 2, wrong: 1, pending: 1, suspect: 0, wrongRows: [first.current[1]] });
  // Someone marks the first value ok; the next run keeps the verdict.
  const sheet = S.parseCsv(S.toCsv(first.rows)).map((r) => (r.label === "Minimum term" ? { ...r, verdict: "OK" } : r));
  const second = S.mergeReview(sheet, [{ ...visits[0], values: [value] }], "run2");
  assert.equal(second.current[0].verdict, "ok");
  assert.deepEqual(S.valueCounts(second.current).pending, 0);
  // The exit-fee row from run1 stays in the sheet but is not scored.
  assert.equal(second.rows.length, 2);
  assert.equal(second.rows.at(-1).last_seen, "run1");
});

test("report: bars, statuses and exit code", () => {
  const visits = [purchase(SIX), { n: 2, category: "no_purchase", url: "https://news", detection: { status: "none" }, panel: panel({ cards: cards({ item: "n_a" }), noPurchase: { ms: 200 } }), values: [] }];
  const review = S.mergeReview([], visits, "r");
  const sum = S.summarise(visits, { cachedVisits: [purchase(SIX)], review });
  assert.deepEqual(sum.bars.map((b) => b.status), ["PASS", "PASS", "FAIL", "PASS"]); // 1 of 2 with found cards = 50%
  assert.equal(S.exitCode(sum), 1);
  const text = S.formatReport(sum, { stamp: "r", server: "http://x", headless: true, reviewPath: "demo/review40.csv", runDir: "demo/results/r" });
  assert.match(text, /\[PASS\]\s+Correct state\s+2\/2 \(100%\)/);
  assert.match(text, /\[FAIL\]\s+Found cards\s+1\/2 \(50%\)/);
  assert.match(text, /RESULT: FAIL \(Found cards\)/);
  const noCached = S.summarise([purchase(SIX)], { cachedVisits: null, review: S.mergeReview([], [], "r") });
  assert.equal(noCached.bars[3].status, "PENDING");
  assert.equal(S.exitCode(noCached), 2);
});
