/**
 * Behaviour of the lifetime cost model, tested through `lifetimeCost` only.
 * Expected totals are worked out by hand in the comments, not recomputed in code.
 */
import { describe, expect, it } from "vitest";
import type { CostStream } from "../types";
import { CostModelError, lifetimeCost } from "./lifetimeCost";

const EVIDENCE = { quote: "q", url: "https://example.com/terms" };

function recurring(amount: number, from_month = 1, to_month?: number, label = "Monthly fee"): CostStream {
  return { label, type: "recurring", amount, from_month, ...(to_month === undefined ? {} : { to_month }), evidence: EVIDENCE };
}

function oneOff(amount: number, label = "Setup fee"): CostStream {
  return { label, type: "one_off", amount, evidence: EVIDENCE };
}

function stepChange(amount: number, month: number, label = "Annual price rise"): CostStream {
  return { label, type: "step_change", amount, month, evidence: EVIDENCE };
}

function usage(unit_price: number, low: number, mid: number, high: number, label = "CO2 cylinder"): CostStream {
  return { label, type: "usage", unit_price, units_per_month: { low, mid, high }, evidence: EVIDENCE };
}

describe("lifetimeCost", () => {
  it("charges a recurring fee every month of the horizon", () => {
    const result = lifetimeCost([recurring(9.99)], 12);

    // 12 x 9.99 = 119.88
    expect(result.total).toEqual({ low: 119.88, mid: 119.88, high: 119.88 });
  });

  it("charges a setup fee once", () => {
    const result = lifetimeCost([oneOff(49.0), recurring(30.0)], 12);

    // 49.00 once + 12 x 30.00 = 409.00
    expect(result.total?.mid).toBe(409.0);
  });

  it("charges a trial price and then the full price", () => {
    const streams = [
      recurring(1.0, 1, 3, "Introductory price"),
      recurring(9.99, 4, undefined, "Full price"),
    ];

    const result = lifetimeCost(streams, 12);

    // 3 x 1.00 + 9 x 9.99 = 3.00 + 89.91 = 92.91
    expect(result.total?.mid).toBe(92.91);
  });

  it("applies an annual rise from month 13", () => {
    const result = lifetimeCost([recurring(30.0, 1, 24), stepChange(3.0, 13)], 24);

    // months 1-12: 12 x 30.00 = 360.00; months 13-24: 12 x 33.00 = 396.00; total 756.00
    expect(result.total?.mid).toBe(756.0);
  });

  it("ignores a month-13 rise on a 12 month horizon", () => {
    const result = lifetimeCost([recurring(30.0, 1, 24), stepChange(3.0, 13)], 12);

    // 12 x 30.00 = 360.00
    expect(result.total?.mid).toBe(360.0);
  });

  it("does not add a rise after the recurring fee has ended", () => {
    const result = lifetimeCost([recurring(10.0, 1, 6), stepChange(5.0, 8)], 12);

    // 6 x 10.00 = 60.00, and the rise has no fee to apply to
    expect(result.total?.mid).toBe(60.0);
  });

  it("gives a low, mid and high range for usage", () => {
    const result = lifetimeCost([oneOff(89.99, "Machine"), usage(14.99, 0.5, 1.0, 2.0)], 12);

    // machine 89.99 + cylinders: low 6 x 14.99 = 89.94, mid 12 x 14.99 = 179.88, high 24 x 14.99 = 359.76
    expect(result.total).toEqual({ low: 179.93, mid: 269.87, high: 449.75 });
  });

  it("scales usage with the 24 month horizon", () => {
    const result = lifetimeCost([oneOff(89.99, "Machine"), usage(14.99, 0.5, 1.0, 2.0)], 24);

    // machine 89.99 + cylinders: low 179.88, mid 359.76, high 719.52
    expect(result.total).toEqual({ low: 269.87, mid: 449.75, high: 809.51 });
  });

  it("charges usage only inside its month window", () => {
    const stream: CostStream = { ...usage(10.0, 1, 1, 1, "Refill"), from_month: 1, to_month: 6 };

    const result = lifetimeCost([stream], 12);

    // 6 x 10.00 x 1 unit = 60.00
    expect(result.total?.mid).toBe(60.0);
  });

  it("adds the exit fee when leaving before the minimum term ends", () => {
    const result = lifetimeCost([recurring(32.99, 1, 24)], 12, { exitFee: 215.0, minTermMonths: 24 });

    // staying 12 months: 12 x 32.99 = 395.88; leaving then adds 215.00 = 610.88
    expect(result.total?.mid).toBe(395.88);
    expect(result.totalIfLeaving?.mid).toBe(610.88);
  });

  it("adds no exit fee when the horizon reaches the end of the minimum term", () => {
    const result = lifetimeCost([recurring(32.99, 1, 24)], 24, { exitFee: 215.0, minTermMonths: 24 });

    // 24 x 32.99 = 791.76, and the contract has run its course
    expect(result.total?.mid).toBe(791.76);
    expect(result.totalIfLeaving?.mid).toBe(791.76);
  });

  it("reports state found when every number comes from the page", () => {
    expect(lifetimeCost([recurring(9.99)], 12).state).toBe("found");
  });

  it("reports state estimated when a usage stream is included", () => {
    expect(lifetimeCost([usage(14.99, 0.5, 1.0, 2.0)], 12).state).toBe("estimated");
  });

  it("reports state not_found when there are no cost streams", () => {
    const result = lifetimeCost([], 12);

    expect(result.state).toBe("not_found");
    expect(result.total).toBeNull();
    expect(result.totalIfLeaving).toBeNull();
  });

  it("rejects a horizon other than 12 or 24 months", () => {
    expect(() => lifetimeCost([recurring(9.99)], 18 as unknown as 12)).toThrow(CostModelError);
    expect(() => lifetimeCost([recurring(9.99)], 18 as unknown as 12)).toThrow(/horizon/);
  });

  it("rejects a stream without an amount instead of counting it as zero", () => {
    const stream = { label: "Monthly fee", type: "recurring", evidence: EVIDENCE } as CostStream;

    expect(() => lifetimeCost([stream], 12)).toThrow(CostModelError);
    expect(() => lifetimeCost([stream], 12)).toThrow(/Monthly fee/);
  });
});
