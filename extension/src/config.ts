import type { AnalyseRequest } from "~panel/types";
import sodastream from "~fixtures/requests/req_sodastream.json";

/** What goes in the POST body: page data only. Nothing about the user. */
export type AnalyseBody = Omit<AnalyseRequest, "install_id">;

/** Backend base URL. Override at build time with VITE_SERVER_URL, or at runtime in the panel. */
export const DEFAULT_SERVER_URL: string = import.meta.env.VITE_SERVER_URL ?? "https://smallprint-production.up.railway.app";

/** H1: the panel sends a canned request instead of scraping the page. */
// The fixture still carries a test install_id for the backend's own tests; drop it.
const { install_id: _unused, ...cannedBody } = sodastream as AnalyseRequest;
export const CANNED_REQUEST: AnalyseBody = cannedBody;

export const TIMEOUTS = {
  /** No response headers within this time → give up. */
  connectMs: 10_000,
  /** No bytes (cards or keep-alive pings) for this long → give up. */
  idleMs: 20_000,
  /** Hard cap on the whole stream, so pings alone can't keep the spinner up. */
  totalMs: 60_000,
};
