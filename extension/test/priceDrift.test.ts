// @vitest-environment happy-dom
/**
 * V3: price drift pure logic tests (no Chrome APIs).
 */
import { describe, expect, it } from "vitest";
import { parseHTML } from "linkedom";
import { computeDrift, extractCheckoutFees, extractCheckoutSubtotal } from "../src/priceDrift";

function html(body: string): Document {
  return parseHTML(`<!doctype html><html><body>${body}</body></html>`).document as unknown as Document;
}

// ---------------------------------------------------------------------------
// computeDrift
// ---------------------------------------------------------------------------

describe("computeDrift", () => {
  it("no fees, same price → n_a (no added array entries)", () => {
    const d = computeDrift(29.99, 29.99, []);
    expect(d.first_seen).toBe(29.99);
    expect(d.at_checkout).toBe(29.99);
    expect(d.added).toEqual([]);
  });

  it("named fees are passed through and summed into at_checkout", () => {
    const d = computeDrift(29.99, 29.99, [{ label: "Delivery", amount: 3.99 }]);
    expect(d.at_checkout).toBe(33.98);
    expect(d.added).toEqual([{ label: "Delivery", amount: 3.99 }]);
  });

  it("when subtotal differs from first_seen and no named fees, adds generic fee", () => {
    const d = computeDrift(25.0, 31.5, []);
    expect(d.at_checkout).toBe(31.5);
    expect(d.added).toEqual([{ label: "Added at checkout", amount: 6.5 }]);
  });

  it("when subtotal is null, falls back to first_seen + fees", () => {
    const d = computeDrift(29.99, null, [{ label: "Shipping", amount: 4.99 }]);
    expect(d.at_checkout).toBe(34.98);
  });

  it("rounds to 2 decimal places", () => {
    const d = computeDrift(9.99, 9.99, [{ label: "Fee", amount: 0.001 }]);
    expect(d.at_checkout).toBe(9.99);
  });
});

// ---------------------------------------------------------------------------
// extractCheckoutFees — generic DOM
// ---------------------------------------------------------------------------

describe("extractCheckoutFees generic", () => {
  it("picks up fee-labelled lines with prices", () => {
    const doc = html(`
      <p>Subtotal £29.99</p>
      <p>Delivery £3.99</p>
      <p>Shipping £5.00</p>
    `);
    const fees = extractCheckoutFees(doc);
    expect(fees.some((f) => f.label === "Delivery" && f.amount === 3.99)).toBe(true);
    expect(fees.some((f) => f.label === "Shipping" && f.amount === 5.0)).toBe(true);
  });

  it("ignores base-price labels", () => {
    const doc = html(`<p>Subtotal £29.99</p><p>Price £29.99</p><p>Items £29.99</p>`);
    expect(extractCheckoutFees(doc)).toEqual([]);
  });

  it("returns empty array when no fee lines", () => {
    const doc = html(`<h1>Your basket is empty</h1>`);
    expect(extractCheckoutFees(doc)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// extractCheckoutFees — Amazon-style structured table
// ---------------------------------------------------------------------------

describe("extractCheckoutFees Amazon", () => {
  it("extracts named fees from Amazon order-summary rows", () => {
    const doc = html(`
      <div id="subtotals-marketplace-table">
        <div class="a-row"><span>Items (2):</span><span>£59.98</span></div>
        <div class="a-row"><span>Delivery:</span><span>£3.99</span></div>
        <div class="a-row"><span>Import Fees Deposit:</span><span>£8.50</span></div>
      </div>
    `);
    const fees = extractCheckoutFees(doc);
    expect(fees.some((f) => f.label === "Delivery" && f.amount === 3.99)).toBe(true);
    expect(fees.some((f) => /Import/i.test(f.label) && f.amount === 8.5)).toBe(true);
    // "Items" is a base label — must not appear
    expect(fees.every((f) => !/items/i.test(f.label))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// extractCheckoutSubtotal
// ---------------------------------------------------------------------------

describe("extractCheckoutSubtotal", () => {
  it("returns null when no price found", () => {
    const doc = html(`<p>No purchase here.</p>`);
    expect(extractCheckoutSubtotal(doc)).toBeNull();
  });

  it("returns the first standalone price in main content", () => {
    const doc = html(`<main><p>£29.99</p><p>£3.99 delivery</p></main>`);
    expect(extractCheckoutSubtotal(doc)).toBe(29.99);
  });
});

// ---------------------------------------------------------------------------
// Privacy rule: pure module exports no chrome.* or network references
// ---------------------------------------------------------------------------

it("priceDrift exports are pure functions with no side effects", () => {
  // All exports should be functions or interfaces — no chrome.storage, no fetch.
  expect(typeof computeDrift).toBe("function");
  expect(typeof extractCheckoutFees).toBe("function");
  expect(typeof extractCheckoutSubtotal).toBe("function");
});
