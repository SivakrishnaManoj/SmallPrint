/**
 * The exit fee arrives as quoted text ("£215", "Up to £215", "Remaining monthly payments").
 * The cost model needs a number. Only an exact single amount becomes one: "Up to £215" or a
 * formula is not a known fee, so it returns null and no "if you leave" total is shown.
 */
export function parseExitFee(text: string | null | undefined): number | null {
  const m = text?.trim().match(/^£\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$/);
  return m ? Number(m[1].replace(/,/g, "")) : null;
}
