/**
 * Content script: runs detectPurchase on the page and reports the result to the service worker.
 * Read-only: it never clicks, fills in or changes anything. Nothing is sent off-device from here;
 * the request only reaches the backend when the user opens the side panel.
 */
import { detectPurchase } from "./detect";
import type { DetectionMessage } from "./messages";

let last = "";

function report() {
  const detection = detectPurchase(location.href, document);
  const key = JSON.stringify(detection);
  if (key === last) return;
  last = key;
  const msg: DetectionMessage = { type: "smallprint:detection", url: location.href, detection };
  chrome.runtime.sendMessage(msg).catch(() => {
    /* extension reloaded or service worker asleep; the next change re-sends */
  });
}

report();

// Single-page shops change product without a page load (W7). Two signals, both debounced:
//  - the URL changes: history.pushState fires no event a content script can hear, so poll it;
//  - the DOM changes: a new product renders into the same page.
let timer: ReturnType<typeof setTimeout> | undefined;
const soon = (ms: number) => {
  clearTimeout(timer);
  timer = setTimeout(report, ms);
};
new MutationObserver(() => soon(600)).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
let href = location.href;
setInterval(() => {
  if (location.href === href) return;
  href = location.href;
  soon(300); // give the app a moment to render the new product
}, 400);
addEventListener("popstate", () => soon(300));
