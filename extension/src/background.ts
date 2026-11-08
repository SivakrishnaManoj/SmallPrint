import { getInstallId } from "./install";
import { tabKey, type DetectionMessage, type StoredDetection } from "./messages";
import type { Detection } from "./detect";
import { TITLES, tabState } from "./tabState";

// Clicking the toolbar icon opens the side panel.
const openOnClick = () => chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
openOnClick(); // onInstalled doesn't fire on every service-worker start

chrome.runtime.onInstalled.addListener(({ reason }) => {
  openOnClick();
  getInstallId().catch(console.error);
  // A side panel can only be opened from a user gesture, so first-run setup opens as a tab.
  if (reason === chrome.runtime.OnInstalledReason.INSTALL) chrome.runtime.openOptionsPage();
});

const ICON = (name: "color" | "grey") => ({ 16: `icons/${name}-16.png`, 32: `icons/${name}-32.png`, 48: `icons/${name}-48.png` });

/** Grey icon on pages with no purchase (W7); colour on a purchase; checkout pages also light the "£" badge (W3). */
async function setBadge(tabId: number, detection: Detection | null) {
  const state = tabState(detection);
  await chrome.action.setIcon({ tabId, path: ICON(state === "none" ? "grey" : "color") });
  await chrome.action.setBadgeText({ tabId, text: state === "checkout" ? "£" : "" });
  if (state === "checkout") await chrome.action.setBadgeBackgroundColor({ tabId, color: "#d97706" });
  await chrome.action.setTitle({ tabId, title: TITLES[state] });
}

chrome.runtime.onMessage.addListener((msg: DetectionMessage, sender) => {
  const tabId = sender.tab?.id;
  if (msg?.type !== "smallprint:detection" || tabId === undefined || sender.id !== chrome.runtime.id) return;
  if (sender.frameId !== 0) return; // top frame only
  const stored: StoredDetection = { url: msg.url, detection: msg.detection };
  chrome.storage.session.set({ [tabKey(tabId)]: stored }).catch(console.error);
  setBadge(tabId, msg.detection).catch(console.error);
});

// A new page load starts clean, so stale results never show (e.g. on pages the content script can't run in).
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status !== "loading" || !info.url) return;
  chrome.storage.session.remove(tabKey(tabId)).catch(() => {});
  setBadge(tabId, null).catch(() => {});
});
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(tabKey(tabId)).catch(() => {});
});
