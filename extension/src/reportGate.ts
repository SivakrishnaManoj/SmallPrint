/**
 * When the content script re-runs detection and which results it reports. Pure apart from
 * timers, so it can be tested without a browser.
 */
import type { Detection } from "./detect";

/** How long a "none" must last, on a URL that showed a purchase, before it is reported. */
export const NONE_HOLD_MS = 5000;

export type Decision =
  | { send: Detection }
  | { recheckInMs: number } // hold: run detection again after this delay
  | null; // nothing to do

/**
 * Decides which detections to report. Client-side frameworks can remove and re-add JSON-LD
 * while they render (PrettyLittleThing drops it for about 2 s after load), so a "none" that
 * follows a purchase on the same URL is held. It is reported only if it lasts `holdMs`.
 * A real move away from the product (a single-page shop that keeps the URL, or that changed
 * the URL before it removed the old product) still ends in "none", just `holdMs` later.
 */
export class ReportGate {
  private last: { url: string; key: string; status: Detection["status"] } | null = null;
  private noneSince: number | null = null;

  constructor(private readonly holdMs = NONE_HOLD_MS) {}

  /** True while the last report for `url` was a purchase. */
  hasPurchase(url: string): boolean {
    return this.last?.url === url && this.last.status === "purchase";
  }

  decide(url: string, detection: Detection, now: number): Decision {
    const key = JSON.stringify(detection);
    if (this.last?.url === url && this.last.key === key) {
      this.noneSince = null;
      return null;
    }
    if (this.hasPurchase(url) && detection.status === "none") {
      this.noneSince ??= now;
      const left = this.holdMs - (now - this.noneSince);
      if (left > 0) return { recheckInMs: left };
    }
    this.noneSince = null;
    this.last = { url, key, status: detection.status };
    return { send: detection };
  }
}

export interface Debounced {
  (ms?: number): void;
  /** Drop any pending run and its deadline. */
  cancel(): void;
}

/**
 * Debounce with an optional ceiling: `fn` runs `wait` ms after the last call, and, while
 * `maxWait()` returns a number, no later than that many ms after the first call in a burst.
 * Some shops change their DOM many times a second (Lakeland: about 22 changes a second, never
 * quiet for 600 ms), and a plain debounce would never run there.
 */
export function debounceWithMaxWait(fn: () => void, wait: number, maxWait: () => number | null): Debounced {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => {
    clearTimeout(timer);
    clearTimeout(deadline);
    timer = deadline = undefined;
  };
  const run = () => {
    cancel();
    fn();
  };
  const call = (ms = wait) => {
    clearTimeout(timer);
    timer = setTimeout(run, ms);
    const max = maxWait();
    if (max === null) {
      clearTimeout(deadline);
      deadline = undefined;
    } else {
      deadline ??= setTimeout(run, Math.max(ms, max));
    }
  };
  return Object.assign(call, { cancel });
}
