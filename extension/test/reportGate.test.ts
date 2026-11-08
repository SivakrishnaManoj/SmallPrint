import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Detection } from "../src/detect";
import { debounceWithMaxWait, nextReport } from "../src/reportGate";

const URL_A = "https://shop.example/p/dress";
const URL_B = "https://shop.example/p/coat";
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

describe("nextReport", () => {
  it("reports the first detection, purchase or none", () => {
    expect(nextReport(null, URL_A, none)).toEqual(none);
    expect(nextReport(null, URL_A, purchase("Dress"))).toEqual(purchase("Dress"));
  });

  it("reports nothing when the result has not changed", () => {
    expect(nextReport({ url: URL_A, detection: purchase("Dress") }, URL_A, purchase("Dress"))).toBeNull();
    expect(nextReport({ url: URL_A, detection: none }, URL_A, none)).toBeNull();
  });

  it("keeps a purchase when the same URL briefly shows none (JSON-LD removed during a re-render)", () => {
    expect(nextReport({ url: URL_A, detection: purchase("Dress") }, URL_A, none)).toBeNull();
  });

  it("reports a purchase that renders late on the same URL", () => {
    expect(nextReport({ url: URL_A, detection: none }, URL_A, purchase("Dress"))).toEqual(purchase("Dress"));
  });

  it("reports a changed purchase on the same URL (price or name re-rendered)", () => {
    expect(nextReport({ url: URL_A, detection: purchase("Dress", 70) }, URL_A, purchase("Dress", 63))).toEqual(purchase("Dress", 63));
  });

  it("reports none after a purchase when the URL changed", () => {
    expect(nextReport({ url: URL_A, detection: purchase("Dress") }, URL_B, none)).toEqual(none);
  });
});

describe("debounceWithMaxWait", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("runs once, `wait` ms after the last call, when the calls stop", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, 1500);
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
    const soon = debounceWithMaxWait(fn, 600, 1500);
    for (let t = 0; t < 4500; t += 50) {
      soon();
      vi.advanceTimersByTime(50);
    }
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("honours a shorter wait passed to a single call", () => {
    const fn = vi.fn();
    const soon = debounceWithMaxWait(fn, 600, 1500);
    soon(300);
    vi.advanceTimersByTime(300);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
