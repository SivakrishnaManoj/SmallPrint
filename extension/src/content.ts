/**
 * Content script: runs detectPurchase on the page and reports the result to the service worker.
 * Read-only: it never clicks, fills in or changes anything. Nothing is sent off-device from here;
 * the request only reaches the backend when the user opens the side panel.
 */
import { detectPurchase } from "./detect";
import { isCheckout } from "./detect/checkout";
import { computeDrift, extractCheckoutFees, extractCheckoutSubtotal } from "./priceDrift";
import type { DetectionMessage, PriceDriftMessage } from "./messages";
import { debounceWithMaxWait, nextReport, type Reported } from "./reportGate";

let last: Reported | null = null;

function report() {
  const url = location.href;
  const detection = nextReport(last, url, detectPurchase(url, document));
  if (!detection) return;
  last = { url, detection };
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
// Some pages never stop changing, so a burst of changes still reports within 1.5 s.
const soon = debounceWithMaxWait(report, 600, 1500);
new MutationObserver(() => soon()).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
let href = location.href;
setInterval(() => {
  if (location.href === href) return;
  href = location.href;
  soon(300); // give the app a moment to render the new product
}, 400);
addEventListener("popstate", () => soon(300));
