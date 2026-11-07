import { useState } from "preact/hooks";
import { CardShell } from "./CardShell";
import type { Company, CardState } from "../types";

interface Props {
  company: Company;
  state: CardState;
  flaggedKinds: string[];
}

const KIND_LABELS: Record<string, string> = {
  gender_pay_gap: "Gender pay gap",
  donation: "Political donation",
  nmw_underpayment: "Minimum wage violation",
  prompt_payment: "Late payment to suppliers",
  modern_slavery: "Modern slavery statement",
  regulator_decision: "Regulator decision",
};

export function CompanyCard({ company, state, flaggedKinds }: Props) {
  const [showAll, setShowAll] = useState(false);

  if (state === "n_a") {
    return <CardShell title="Who's behind it" state="n_a"><p class="muted">Company information doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Who's behind it" state="not_found"><p>No company match was found. No public records matched.</p></CardShell>;
  }

  const records = company.records ?? [];
  const flagged = records.filter((r) => flaggedKinds.includes(r.kind));
  const others = records.filter((r) => !flaggedKinds.includes(r.kind));

  return (
    <CardShell title="Who's behind it" state={state}>
      {company.brand && <p><strong>{company.brand}</strong></p>}
      {company.parent && company.parent !== company.brand && (
        <p class="company__meta">Parent company: {company.parent}</p>
      )}
      {company.match_via && (
        <p class="company__match-via">Matched: {company.match_via}</p>
      )}
      {company.ch_number && (
        <p class="company__meta">Companies House: {company.ch_number}</p>
      )}

      {records.length === 0 ? (
        <p class="muted">No public records matched.</p>
      ) : (
        <div class="company__records">
          {flagged.length > 0 && (
            <ul class="records-list records-list--flagged">
              {flagged.map((r, i) => (
                <li key={i} class="record-item record-item--flagged">
                  <span class="record-kind">{KIND_LABELS[r.kind] ?? r.kind}</span>
                  <span class="record-date">{r.date}</span>
                  <p class="record-summary">{r.summary}</p>
                  <a href={r.source_url} class="source-link" target="_blank" rel="noopener noreferrer">Source ↗</a>
                </li>
              ))}
            </ul>
          )}

          {others.length > 0 && (
            <div class="records-others">
              <button class="show-all-btn" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Hide" : `Show all records (${others.length} more)`}
              </button>
              {showAll && (
                <ul class="records-list">
                  {others.map((r, i) => (
                    <li key={i} class="record-item">
                      <span class="record-kind">{KIND_LABELS[r.kind] ?? r.kind}</span>
                      <span class="record-date">{r.date}</span>
                      <p class="record-summary">{r.summary}</p>
                      <a href={r.source_url} class="source-link" target="_blank" rel="noopener noreferrer">Source ↗</a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </CardShell>
  );
}
