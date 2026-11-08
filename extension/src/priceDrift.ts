/**
 * V3 · Price drift: compare the first-seen price with the checkout price.
 *
 * All data stays in chrome.storage.session and never reaches the backend.
 * This module contains only pure logic (no Chrome API calls) so it can run
 * in Node tests as well as the extension.
 */
import { parsePrice, textOf } from "./detect/text";

export interface AddedFee {
  label: string;
  amount: number;
}

export interface PriceDriftData {
  first_seen: number | null;
  at_checkout: number | null;
  added: AddedFee[];
}

export const priceDriftKey = (tabId: number) => `pricedrift:${tabId}`;

// ---------------------------------------------------------------------------
// Checkout price extraction
// ---------------------------------------------------------------------------

/** Amazon order-summary row selectors (subtotal table, gift-wrap, etc.) */
const AMAZON_ROW_SEL = [
  "#subtotals-marketplace-table .a-row",
  ".subtotals-gift-wrap .a-row",
  ".subtotals-marketplace-spc-offer .a-row",
  "#order-summary .a-row",
].join(", ");

/** Labels that indicate a base item price rather than an added fee. */
const BASE_LABELS = /\b(item|subtotal|price|merchandise|product)\b/i;

/** Labels that indicate a fee added on top of the base price. */
const FEE_LABELS = /\b(delivery|shipping|postage|handling|import|fee|tax|vat|surcharge|service)\b/i;

function parseAmount(text: string): number | null {
  const p = parsePrice(text);
  return p !== null && p > 0 ? p : null;
}

/**
 * Extract named fees from an Amazon or generic checkout page.
 * Only fees whose labels match FEE_LABELS are returned.
 * Returns an empty array when nothing can be parsed.
 */
export function extractCheckoutFees(doc: Document): AddedFee[] {
  const fees: AddedFee[] = [];

  // --- Amazon structured table ---
  const rows = doc.querySelectorAll(AMAZON_ROW_SEL);
  if (rows.length) {
    for (const row of rows) {
      const cells = row.querySelectorAll("span, td, div");
      if (cells.length < 2) continue;
      const label = textOf(cells[0] as HTMLElement).trim();
      const amountText = textOf(cells[cells.length - 1] as HTMLElement);
      if (!label || BASE_LABELS.test(label)) continue;
      if (!FEE_LABELS.test(label)) continue;
      const amount = parseAmount(amountText);
      if (amount !== null) fees.push({ label: label.replace(/:$/, "").trim(), amount });
    }
    return fees;
  }

  // --- Generic: scan visible text for fee-like lines ---
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent?.trim() ?? "";
    const m = text.match(/^(.{3,40}?)[\s:·•]+£\s?(\d[\d,]*(?:\.\d{1,2})?)$/);
    if (!m) continue;
    const label = m[1].trim();
    const amount = parseAmount(m[2]);
    if (amount === null || BASE_LABELS.test(label)) continue;
    if (FEE_LABELS.test(label)) fees.push({ label, amount });
  }
  return fees;
}

/**
 * Extract the checkout subtotal (the item price before fees) from the page.
 * Returns null if nothing can be parsed.
 */
export function extractCheckoutSubtotal(doc: Document): number | null {
  // Amazon: "Items (N): £XX.XX" in the order summary
  const amazonItems = doc.querySelector(
    "#subtotals-marketplace-table .a-row:first-child span:last-child, " +
    ".order-summary-items-subtotal span:last-child",
  );
  if (amazonItems) {
    const p = parseAmount(textOf(amazonItems as HTMLElement));
    if (p !== null) return p;
  }

  // Generic: first occurrence of a price that isn't inside a nav/header/footer
  const main = doc.querySelector("main, [role=main], #main, .main") ?? doc.body;
  const walker = doc.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent?.trim() ?? "";
    const m = text.match(/^£\s?(\d[\d,]*(?:\.\d{1,2})?)$/);
    if (!m) continue;
    const p = parseAmount(m[1]);
    if (p !== null) return p;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Drift computation
// ---------------------------------------------------------------------------

/**
 * Compute the price-drift card payload given a stored first_seen price and
 * the current checkout state. Pure — no side effects.
 */
export function computeDrift(
  firstSeen: number,
  subtotal: number | null,
  fees: AddedFee[],
): PriceDriftData {
  const atCheckout =
    subtotal !== null
      ? subtotal + fees.reduce((s, f) => s + f.amount, 0)
      : firstSeen + fees.reduce((s, f) => s + f.amount, 0);

  // If no fees were detected but the checkout price differs from first_seen,
  // show the difference as a single unlabelled added amount.
  const finalFees = [...fees];
  if (finalFees.length === 0 && subtotal !== null && subtotal !== firstSeen) {
    const diff = +(atCheckout - firstSeen).toFixed(2);
    if (diff > 0) finalFees.push({ label: "Added at checkout", amount: diff });
  }

  return {
    first_seen: firstSeen,
    at_checkout: +atCheckout.toFixed(2),
    added: finalFees,
  };
}
