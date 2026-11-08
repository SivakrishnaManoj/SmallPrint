import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { LIMITS, fetchTermsDocument, fetchTermsDocuments, isPdf, pickTermsLinks, toBase64 } from "../src/terms/fetchTerms";

const TERMS = resolve(__dirname, "../../fixtures/pages/terms");
const HTML = readFileSync(`${TERMS}/fernline-terms.html`);
const PDF = readFileSync(`${TERMS}/fernline-contract-summary.pdf`);

/** A fetch that serves fixed responses by URL and records what it was asked for. */
function fakeFetch(routes: Record<string, () => Response | Promise<Response>>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const f = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const route = routes[url];
    if (!route) throw new TypeError("Failed to fetch");
    return route();
  }) as typeof fetch;
  return { f, calls };
}

const ok = (body: BodyInit, type: string) => () => new Response(body, { status: 200, headers: { "content-type": type } });

describe("pickTermsLinks", () => {
  it("keeps T&C kinds only, best first, de-duplicated, at most 3", () => {
    const picked = pickTermsLinks([
      { url: "https://x.co.uk/privacy", kind: "privacy" },
      { url: "https://x.co.uk/returns", kind: "returns" },
      { url: "https://x.co.uk/terms", kind: "terms" },
      { url: "https://x.co.uk/terms", kind: "terms" },
      { url: "https://x.co.uk/summary.pdf", kind: "contract_summary" },
      { url: "https://x.co.uk/cancel", kind: "cancel" },
      { url: "mailto:help@x.co.uk", kind: "terms" },
    ]);
    expect(picked).toEqual([
      { url: "https://x.co.uk/terms", kind: "terms" },
      { url: "https://x.co.uk/summary.pdf", kind: "contract_summary" },
      { url: "https://x.co.uk/cancel", kind: "cancel" },
    ]);
  });
});

describe("fetchTermsDocument", () => {
  it("sends an HTML page as text", async () => {
    const { f, calls } = fakeFetch({ "https://f.co.uk/terms": ok(HTML, "text/html; charset=utf-8") });
    const doc = await fetchTermsDocument("https://f.co.uk/terms", "terms", { fetchImpl: f });
    expect(doc).toMatchObject({ url: "https://f.co.uk/terms", kind: "terms" });
    expect("text" in doc && doc.text).toContain("minimum term of 24 months");
    // Plain fetch: no cookies, no referrer, no custom headers (so no User-Agent games).
    expect(calls[0].init).toMatchObject({ credentials: "omit", referrerPolicy: "no-referrer" });
    expect(calls[0].init?.headers).toBeUndefined();
  });

  it("sends a PDF as base64 bytes, by content type or by %PDF magic", async () => {
    const { f } = fakeFetch({
      "https://f.co.uk/a.pdf": ok(PDF, "application/pdf"),
      "https://f.co.uk/download?id=7": ok(PDF, "application/octet-stream; mislabelled"),
    });
    for (const url of ["https://f.co.uk/a.pdf", "https://f.co.uk/download?id=7"]) {
      const doc = await fetchTermsDocument(url, "contract_summary", { fetchImpl: f });
      expect("pdf_b64" in doc && Buffer.from(doc.pdf_b64, "base64").equals(PDF)).toBe(true);
    }
  });

  it("flags HTTP errors, network errors and timeouts for the search fallback", async () => {
    const { f } = fakeFetch({
      "https://f.co.uk/blocked": () => new Response("Forbidden", { status: 403 }),
      "https://f.co.uk/slow": () => new Promise<Response>(() => {}),
    });
    expect(await fetchTermsDocument("https://f.co.uk/blocked", "terms", { fetchImpl: f }))
      .toEqual({ url: "https://f.co.uk/blocked", kind: "terms", fetch_failed: true, error: "HTTP 403" });
    expect(await fetchTermsDocument("https://f.co.uk/gone", "terms", { fetchImpl: f }))
      .toMatchObject({ fetch_failed: true, error: expect.stringMatching(/^Network error/) });
    const slow = (async (_u: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))) as typeof fetch;
    expect(await fetchTermsDocument("https://f.co.uk/slow", "terms", { fetchImpl: slow, timeoutMs: 50 }))
      .toMatchObject({ fetch_failed: true, error: expect.stringMatching(/^Timed out/) });
  });

  it("flags empty, unsupported and oversized responses", async () => {
    const big = new Uint8Array(LIMITS.maxPdfBytes + 1);
    big.set(new TextEncoder().encode("%PDF-1.7"));
    const { f } = fakeFetch({
      "https://f.co.uk/empty": ok("", "text/html"),
      "https://f.co.uk/img": ok("GIF89a", "image/gif"),
      "https://f.co.uk/huge.pdf": ok(big, "application/pdf"),
    });
    expect(await fetchTermsDocument("https://f.co.uk/empty", "terms", { fetchImpl: f })).toMatchObject({ fetch_failed: true, error: "Empty response" });
    expect(await fetchTermsDocument("https://f.co.uk/img", "terms", { fetchImpl: f })).toMatchObject({ fetch_failed: true, error: expect.stringContaining("image/gif") });
    expect(await fetchTermsDocument("https://f.co.uk/huge.pdf", "terms", { fetchImpl: f })).toMatchObject({ fetch_failed: true, error: expect.stringContaining("too large") });
  });

  it("cuts very long pages to the contract's 500,000 characters instead of dropping them", async () => {
    const { f } = fakeFetch({ "https://f.co.uk/long": ok("x".repeat(LIMITS.maxTextChars + 10), "text/plain") });
    const doc = await fetchTermsDocument("https://f.co.uk/long", "terms", { fetchImpl: f });
    expect("text" in doc && doc.text.length).toBe(LIMITS.maxTextChars);
  });

  it("rethrows when the whole analysis is cancelled", async () => {
    const ctrl = new AbortController();
    const hang = (async (_u: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))) as typeof fetch;
    const p = fetchTermsDocument("https://f.co.uk/x", "terms", { fetchImpl: hang, signal: ctrl.signal });
    ctrl.abort();
    await expect(p).rejects.toThrow();
  });
});

describe("fetchTermsDocuments", () => {
  it("fetches the picked links in parallel and mixes results", async () => {
    const { f } = fakeFetch({
      "https://f.co.uk/terms": ok(HTML, "text/html"),
      "https://f.co.uk/summary.pdf": ok(PDF, "application/pdf"),
      "https://f.co.uk/cancel": () => new Response("", { status: 403 }),
    });
    const docs = await fetchTermsDocuments(
      [
        { url: "https://f.co.uk/cancel", kind: "cancel" },
        { url: "https://f.co.uk/summary.pdf", kind: "contract_summary" },
        { url: "https://f.co.uk/terms", kind: "terms" },
      ],
      { fetchImpl: f },
    );
    expect(docs.map((d) => [d.kind, "text" in d ? "text" : "pdf_b64" in d ? "pdf" : "failed"])).toEqual([
      ["terms", "text"],
      ["contract_summary", "pdf"],
      ["cancel", "failed"],
    ]);
  });
});

describe("helpers", () => {
  it("isPdf and toBase64", () => {
    expect(isPdf(new Uint8Array(PDF))).toBe(true);
    expect(isPdf(new Uint8Array(HTML))).toBe(false);
    expect(toBase64(new Uint8Array(PDF))).toBe(PDF.toString("base64"));
  });
});
