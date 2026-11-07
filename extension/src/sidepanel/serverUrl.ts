const KEY = "smallprint_server_url";

function storage(): chrome.storage.LocalStorageArea | null {
  try {
    return typeof chrome !== "undefined" && chrome.storage?.local ? chrome.storage.local : null;
  } catch {
    return null;
  }
}

export async function loadServerUrl(fallback: string): Promise<string> {
  try {
    const s = storage();
    if (s) return ((await s.get(KEY))[KEY] as string | undefined) || fallback;
    return localStorage.getItem(KEY) || fallback;
  } catch {
    return fallback;
  }
}

export function saveServerUrl(url: string): void {
  try {
    const s = storage();
    if (s) void s.set({ [KEY]: url });
    else localStorage.setItem(KEY, url);
  } catch {
    /* ignore */
  }
}
