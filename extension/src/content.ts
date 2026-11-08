/**
 * Content script: runs detectPurchase on the page and reports the result to the service worker.
 * Read-only: it never clicks, fills in or changes anything. Nothing is sent off-device from here;
 * the request only reaches the backend when the user opens the side panel.
 */
import { detectPurchase } from "./detect";
import { isCheckout } from "./detect/checkout";
import { computeDrift, extractCheckoutFees, extractCheckoutSubtotal } from "./priceDrift";
import type { DetectionMessage, PriceDriftMessage } from "./messages";
import { debounceWithMaxWait, ReportGate } from "./reportGate";

const gate = new ReportGate();
let recheck: ReturnType<typeof setTimeout> | undefined;

function report() {
  clearTimeout(recheck);
  const url = location.href;
  const decision = gate.decide(url, detectPurchase(url, document), Date.now());
  if (!decision) return;
  if ("recheckInMs" in decision) {
    // A purchase just disappeared on this URL: check again before reporting "none".
    recheck = setTimeout(report, decision.recheckInMs);
    return;
  }
  const detection = decision.send;
  const msg: DetectionMessage = { type: "smallprint:detection", url, detection };
  chrome.runtime.sendMessage(msg).catch(() => {
    /* extension reloaded or service worker asleep; the next change re-sends */
  });
  reportPriceDrift(detection);
}

/** On product pages: record first_seen price. On checkout: compute drift. */
function reportPriceDrift(detection: ReturnType<typeof detectPurchase>) {
  const onCheckout = isCheckout(new URL(location.href), document);

  if (!onCheckout && detection.status === "purchase" && detection.request.item.price != null) {
    // First time we see a price — store it; background ignores if already set.
    chrome.storage.session.get(["pricedrift_firstseen_" + location.hostname]).then((r) => {
      const key = "pricedrift_firstseen_" + location.hostname;
      if (r[key] == null) chrome.storage.session.set({ [key]: detection.request.item.price });
    }).catch(() => {});
    return;
  }

  if (onCheckout) {
    const hostname = location.hostname;
    chrome.storage.session.get("pricedrift_firstseen_" + hostname).then((r) => {
      const firstSeen: number | null = r["pricedrift_firstseen_" + hostname] ?? null;
      if (firstSeen == null) return;
      const fees = extractCheckoutFees(document);
      const subtotal = extractCheckoutSubtotal(document);
      const drift = computeDrift(firstSeen, subtotal, fees);
      const msg: PriceDriftMessage = { type: "smallprint:pricedrift", drift };
      chrome.runtime.sendMessage(msg).catch(() => {});
    }).catch(() => {});
  }
}

report();

// Single-page shops change product without a page load (W7). Two signals, both debounced:
//  - the URL changes: history.pushState fires no event a content script can hear, so poll it;
//  - the DOM changes: a new product renders into the same page.
// Some pages never stop changing, so a plain debounce would never run. For the first 20 s
// after a page load or URL change, and until a purchase is found, a burst of changes still
// reports within 1.5 s. After that the plain debounce applies, so a busy page (live ticker,
// rotating ads) isn't scanned every 1.5 s for as long as it is open.
const BURST_CEILING_MS = 1500;
const BURST_WINDOW_MS = 20_000;
let pageStart = Date.now();
const soon = debounceWithMaxWait(report, 600, () =>
  Date.now() - pageStart < BURST_WINDOW_MS && !gate.hasPurchase(location.href) ? BURST_CEILING_MS : null,
);
new MutationObserver(() => soon()).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
let href = location.href;
const onUrlChange = () => {
  href = location.href;
  pageStart = Date.now();
  soon.cancel(); // a deadline left from the old page must not fire before the new one renders
  soon(300); // give the app a moment to render the new product
};
setInterval(() => {
  if (location.href !== href) onUrlChange();
}, 400);
addEventListener("popstate", () => (location.href !== href ? onUrlChange() : soon(300)));
