/** Settings wrapper: chrome.storage.local when available, else localStorage. */
import type { Settings } from "./types";
import { DEFAULT_SETTINGS } from "./types";

const KEY = "smallprint_settings";

declare const chrome: typeof globalThis extends { chrome: infer C } ? C : {
  storage?: {
    local?: {
      get(key: string, cb: (result: Record<string, unknown>) => void): void;
      set(obj: Record<string, unknown>, cb?: () => void): void;
    };
  };
};

function hasChromeStorage(): boolean {
  try {
    return typeof chrome !== "undefined" && !!chrome.storage?.local;
  } catch {
    return false;
  }
}

export async function loadSettings(): Promise<Settings> {
  try {
    if (hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage!.local!.get(KEY, (result: Record<string, unknown>) => {
          resolve((result[KEY] as Settings) ?? DEFAULT_SETTINGS);
        });
      });
    }
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Settings) : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export async function saveSettings(settings: Settings): Promise<void> {
  try {
    if (hasChromeStorage()) {
      return new Promise((resolve) => {
        chrome.storage!.local!.set({ [KEY]: settings }, resolve);
      });
    }
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // ignore storage errors
  }
}

