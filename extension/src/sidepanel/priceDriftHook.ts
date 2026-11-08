import { useEffect, useState } from "preact/hooks";
import { priceDriftKey, type PriceDriftData } from "../priceDrift";

/**
 * The locally computed price drift for the active tab.
 * Returns null when not on a checkout page or no first_seen was recorded.
 * This data never leaves the browser.
 */
export function usePriceDrift(tabId: number | null): PriceDriftData | null {
  const [drift, setDrift] = useState<PriceDriftData | null>(null);

  useEffect(() => {
    if (tabId === null || tabId < 0) {
      setDrift(null);
      return;
    }
    const key = priceDriftKey(tabId);
    chrome.storage.session.get(key).then((r) => {
      setDrift((r[key] as PriceDriftData | undefined) ?? null);
    }).catch(() => setDrift(null));

    const onChanged = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === "session" && key in changes) {
        setDrift((changes[key].newValue as PriceDriftData | undefined) ?? null);
      }
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, [tabId]);

  return drift;
}
