import { useState } from "preact/hooks";
import { CardShell } from "./CardShell";
import type { Company, CompanyRecord, CardState } from "../types";

interface Props {
  company: Company;
  state: CardState;
  /** Record kinds the user ticked in settings ("values filter"). Settings IDs or record kinds. */
  flaggedKinds: string[];
}

/**
 * Neutral names for each record kind. Evidence, not verdicts: no score, no good/bad labels,
 * no verdict words. A record says what was recorded, when, and where it comes from.
 */
export const KIND_LABELS: Record<string, string> = {
  donation: "Political donation",
  gender_pay_gap: "Gender pay gap report",
  modern_slavery: "Modern slavery statement",
  asa_ruling: "ASA ruling",
  regulator_decision: "Regulator decision",
  nmw_underpayment: "Minimum wage underpayment",
  prompt_payment: "Payment practices report",
};

/** Settings IDs that differ from the record kind they mean. */
const SETTING_TO_KIND: Record<string, string> = {
  political_donations: "donation",
  regulator_decisions: "regulator_decision",
};

/** The record kinds the user asked to see first. */
export function flaggedRecordKinds(settingKinds: readonly string[]): Set<string> {
  return new Set(settingKinds.map((k) => SETTING_TO_KIND[k] ?? k));
}

const byDateDesc = (a: CompanyRecord, b: CompanyRecord) => (b.date ?? "").localeCompare(a.date ?? "");

/** "2023-04-05" → "5 April 2023"; anything else is shown as given. */
export function formatDate(iso: string): string {
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return iso;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

function Record({ r, flagged }: { r: CompanyRecord; flagged: boolean }) {
  return (
    <li class={flagged ? "record-item record-item--tracked" : "record-item"} data-testid="record" data-kind={r.kind}>
      <span class="record-kind">{KIND_LABELS[r.kind] ?? r.kind.replace(/_/g, " ")}</span>
      <span class="record-date">{formatDate(r.date)}</span>
      <p class="record-summary">{r.summary}</p>
      {r.source_url ? (
        <a href={r.source_url} class="source-link" target="_blank" rel="noopener noreferrer">Source ↗</a>
      ) : (
        <span class="muted">Source link not available</span>
      )}
    </li>
  );
}

const NoRecords = () => <p class="muted" data-testid="no-records">No public records matched.</p>;

export function CompanyCard({ company, state, flaggedKinds }: Props) {
  const [showAll, setShowAll] = useState(false);

  if (state === "n_a") {
    return <CardShell title="Who's behind it" state="n_a"><p class="muted">Company information doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return (
      <CardShell title="Who's behind it" state="not_found">
        {company?.brand && <p><strong>{company.brand}</strong></p>}
        <NoRecords />
      </CardShell>
    );
  }

  const tracked = flaggedRecordKinds(flaggedKinds);
  const records = [...(company.records ?? [])].sort(byDateDesc);
  // Values filter: the kinds the user ticked come first, newest first; the rest are one tap away.
  const top = records.filter((r) => tracked.has(r.kind));
  const rest = records.filter((r) => !tracked.has(r.kind));

  return (
    <CardShell title="Who's behind it" state={state}>
      {company.brand && <p class="company__brand"><strong>{company.brand}</strong></p>}
      {company.parent && company.parent !== company.brand && (
        <p class="company__meta">Parent company: {company.parent}</p>
      )}
      {(company.match_via || company.ch_number) && (
        <p class="company__match-via" data-testid="match-via">
          Matched by: {company.match_via ?? "Companies House number"}
          {company.ch_number && <> · Companies House {company.ch_number}</>}
        </p>
      )}

      {records.length === 0 ? (
        <NoRecords />
      ) : (
        <div class="company__records">
          {top.length > 0 && (
            <>
              <p class="records-heading">Records you chose to see first</p>
              <ul class="records-list">
                {top.map((r, i) => <Record key={`t${i}`} r={r} flagged />)}
              </ul>
            </>
          )}
          {top.length === 0 && rest.length > 0 && (
            <p class="muted">None of the records are of the kinds you chose to see first.</p>
          )}
          {rest.length > 0 && (
            <div class="records-others">
              <button type="button" class="show-all-btn" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Hide other records" : `Show ${rest.length} other record${rest.length === 1 ? "" : "s"}`}
              </button>
              {showAll && (
                <ul class="records-list">
                  {rest.map((r, i) => <Record key={`o${i}`} r={r} flagged={false} />)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </CardShell>
  );
}
