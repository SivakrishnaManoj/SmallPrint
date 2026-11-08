import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Detection } from "../src/detect";
import { debounceWithMaxWait, ReportGate } from "../src/reportGate";

const URL_A = "https://shop.example/p/dress";
const URL_B = "https://shop.example/c/dresses";
const none: Detection = { status: "none", checkout: false };
const purchase = (name: string, price = 70): Detection => ({
  status: "purchase",
  detector: "jsonld",
  checkout: false,
  request: {
    item: { name, brand: "Shop", price, seller: null, url: URL_A, id: null },
    purchase_type_signals: ["product"],
    links: [],
    page_text_snippets: [],
  },
});

describe("ReportGate", () => {
  it("reports the first detection, purchase or none", () => {
    expect(new ReportGate().decide(URL_A, none, 0)).toEqual({ send: none });
    expect(new ReportGate().decide(URL_A, purchase("Dress"), 0)).toEqual({ send: purchase("Dress") });
  });

  it("reports nothing when the result has not changed", () => {
    const g = new ReportGate();
    g.decide(URL_A, purchase("Dress"), 0);
    expect(g.decide(URL_A, purchase("Dress"), 100)).toBeNull();
  });

  it("holds a none that follows a purchase on the same URL, and asks for a re-check", () => {
    const g = new ReportGate(5000);
    g.decide(URL_A, purchase("Dress"), 0);
    expect(g.decide(URL_A, none, 1000)).toEqual({ recheckInMs: 5000 });
    expect(g.decide(URL_A, none, 3000)).toEqual({ recheckInMs: 3000 });
  });

  it("keeps the purchase when the JSON-LD comes back within the hold (PrettyLittleThing re-render)", () => {
    const g = new ReportGate(5000);
    g.decide(URL_A, purchase("Dress"), 0);
    g.decide(URL_A, none, 1000);
    expect(g.decide(URL_A, purchase("Dress"), 3000)).toBeNull();
    // The hold restarts from scratch next time.
    expect(g.decide(URL_A, none, 20_000)).toEqual({ recheckInMs: 5000 });
  });

  it("reports none once it has lasted the hold (the product really went away)", () => {
    const g = new ReportGate(5000);
    g.decide(URL_A, purchase("Dress"), 0);
    g.decide(URL_A, none, 1000);
    expect(g.decide(URL_A, none, 6000)).toEqual({ send: none });
    expect(g.hasPurchase(URL_A)).toBe(false);
  });

  it("does not leave a stale product stuck after a single-page navigation", () => {
    // pushState changes the URL first; the old product's JSON-LD is still in the DOM.
    const g = new ReportGate(5000);
    g.decide(URL_A, purchase("Dress"), 0);
    expect(g.decide(URL_B, purchase("Dress"), 500)).toEqual({ send: purchase("Dress") });
    // The category page then renders without JSON-LD.
    expect(g.decide(URL_B, none, 900)).toEqual({ recheckInMs: 5000 });
    expect(g.decide(URL_B, none, 5900)).toEqual({ send: none });
  });

  it("reports a purchase that renders late, and a changed price, at once", () => {
    const g = new ReportGate();
    g.decide(URL_A, none, 0);
    expect(g.decide(URL_A, purchase("Dress", 70), 100)).toEqual({ send: purchase("Dress", 70) });
    expect(g.decide(URL_A, purchase("Dress", 63), 200)).toEqual({ send: purchase("Dress", 63) });
  });

  it("reports none at once on a new URL", () => {
    const g = new ReportGate();
    g.decide(URL_A, purchase("Dress"), 0);
    expect(g.decide(URL_B, none, 100)).toEqual({ send: none });
  });
});

describe("debounceWithMaxWait", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("runs once, `wait` ms after the last call, when the calls stop", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, () => 1500);
    soon();
    vi.advanceTimersByTime(400);
    soon();
    vi.advanceTimersByTime(599);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("still runs every `maxWait` ms when calls never stop (a page that changes 20 times a second)", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, () => 1500);
    for (let t = 0; t < 4500; t += 50) {
      soon();
      vi.advanceTimersByTime(50);
    }
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("acts as a plain debounce when maxWait() is null (never runs while calls continue)", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, () => null);
    for (let t = 0; t < 4500; t += 50) {
      soon();
      vi.advanceTimersByTime(50);
    }
    expect(fn).not.toHaveBeenCalled();
  });

  it("cancel() drops a pending deadline, so a new wait is honoured (URL change)", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, () => 1500);
    for (let t = 0; t < 1400; t += 50) {
      soon();
      vi.advanceTimersByTime(50);
    }
    soon.cancel();
    soon(300);
    vi.advanceTimersByTime(200); // the old deadline would have fired at 1500 ms
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
