/**
 * W4 · T&C fetcher: fetch the page's T&C links from the user's browser and attach them
 * to the /analyse request as `terms` (contracts/request.schema.json, terms_document).
 *
 * - HTML or plain-text pages are sent as `text` (the backend strips the HTML).
 * - PDFs are sent as `pdf_b64`.
 * - Anything that fails (HTTP error, network error, timeout, too big, wrong type) is sent as
 *   `fetch_failed: true` with an `error`, so the backend falls back to search (S6).
 *
 * A plain fetch: the browser's own User-Agent, no retries with other headers, no bot evasion.
 * Cookies are not sent (`credentials: "omit"`), so the T&C site doesn't learn who the user is.
 */
import type { TermsDocument, TermsKind } from "~panel/types";

export interface TermsLink {
  url: string;
  kind: string;
}

/** Which link kinds are worth fetching, most useful first. Privacy policies etc. are skipped. */
export const FETCH_PRIORITY: TermsKind[] = ["terms", "contract_summary", "subscription", "cancel", "price_guide", "returns", "warranty"];

export const LIMITS = {
  maxDocuments: 3,
  timeoutMs: 10_000,
  /** contracts: text maxLength 500,000 characters; longer pages are cut, not dropped. */
  maxTextChars: 500_000,
  /** contracts: pdf_b64 maxLength 20,000,000 characters of base64 ≈ 15 MB of PDF. */
  maxPdfBytes: 15_000_000,
};

export interface FetchOptions {
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/** The links to fetch: known T&C kinds only, de-duplicated, best first, at most 3. */
export function pickTermsLinks(links: TermsLink[]): { url: string; kind: TermsKind }[] {
  const seen = new Set<string>();
  return links
    .filter((l): l is { url: string; kind: TermsKind } => FETCH_PRIORITY.includes(l.kind as TermsKind) && /^https?:/i.test(l.url))
    .sort((a, b) => FETCH_PRIORITY.indexOf(a.kind) - FETCH_PRIORITY.indexOf(b.kind))
    .filter((l) => !seen.has(l.url) && seen.add(l.url))
    .slice(0, LIMITS.maxDocuments);
}

export async function fetchTermsDocuments(links: TermsLink[], opts: FetchOptions = {}): Promise<TermsDocument[]> {
  return Promise.all(pickTermsLinks(links).map((l) => fetchTermsDocument(l.url, l.kind, opts)));
}

const failed = (url: string, kind: TermsKind, error: string): TermsDocument => ({ url, kind, fetch_failed: true, error });

export async function fetchTermsDocument(url: string, kind: TermsKind, opts: FetchOptions = {}): Promise<TermsDocument> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, opts.timeoutMs ?? LIMITS.timeoutMs);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener("abort", onAbort);

  try {
    const res = await (opts.fetchImpl ?? fetch)(url, {
      method: "GET",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      redirect: "follow",
      signal: controller.signal,
    });
    if (!res.ok) return failed(url, kind, `HTTP ${res.status}`);

    const type = (res.headers.get("content-type") ?? "").toLowerCase();
    const declared = Number(res.headers.get("content-length") ?? "");
    if (declared > Math.max(LIMITS.maxPdfBytes, LIMITS.maxTextChars * 4)) return failed(url, kind, `Too large (${declared} bytes)`);

    const bytes = new Uint8Array(await res.arrayBuffer());
    if (bytes.length === 0) return failed(url, kind, "Empty response");

    if (type.includes("application/pdf") || isPdf(bytes)) {
      if (bytes.length > LIMITS.maxPdfBytes) return failed(url, kind, `PDF too large (${bytes.length} bytes)`);
      return { url, kind, pdf_b64: toBase64(bytes) };
    }
    if (type && !/text\/html|text\/plain|application\/xhtml\+xml/.test(type)) {
      return failed(url, kind, `Unsupported content type: ${type.split(";")[0]}`);
    }
    const text = decode(bytes, type).slice(0, LIMITS.maxTextChars);
    if (!text.trim()) return failed(url, kind, "Empty response");
    return { url, kind, text };
  } catch (err) {
    if (timedOut) return failed(url, kind, `Timed out after ${(opts.timeoutMs ?? LIMITS.timeoutMs) / 1000}s`);
    if (opts.signal?.aborted) throw err; // the whole analysis was cancelled
    return failed(url, kind, `Network error: ${err instanceof Error ? err.message : String(err)}`);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

/** PDFs start with "%PDF-" (sometimes after a little junk; check the first 1 KB). */
export function isPdf(bytes: Uint8Array): boolean {
  const head = new TextDecoder("latin1").decode(bytes.subarray(0, 1024));
  return head.includes("%PDF-");
}

function decode(bytes: Uint8Array, type: string): string {
  const charset = type.match(/charset=([\w-]+)/)?.[1];
  try {
    return new TextDecoder(charset || "utf-8").decode(bytes);
  } catch {
    return new TextDecoder("utf-8").decode(bytes);
  }
}

/** Base64 in chunks: String.fromCharCode(...bytes) on a whole 15 MB PDF would overflow the call stack. */
export function toBase64(bytes: Uint8Array): string {
  let out = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    out += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(out);
}
