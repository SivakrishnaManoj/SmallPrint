// @vitest-environment happy-dom
/**
 * W6: company card and values filter.
 * Done when "No public records matched" renders for a non-match and the values filter reorders records.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { CompanyCard, flaggedRecordKinds, formatDate } from "~panel/components/CompanyCard";
import type { Company, CompanyRecord } from "~panel/types";
import { DEFAULT_SETTINGS } from "~panel/types";
import broadband from "~fixtures/broadband.json";
import sodastream from "~fixtures/sodastream.json";

afterEach(cleanup);

const rec = (kind: string, date: string, summary: string, source_url = "https://example.gov.uk/r"): CompanyRecord => ({ kind, date, summary, source_url });
const COMPANY: Company = {
  brand: "Fernline",
  parent: "Fernline Holdings plc",
  ch_number: "01234567",
  match_via: "Companies House number",
  records: [
    rec("gender_pay_gap", "2024-04-04", "Reported a median hourly pay gap of 9.1% for 2023-24."),
    rec("donation", "2023-06-12", "Donated £25,000 to the Example Party on 12 June 2023."),
    rec("modern_slavery", "2024-09-30", "Published a modern slavery statement for FY2024."),
    rec("donation", "2024-02-01", "Donated £10,000 to the Other Party on 1 February 2024."),
  ],
};
const kinds = () => screen.queryAllByTestId("record").map((el) => el.getAttribute("data-kind"));

describe("no match", () => {
  it('shows "No public records matched" for a non-match', () => {
    render(<CompanyCard company={{ brand: "Unknown Ltd" }} state="not_found" flaggedKinds={[]} />);
    expect(screen.getByTestId("no-records").textContent).toBe("No public records matched.");
    expect(screen.getByText("Unknown Ltd")).toBeTruthy();
  });

  it("also for a matched company with no records", () => {
    render(<CompanyCard company={{ ...COMPANY, records: [] }} state="found" flaggedKinds={["donation"]} />);
    expect(screen.getByTestId("no-records").textContent).toBe("No public records matched.");
  });
});

describe("values filter", () => {
  it("puts the kinds the user ticked first, newest first; the rest are one tap away", () => {
    render(<CompanyCard company={COMPANY} state="found" flaggedKinds={["donation"]} />);
    expect(kinds()).toEqual(["donation", "donation"]);
    expect(screen.getAllByTestId("record")[0].textContent).toContain("1 February 2024");
    fireEvent.click(screen.getByRole("button", { name: "Show 2 other records" }));
    expect(kinds()).toEqual(["donation", "donation", "modern_slavery", "gender_pay_gap"]);
  });

  it("reorders when the user's choice changes", () => {
    const { rerender } = render(<CompanyCard company={COMPANY} state="found" flaggedKinds={["gender_pay_gap"]} />);
    expect(kinds()).toEqual(["gender_pay_gap"]);
    rerender(<CompanyCard company={COMPANY} state="found" flaggedKinds={["modern_slavery", "gender_pay_gap"]} />);
    expect(kinds()).toEqual(["modern_slavery", "gender_pay_gap"]);
  });

  it("matches the settings IDs to record kinds (political_donations → donation)", () => {
    expect(flaggedRecordKinds(["political_donations", "regulator_decisions", "gender_pay_gap"]))
      .toEqual(new Set(["donation", "regulator_decision", "gender_pay_gap"]));
    render(<CompanyCard company={COMPANY} state="found" flaggedKinds={DEFAULT_SETTINGS.recordKinds} />);
    expect(kinds()).toContain("donation");
  });

  it("says so when nothing matches the chosen kinds", () => {
    render(<CompanyCard company={COMPANY} state="found" flaggedKinds={["regulator_decisions"]} />);
    expect(kinds()).toEqual([]);
    expect(screen.getByText(/None of the records are of the kinds you chose/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show 4 other records" })).toBeTruthy();
  });
});

describe("what the card shows", () => {
  it("parent, match method and dated, sourced records", () => {
    render(<CompanyCard company={COMPANY} state="found" flaggedKinds={["donation"]} />);
    expect(screen.getByText("Parent company: Fernline Holdings plc")).toBeTruthy();
    expect(screen.getByTestId("match-via").textContent).toBe("Matched by: Companies House number · Companies House 01234567");
    const first = screen.getAllByTestId("record")[0];
    expect(first.textContent).toContain("Political donation");
    expect(first.textContent).toContain("Donated £10,000 to the Other Party on 1 February 2024.");
    expect(first.querySelector("a")?.getAttribute("href")).toBe("https://example.gov.uk/r");
  });

  it("copes with a record that has no source link", () => {
    const company = { ...COMPANY, records: [{ ...rec("donation", "2024-01-01", "Donated £1 to X."), source_url: null as unknown as string }] };
    render(<CompanyCard company={company} state="found" flaggedKinds={["donation"]} />);
    expect(screen.getByText("Source link not available")).toBeTruthy();
  });

  it("no score, no good or bad labels, no verdict words (fixtures included)", () => {
    const VERDICT = /\b(score|rating|rated|good|bad|ethical|unethical|evil|terrible|poor|excellent|avoid|boycott|shame|scandal|warning|verdict|grade)\b/i;
    const companies = [COMPANY, (broadband as { company: Company }).company, (sodastream as { company: Company }).company];
    for (const c of companies) {
      render(<CompanyCard company={c} state="found" flaggedKinds={[]} />);
      fireEvent.click(screen.getByRole("button", { name: /Show \d+ other record/ }));
      const text = document.body.textContent ?? "";
      expect(text).not.toMatch(VERDICT);
      expect(document.body.querySelector("[class*='score'], [class*='rating'], meter, progress")).toBeNull();
      cleanup();
    }
  });

  it("n_a renders, and dates read as words", () => {
    render(<CompanyCard company={{}} state="n_a" flaggedKinds={[]} />);
    expect(screen.getByText("Company information doesn't apply to this page.")).toBeTruthy();
    expect(formatDate("2023-04-05")).toBe("5 April 2023");
    expect(formatDate("FY2023")).toBe("FY2023");
  });
});
