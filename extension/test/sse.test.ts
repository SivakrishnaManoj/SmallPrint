import { describe, expect, it } from "vitest";
import { AnalyseError, SSEParser, buildBody, buildHeaders, streamAnalyse } from "../src/sse";
import { CANNED_REQUEST } from "../src/config";

const enc = new TextEncoder();
const UUID = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b";
const FAST = { connectMs: 200, idleMs: 200, totalMs: 2000, installId: UUID };

/** A fetch whose body emits `chunks` (strings, or a number = delay in ms), then optionally hangs. */
function fakeFetch(chunks: (string | number)[], init: { status?: number; type?: string; hang?: boolean } = {}): typeof fetch {
  return (async (_url: RequestInfo | URL, req?: RequestInit) => {
    const signal = req?.signal ?? undefined;
    const body = new ReadableStream<Uint8Array>({
      async start(ctrl) {
        signal?.addEventListener("abort", () => {
          try { ctrl.error(new DOMException("aborted", "AbortError")); } catch { /* closed */ }
        });
        for (const c of chunks) {
          if (signal?.aborted) return;
          if (typeof c === "number") await new Promise((r) => setTimeout(r, c));
          else ctrl.enqueue(enc.encode(c));
        }
        if (!init.hang) ctrl.close();
      },
    });
    return new Response(body, {
      status: init.status ?? 200,
      headers: { "content-type": init.type ?? "text/event-stream; charset=utf-8" },
    });
  }) as typeof fetch;
}

const card = (name: string, state = "found", payload: unknown = {}) =>
  `event: card\r\ndata: ${JSON.stringify({ card: name, state, payload })}\r\n\r\n`;
const DONE = "event: done\r\ndata: {}\r\n\r\n";

async function collect(f: typeof fetch, opts = FAST) {
  const out: string[] = [];
  for await (const c of streamAnalyse("http://x", CANNED_REQUEST, { ...opts, fetchImpl: f })) out.push(c.card);
  return out;
}

describe("SSEParser", () => {
  it("parses CRLF events, comments and multi-line data", () => {
    const p = new SSEParser();
    const msgs = p.push(": ping\r\n\r\nevent: card\r\ndata: a\r\ndata: b\r\n\r\ndata: plain\n\n");
    expect(msgs).toEqual([{ event: "card", data: "a\nb" }, { event: "message", data: "plain" }]);
  });

  it("handles a CRLF split across chunks and events split mid-line", () => {
    const p = new SSEParser();
    const text = card("item") + card("cost");
    const out = [];
    for (const ch of text) out.push(...p.push(ch)); // one character at a time
    out.push(...p.end());
    expect(out.map((m) => JSON.parse(m.data).card)).toEqual(["item", "cost"]);
  });
});

describe("streamAnalyse", () => {
  it("yields cards in order and stops at done", async () => {
    const f = fakeFetch([card("item"), 20, card("cost") + card("lock_in"), DONE, card("company")]);
    expect(await collect(f)).toEqual(["item", "cost", "lock_in"]);
  });

  it("skips malformed card events", async () => {
    const f = fakeFetch(["event: card\r\ndata: {nope\r\n\r\n", card("bogus"), card("item"), DONE]);
    expect(await collect(f)).toEqual(["item"]);
  });

  it("throws ended_early if the stream closes without done", async () => {
    const f = fakeFetch([card("item")]);
    await expect(collect(f)).rejects.toMatchObject({ kind: "ended_early" });
  });

  it("throws timeout when the server goes silent mid-stream", async () => {
    const f = fakeFetch([card("item")], { hang: true });
    await expect(collect(f)).rejects.toMatchObject({ kind: "timeout" });
  });

  it("throws timeout when pings keep the stream alive past the total cap", async () => {
    const pings = Array.from({ length: 30 }, () => [": ping\r\n\r\n", 50]).flat();
    const f = fakeFetch(pings, { hang: true });
    await expect(collect(f, { ...FAST, totalMs: 400 })).rejects.toMatchObject({ kind: "timeout" });
  });

  it("throws timeout when the server never answers", async () => {
    const f = ((_u: RequestInfo | URL, req?: RequestInit) =>
      new Promise((_, reject) => req?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))) as typeof fetch;
    await expect(collect(f)).rejects.toMatchObject({ kind: "timeout" });
  });

  it("reports HTTP errors and non-SSE responses", async () => {
    await expect(collect(fakeFetch(['{"detail":"Rate limit exceeded"}'], { status: 429, type: "application/json" })))
      .rejects.toMatchObject({ kind: "http", message: expect.stringContaining("429") });
    await expect(collect(fakeFetch(["<html>ngrok</html>"], { type: "text/html" })))
      .rejects.toMatchObject({ kind: "not_sse" });
  });

  it("reports network failures", async () => {
    const f = (async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
    const err = await collect(f).catch((e) => e);
    expect(err).toBeInstanceOf(AnalyseError);
    expect(err.kind).toBe("network");
  });

  it("stops cleanly when the caller aborts", async () => {
    const ctrl = new AbortController();
    const f = fakeFetch([card("item")], { hang: true });
    const seen: string[] = [];
    const err = await (async () => {
      for await (const c of streamAnalyse("http://x", CANNED_REQUEST, { ...FAST, idleMs: 5000, signal: ctrl.signal, fetchImpl: f })) {
        seen.push(c.card);
        ctrl.abort();
      }
    })().catch((e) => e);
    expect(seen).toEqual(["item"]);
    expect(err.kind).toBe("aborted");
  });
});

describe("what leaves the browser", () => {
  it("sends the install UUID only as X-Install-Id, and page data only in the body", async () => {
    let sent: RequestInit | undefined;
    const base = fakeFetch([DONE]);
    const f = ((u: RequestInfo | URL, init?: RequestInit) => { sent = init; return base(u, init); }) as typeof fetch;
    // Simulate stray user data on the request object.
    const leaky = { ...CANNED_REQUEST, install_id: "body-id", postcode: "EH1 1YZ", horizon: 24 } as typeof CANNED_REQUEST;
    for await (const _ of streamAnalyse("http://localhost:8000", leaky, { ...FAST, fetchImpl: f })) { /* drain */ }

    expect(sent?.headers).toEqual({ "Content-Type": "application/json", Accept: "text/event-stream", "X-Install-Id": UUID });
    expect(sent?.credentials).toBe("omit");
    const body = JSON.parse(String(sent?.body));
    expect(Object.keys(body).sort()).toEqual(["item", "links", "page_text_snippets", "price_drift", "purchase_type_signals"]);
    expect(JSON.stringify(body)).not.toMatch(/install_id|postcode|horizon|EH1/);
  });

  it("adds the ngrok header only for ngrok hosts", () => {
    expect(buildHeaders("https://abc.ngrok-free.app/analyse", UUID)).toHaveProperty("ngrok-skip-browser-warning");
    expect(buildHeaders("http://localhost:8000/analyse", UUID)).not.toHaveProperty("ngrok-skip-browser-warning");
  });

  it("buildBody drops unknown fields", () => {
    expect(buildBody({ ...CANNED_REQUEST, extra: 1 } as typeof CANNED_REQUEST)).not.toHaveProperty("extra");
  });

  it("refuses to send without an install ID", async () => {
    await expect(collect(fakeFetch([DONE]), { ...FAST, installId: "" })).rejects.toBeInstanceOf(AnalyseError);
  });
});
