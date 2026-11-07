/**
 * Settings live in chrome.storage.local under the same key panel/src/storage.ts uses.
 * SETUP_KEY records that the first-run form was completed or skipped.
 */
import { loadSettings, saveSettings } from "~panel/storage";
import type { Settings } from "~panel/types";

export const SETTINGS_KEY = "smallprint_settings";
export const SETUP_KEY = "setup_done";

export { loadSettings };

export async function isSetupDone(): Promise<boolean> {
  return (await chrome.storage.local.get(SETUP_KEY))[SETUP_KEY] === true;
}

/** Saves settings and marks first run as done (FirstRunForm already saves; this is idempotent). */
export async function completeSetup(settings: Settings): Promise<void> {
  await saveSettings(settings);
  await chrome.storage.local.set({ [SETUP_KEY]: true });
}

/** Calls `cb` when settings change in another extension page (e.g. the options tab). */
export function onSettingsChanged(cb: (s: Settings, setupDone: boolean) => void): () => void {
  const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area !== "local" || !(SETTINGS_KEY in changes || SETUP_KEY in changes)) return;
    Promise.all([loadSettings(), isSetupDone()]).then(([s, done]) => cb(s, done));
  };
  chrome.storage.onChanged.addListener(listener);
  return () => chrome.storage.onChanged.removeListener(listener);
}
