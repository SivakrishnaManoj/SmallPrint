/**
 * Anonymous install ID: a random UUID created once and kept in chrome.storage.local.
 * It is the only thing about the user that leaves the browser (as the X-Install-Id header).
 */
const KEY = "install_id";

let pending: Promise<string> | null = null;

export function getInstallId(): Promise<string> {
  pending ??= (async () => {
    const stored = (await chrome.storage.local.get(KEY))[KEY];
    if (typeof stored === "string" && stored) return stored;
    const id = crypto.randomUUID();
    await chrome.storage.local.set({ [KEY]: id });
    return id;
  })().catch((err) => {
    pending = null;
    throw err;
  });
  return pending;
}
