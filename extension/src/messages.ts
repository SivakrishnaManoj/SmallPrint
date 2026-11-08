import type { Detection } from "./detect";
import type { PriceDriftData } from "./priceDrift";

export interface DetectionMessage {
  type: "smallprint:detection";
  url: string;
  detection: Detection;
}

export interface PriceDriftMessage {
  type: "smallprint:pricedrift";
  drift: PriceDriftData;
}

/** chrome.storage.session key holding the latest detection for a tab (kept in memory, cleared on browser exit). */
export const tabKey = (tabId: number) => `detection:${tabId}`;

export interface StoredDetection {
  url: string;
  detection: Detection;
}
