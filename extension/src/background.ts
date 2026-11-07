import { getInstallId } from "./install";

// Clicking the toolbar icon opens the side panel.
const openOnClick = () => chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
openOnClick(); // onInstalled doesn't fire on every service-worker start

chrome.runtime.onInstalled.addListener(({ reason }) => {
  openOnClick();
  getInstallId().catch(console.error);
  // A side panel can only be opened from a user gesture, so first-run setup opens as a tab.
  if (reason === chrome.runtime.OnInstalledReason.INSTALL) chrome.runtime.openOptionsPage();
});
