/**
 * When the content script re-runs detection and which results it reports. Pure, so it can be
 * tested without a browser.
 */
import type { Detection } from "./detect";

export interface Reported { url: string; detection: Detection }

/**
 * The detection to report now, or null to report nothing.
 *
 * - Same result as last time: nothing.
 * - Same URL, a purchase was reported and now there is none: nothing. Pages built with
 *   client-side frameworks remove and re-add their JSON-LD while they render (PrettyLittleThing
 *   drops it for about 2 s), so a "none" on the same URL is usually a re-render, not a new page.
 *   A real change of page comes with a new URL, which starts fresh.
 */
export function nextReport(prev: Reported | null, url: string, detection: Detection): Detection | null {
  if (prev && prev.url === url) {
    if (JSON.stringify(prev.detection) === JSON.stringify(detection)) return null;
    if (prev.detection.status === "purchase" && detection.status === "none") return null;
  }
  return detection;
}

/**
 * Debounce with a ceiling: `fn` runs `wait` ms after the last call, but never later than
 * `maxWait` ms after the first call in a burst. Some shops change their DOM many times a
 * second for as long as the page is open (Lakeland: about 22 changes a second, never quiet
 * for 600 ms), and a plain debounce would never fire there.
 */
export function debounceWithMaxWait(fn: () => void, wait: number, maxWait: number): (ms?: number) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  const run = () => {
    clearTimeout(timer);
    clearTimeout(deadline);
    timer = deadline = undefined;
    fn();
  };
  return (ms = wait) => {
    clearTimeout(timer);
    timer = setTimeout(run, ms);
    deadline ??= setTimeout(run, Math.max(ms, maxWait));
  };
}
