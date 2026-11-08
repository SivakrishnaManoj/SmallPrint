// @vitest-environment happy-dom
/**
 * W5: cost, lock-in and small-print cards, and statutory rights.
 * Done when switching horizon updates the total instantly, and every found value shows its quote and link.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/preact";
import { CostCard } from "./CostCard";
import { LockInCard } from "./LockInCard";
import { SmallPrintCard } from "./SmallPrintCard";
import { StatutoryRights } from "./StatutoryRights";
import { parseExitFee } from "../cost/exitFee";
import type { AnalyseResult, CardState, CostStream } from "../types";
import broadband from "../../../fixtures/broadband.json";
import sodastream from "../../../fixtures/sodastream.json";
import netflix from "../../../fixtures/netflix.json";

afterEach(cleanup);

const FIXTURES = { broadband, sodastream, netflix } as unknown as Record<string, AnalyseResult>;
const STATES: CardState[] = ["found", "estimated", "not_found", "n_a"];
const total = () => screen.getByTestId("cost-total").textContent ?? "";

/** Every row has a verbatim quote and a working link. */
function expectQuoteAndLink(rows: HTMLElement[]) {
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    expect(row.querySelector("blockquote")?.textContent?.trim()).toBeTruthy();
    expect(row.querySelector("a.source-link")?.getAttribute("href")).toMatch(/^https:\/\//);
  }
}

describe("cost card", () => {
  it("switching horizon updates the total instantly (no network, no waiting)", () => {
    render(<CostCard costStreams={FIXTURES.broadband.cost_streams} state="found" horizon={12} />);
    // 12 × £32.99; the £2.50 rise starts in month 13.
    expect(total()).toContain("£395.88");
    fireEvent.click(screen.getByRole("button", { name: "24 months" }));
    // 24 × £32.99 + 12 × £2.50
    expect(total()).toContain("£821.76");
    fireEvent.click(screen.getByRole("button", { name: "12 months" }));
    expect(total()).toContain("£395.88");
  });

  it("starts at the user's default horizon and follows it when settings change", () => {
    const { rerender } = render(<CostCard costStreams={FIXTURES.netflix.cost_streams} state="found" horizon={24} />);
    expect(total()).toMatch(/24 months: £119\.76/);
    rerender(<CostCard costStreams={FIXTURES.netflix.cost_streams} state="found" horizon={12} />);
    expect(total()).toMatch(/12 months: £59\.88/);
  });

  it("shows usage estimates as a range with their source, and marks the card estimated", () => {
    render(<CostCard costStreams={FIXTURES.sodastream.cost_streams} state="found" horizon={12} />);
    // £89.99 + £14.99 × 0.5…2 cylinders × 12 months
    expect(total()).toContain("£179.93 – £449.75");
    expect(total()).toContain("estimated range");
    expect(screen.getByText("Estimated")).toBeTruthy();
    const usage = screen.getAllByTestId("cost-stream").find((r) => r.textContent?.includes("CO2 cylinder"))!;
    expect(usage.textContent).toContain("£7.50 – £29.98 a month (estimate)");
    expectQuoteAndLink([usage]);
  });

  it("every cost stream shows its quote and link", () => {
    for (const f of Object.values(FIXTURES)) {
      render(<CostCard costStreams={f.cost_streams} state={f.card_states.cost} horizon={12} />);
      expectQuoteAndLink(screen.getAllByTestId("cost-stream"));
      cleanup();
    }
  });

  it("quote or null: a stream without its quote is neither shown nor counted", () => {
    const streams: CostStream[] = [
      ...FIXTURES.netflix.cost_streams,
      { label: "Unverified add-on", type: "recurring", amount: 100, evidence: { quote: null, url: "https://x.example" } },
    ];
    render(<CostCard costStreams={streams} state="found" horizon={12} />);
    expect(total()).toContain("£59.88");
    expect(screen.queryByText("Unverified add-on")).toBeNull();
    expect(screen.getByText(/1 cost was found without a quote/)).toBeTruthy();
  });

  it("adds the exit fee only when it is an exact amount and leaving breaks the minimum term", () => {
    const lockIn = { ...FIXTURES.broadband.lock_in, exit_fee: "£215" };
    render(<CostCard costStreams={FIXTURES.broadband.cost_streams} state="found" horizon={12} lockIn={lockIn} />);
    expect(screen.getByTestId("cost-if-leaving").textContent).toContain("£610.88");
    fireEvent.click(screen.getByRole("button", { name: "24 months" }));
    expect(screen.queryByTestId("cost-if-leaving")).toBeNull(); // the 24-month term is served
    cleanup();
    // "Up to £215" isn't a known fee, so no total is invented from it.
    render(<CostCard costStreams={FIXTURES.broadband.cost_streams} state="found" horizon={12} lockIn={FIXTURES.broadband.lock_in} />);
    expect(screen.queryByTestId("cost-if-leaving")).toBeNull();
  });

  it("an unreadable stream shows not found rather than a wrong total", () => {
    const bad = [{ label: "Broken", type: "recurring", evidence: { quote: "q", url: "https://x.example" } }] as CostStream[];
    render(<CostCard costStreams={bad} state="found" horizon={12} />);
    expect(screen.getByText("Cost information wasn't found for this item.")).toBeTruthy();
  });
});

describe("lock-in card", () => {
  it("every value shows its own quote and link", () => {
    render(<LockInCard lockIn={FIXTURES.broadband.lock_in} state="found" />);
    const rows = screen.getAllByTestId("lock-in-row");
    expect(rows.map((r) => r.querySelector(".lock-in__label")?.textContent)).toEqual([
      "Minimum term", "Exit fee", "Notice to cancel", "Auto-renews", "How to cancel",
    ]);
    expectQuoteAndLink(rows);
    const term = rows[0];
    expect(within(term).getByText("24 months")).toBeTruthy();
    expect(term.querySelector("blockquote")?.textContent).toContain("24-month contract");
  });

  it("quote or null: a value with no evidence entry is not shown", () => {
    const lockIn = { ...FIXTURES.netflix.lock_in, notice_days: 30 }; // no evidence for notice_days
    render(<LockInCard lockIn={lockIn} state="found" />);
    expect(screen.queryByText("Notice to cancel")).toBeNull();
    expect(screen.getByText("How to cancel")).toBeTruthy();
  });
});

describe("small print card", () => {
  it("every clause shows its quote and link, without a stray colon", () => {
    render(<SmallPrintCard items={FIXTURES.sodastream.small_print} state="found" />);
    const rows = screen.getAllByTestId("small-print-row");
    expectQuoteAndLink(rows);
    expect(rows[0].textContent).not.toMatch(/^Returns window:/);
    expect(within(rows[0]).getByText("30 days")).toBeTruthy();
  });

  it("drops clauses without a quote", () => {
    render(<SmallPrintCard items={[{ field: "Warranty", value: "2 years", quote: null, url: null }]} state="found" />);
    expect(screen.queryByText("Warranty")).toBeNull();
    expect(screen.getByText(/No small print clauses were found/)).toBeTruthy();
  });
});

describe("search fallback (story 28)", () => {
  const ev = { quote: "The minimum term is 12 months.", url: "https://www.fitbox.example/legal/terms", source_step: "tavily_search" };

  it("a value the backend found by web search says so next to its source link", () => {
    render(<CostCard costStreams={[{ label: "Monthly fee", type: "recurring", amount: 9.99, evidence: ev }]} state="found" horizon={12} />);
    render(<LockInCard lockIn={{ min_term_months: 12, evidence: [{ field: "min_term_months", ...ev }] }} state="found" />);
    render(<SmallPrintCard items={[{ field: "Returns window", value: "30 days", ...ev }]} state="found" />);
    expect(screen.getAllByText(/found by web search/i)).toHaveLength(3);
  });

  it("a value from the page's own T&C link carries no such label", () => {
    render(<LockInCard lockIn={FIXTURES.broadband.lock_in} state="found" />);
    expect(screen.queryByText(/web search/i)).toBeNull();
  });
});

describe("all four card states render", () => {
  const f = FIXTURES.broadband;
  const cards = {
    cost: (s: CardState) => <CostCard costStreams={f.cost_streams} state={s} horizon={12} />,
    lock_in: (s: CardState) => <LockInCard lockIn={f.lock_in} state={s} />,
    small_print: (s: CardState) => <SmallPrintCard items={f.small_print} state={s} />,
  };
  for (const [name, card] of Object.entries(cards)) {
    for (const s of STATES) {
      it(`${name} · ${s}`, () => {
        const { container } = render(card(s));
        const section = container.querySelector("section.card")!;
        expect(section).toBeTruthy();
        expect(section.className).toContain(`card--${s}`);
        expect(section.querySelector(".badge")?.textContent).toBe({ found: "Found", estimated: "Estimated", not_found: "Not found", n_a: "N/A" }[s]);
      });
    }
  }
});

describe("limit_reached (contracts/response.schema.json card_state)", () => {
  it("cost, lock-in and small print say the daily limit was reached, not that nothing was found", () => {
    render(<CostCard costStreams={[]} state="limit_reached" horizon={12} />);
    render(<LockInCard lockIn={{ evidence: [] }} state="limit_reached" />);
    render(<SmallPrintCard items={[]} state="limit_reached" />);
    expect(screen.getAllByText("Limit reached")).toHaveLength(3);
    expect(screen.getAllByText(/daily limit/i)).toHaveLength(3);
    expect(screen.queryAllByText(/wasn't found/)).toHaveLength(0);
  });
});

describe("statutory rights", () => {
  it("are shown apart from the cards and labelled as not legal advice", () => {
    render(<StatutoryRights purchaseTypes={["product"]} />);
    const box = screen.getByTestId("statutory-rights");
    expect(box.tagName).toBe("SECTION");
    expect(box.classList.contains("card")).toBe(false);
    expect(within(box).getByText("Not legal advice")).toBeTruthy();
    expect(box.textContent).toContain("not legal advice");
  });

  it("depend on the purchase type and link to the law", () => {
    render(<StatutoryRights purchaseTypes={["product"]} />);
    expect(screen.getByText("Goods must be as described and work")).toBeTruthy();
    expect(screen.queryByText(/reasonable care and skill/)).toBeNull();
    cleanup();
    render(<StatutoryRights purchaseTypes={["subscription", "contract"]} />);
    expect(screen.getByText("Services must be done with reasonable care and skill")).toBeTruthy();
    expect(screen.getByText("14 days to change your mind")).toBeTruthy();
    for (const a of Array.from(screen.getByTestId("statutory-rights").querySelectorAll("a"))) {
      expect(a.getAttribute("href")).toMatch(/^https:\/\/www\.(legislation\.)?gov\.uk\//);
    }
  });
});

describe("parseExitFee", () => {
  it("only reads an exact single amount", () => {
    expect(parseExitFee("£215")).toBe(215);
    expect(parseExitFee("£1,200.50")).toBe(1200.5);
    expect(parseExitFee("Up to £215")).toBeNull();
    expect(parseExitFee("Remaining monthly payments")).toBeNull();
    expect(parseExitFee(null)).toBeNull();
  });
});
