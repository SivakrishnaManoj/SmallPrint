import type { Detection } from "./detect";

/** What the toolbar button shows for a tab. */
export type TabState = "none" | "purchase" | "checkout";

export const TITLES: Record<TabState, string> = {
  none: "SmallPrint: no purchase detected on this page",
  purchase: "SmallPrint: purchase found. Open to see the real cost and small print.",
  checkout: "SmallPrint: checkout page. Open to see the real cost and small print.",
};

export function tabState(detection: Detection | null): TabState {
  if (detection?.checkout) return "checkout";
  return detection?.status === "purchase" ? "purchase" : "none";
}
