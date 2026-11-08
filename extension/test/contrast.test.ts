/**
 * Badge text must meet WCAG AA for small text (4.5:1) on its badge background,
 * in light and dark mode. Reads the real tokens from panel/src/index.css.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "../../panel/src/index.css"), "utf8");
const block = (from: number) => css.slice(css.indexOf("{", from) + 1, css.indexOf("}", from));
const tokens = (src: string) => Object.fromEntries([...src.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));

const light = tokens(block(css.indexOf(":root")));
const dark = { ...light, ...tokens(block(css.indexOf(":root", css.indexOf("prefers-color-scheme: dark")))) };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// The pairs .badge--* actually use (text on background).
const BADGES: [string, string, string][] = [
  ["found", "found-ink", "found-bg"],
  ["estimated", "estimated-ink", "estimated-bg"],
  ["not found / n/a", "muted-ink", "muted-ink-bg"],
];

describe("badge contrast (WCAG AA, 4.5:1)", () => {
  for (const [mode, t] of [["light", light], ["dark", dark]] as const) {
    for (const [name, ink, bg] of BADGES) {
      it(`${mode} · ${name}`, () => {
        expect(t[ink], `--${ink} missing`).toBeTruthy();
        expect(contrast(t[ink], t[bg])).toBeGreaterThanOrEqual(4.5);
      });
    }
  }

  it("the badges really use the ink tokens", () => {
    expect(css).toMatch(/\.badge--found\s*{[^}]*color:\s*var\(--found-ink\)/);
    expect(css).toMatch(/\.badge--estimated\s*{[^}]*color:\s*var\(--estimated-ink\)/);
    expect(css).toMatch(/\.badge--na\s*{[^}]*color:\s*var\(--muted-ink\)/);
    expect(css).not.toMatch(/\.card--n_a\s*{[^}]*opacity/);
  });
});
