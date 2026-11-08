import { describe, expect, it } from "vitest";
import { TITLES, tabState } from "../src/tabState";
import type { Detection } from "../src/detect";

const purchase = { status: "purchase", detector: "jsonld", checkout: false, request: {} } as unknown as Detection;

describe("toolbar state (W7)", () => {
  it("greys out on pages with no purchase, and when nothing has reported", () => {
    expect(tabState({ status: "none", checkout: false })).toBe("none");
    expect(tabState(null)).toBe("none");
    expect(TITLES.none).toMatch(/no purchase detected/);
  });
  it("colour on a purchase; checkout wins, even without product details", () => {
    expect(tabState(purchase)).toBe("purchase");
    expect(tabState({ ...purchase, checkout: true } as Detection)).toBe("checkout");
    expect(tabState({ status: "none", checkout: true })).toBe("checkout");
  });
});
