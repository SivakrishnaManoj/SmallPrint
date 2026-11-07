/**
 * Client for POST /analyse, which answers with a Server-Sent Events stream
 * (contracts/stream-event.schema.json): `event: card` per card, then `event: done`.
 *
 * EventSource can't POST, so we read the fetch body ourselves. Every way the stream
 * can stall or break ends in a thrown AnalyseError, so callers can always clear
 * their loading state in `finally`.
 */
import type { StreamCard } from "~panel/types";
import type { AnalyseBody } from "./config";

export interface SSEMessage {
  event: string;
  data: string;
}

/**
 * Incremental SSE parser (WHATWG "event stream interpretation").
 * Handles CRLF / CR / LF line endings (sse-starlette sends CRLF), line endings split
 * across chunks, multi-line `data:`, and `:` comment lines (keep-alive pings).
 */
export class SSEParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];

  push(text: string): SSEMessage[] {
    this.buffer += text;
    const out: SSEMessage[] = [];
    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch !== "\n" && ch !== "\r") continue;
      // A trailing CR might be the first half of a CRLF split across chunks: wait.
      if (ch === "\r" && i === this.buffer.length - 1) break;
      this.line(this.buffer.slice(start, i), out);
      if (ch === "\r" && this.buffer[i + 1] === "\n") i++;
      start = i + 1;
    }
    this.buffer = this.buffer.slice(start);
    return out;
  }

  /** Call at end of stream. Per spec, an event without its terminating blank line is dropped. */
  end(): SSEMessage[] {
    const out: SSEMessage[] = [];
    if (this.buffer.endsWith("\r")) this.line(this.buffer.slice(0, -1), out);
    this.buffer = "";
    return out;
  }

  private line(line: string, out: SSEMessage[]) {
    if (line === "") {
      if (this.data.length > 0) out.push({ event: this.event || "message", data: this.data.join("\n") });
      this.event = "";
      this.data = [];
      return;
    }
    if (line.startsWith(":")) return; // comment / ping
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    // id / retry are irrelevant for a one-shot POST stream.
  }
}

export type AnalyseErrorKind = "http" | "not_sse" | "timeout" | "network" | "ended_early" | "aborted";

export class AnalyseError extends Error {
  constructor(public kind: AnalyseErrorKind, message: string) {
    super(message);
    this.name = "AnalyseError";
  }
}

export interface StreamOptions {
  /** Anonymous install UUID, sent as the X-Install-Id header. */
  installId: string;
  signal?: AbortSignal;
  connectMs: number;
  idleMs: number;
  totalMs: number;
  fetchImpl?: typeof fetch;
}

const CARD_NAMES = new Set(["item", "cost", "lock_in", "small_print", "company", "price_drift"]);
const CARD_STATES = new Set(["found", "estimated", "not_found", "n_a"]);

function toStreamCard(data: string): StreamCard | null {
  try {
    const v = JSON.parse(data) as Partial<StreamCard>;
    if (v && typeof v.card === "string" && CARD_NAMES.has(v.card) && typeof v.state === "string" && CARD_STATES.has(v.state)) {
      return { card: v.card, state: v.state, payload: v.payload ?? {} };
    }
  } catch {
    /* fall through */
  }
  console.warn("[smallprint] skipping malformed card event", data);
  return null;
}

/**
 * The body is rebuilt from an allowlist of page-data fields, so nothing about the user
 * (install_id, postcode, settings) can leak in through a stray property.
 */
export function buildBody(req: AnalyseBody): AnalyseBody {
  return {
    item: req.item,
    purchase_type_signals: req.purchase_type_signals,
    links: req.links,
    page_text_snippets: req.page_text_snippets,
    price_drift: req.price_drift,
  };
}

/** Headers sent with /analyse. The install UUID is the only user-related value. */
export function buildHeaders(url: string, installId: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    "X-Install-Id": installId,
  };
  // ngrok's free tier answers browsers with an HTML interstitial unless this is set.
  if (new URL(url).hostname.endsWith(".ngrok-free.app")) headers["ngrok-skip-browser-warning"] = "1";
  return headers;
}

/** Yields each card as it arrives; returns normally on `event: done`, throws AnalyseError otherwise. */
export async function* streamAnalyse(
  serverUrl: string,
  request: AnalyseBody,
  opts: StreamOptions,
): AsyncGenerator<StreamCard, void, undefined> {
  if (!opts.installId) throw new AnalyseError("http", "Missing install ID");

  const controller = new AbortController();
  let timeoutReason: string | null = null;
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const arm = (name: string, ms: number, reason: string) => {
    clearTimeout(timers.get(name));
    timers.set(name, setTimeout(() => {
      timeoutReason = reason;
      controller.abort();
    }, ms));
  };
  const disarm = (name: string) => clearTimeout(timers.get(name));

  const onExternalAbort = () => controller.abort();
  if (opts.signal?.aborted) controller.abort();
  opts.signal?.addEventListener("abort", onExternalAbort);

  const fail = (err: unknown): AnalyseError => {
    if (err instanceof AnalyseError) return err;
    if (timeoutReason) return new AnalyseError("timeout", timeoutReason);
    if (opts.signal?.aborted) return new AnalyseError("aborted", "Cancelled");
    return new AnalyseError("network", `Couldn't reach the SmallPrint server (${err instanceof Error ? err.message : String(err)})`);
  };

  arm("total", opts.totalMs, `The analysis took longer than ${opts.totalMs / 1000}s`);
  arm("connect", opts.connectMs, `The server didn't respond within ${opts.connectMs / 1000}s`);

  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const url = `${serverUrl.replace(/\/+$/, "")}/analyse`;
    const response = await (opts.fetchImpl ?? fetch)(url, {
      method: "POST",
      headers: buildHeaders(url, opts.installId),
      body: JSON.stringify(buildBody(request)),
      credentials: "omit", // no cookies for the backend's domain
      referrerPolicy: "no-referrer",
      signal: controller.signal,
    }).catch((e) => { throw fail(e); });
    disarm("connect");

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new AnalyseError("http", `Server error ${response.status}${detail ? `: ${detail.slice(0, 200)}` : ""}`);
    }
    const type = response.headers.get("content-type") ?? "";
    if (!type.includes("text/event-stream") || !response.body) {
      throw new AnalyseError("not_sse", `Expected an event stream but got "${type || "no content type"}". Is the server URL right?`);
    }

    reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SSEParser();
    arm("idle", opts.idleMs, `No data from the server for ${opts.idleMs / 1000}s`);

    while (true) {
      const { done, value } = await reader.read().catch((e) => { throw fail(e); });
      const messages = done ? [...parser.push(decoder.decode()), ...parser.end()] : parser.push(decoder.decode(value, { stream: true }));
      if (!done) arm("idle", opts.idleMs, `No data from the server for ${opts.idleMs / 1000}s`);

      for (const msg of messages) {
        if (msg.event === "done") return;
        if (msg.event === "card") {
          const card = toStreamCard(msg.data);
          if (card) yield card;
        }
      }
      if (done) throw new AnalyseError("ended_early", "The server closed the stream before sending all results");
    }
  } catch (err) {
    throw fail(err);
  } finally {
    for (const t of timers.values()) clearTimeout(t);
    opts.signal?.removeEventListener("abort", onExternalAbort);
    // Release the connection if we stopped early (done, error, or consumer broke out).
    controller.abort();
    reader?.cancel().catch(() => {});
  }
}
