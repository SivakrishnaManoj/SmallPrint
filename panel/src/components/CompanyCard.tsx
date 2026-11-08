import { useState } from "preact/hooks";
import type { Company, CompanyRecord, CardState } from "../types";

interface Props {
  company: Company;
  state: CardState;
  flaggedKinds: string[];
}

export const KIND_LABELS: Record<string, string> = {
  donation: "Political donation",
  gender_pay_gap: "Gender pay gap",
  modern_slavery: "Slavery statement",
  regulator_decision: "Regulator decision",
  nmw_underpayment: "Min wage underpayment",
  prompt_payment: "Payment practices",
};

const SETTING_TO_KIND: Record<string, string> = {
  political_donations: "donation",
  regulator_decisions: "regulator_decision",
};

export function flaggedRecordKinds(settingKinds: readonly string[]): Set<string> {
  return new Set(settingKinds.map((k) => SETTING_TO_KIND[k] ?? k));
}

const byDateDesc = (a: CompanyRecord, b: CompanyRecord) => (b.date ?? "").localeCompare(a.date ?? "");

export function formatDate(iso: string): string {
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return iso;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

function recSub(r: CompanyRecord): string {
  const year = r.date?.slice(0, 4) ?? "";
  try {
    const domain = new URL(r.source_url).hostname.replace(/^www\./, "");
    return year ? `${domain} · ${year}` : domain;
  } catch {
    return year;
  }
}

export function CompanyCard({ company, state, flaggedKinds }: Props) {
  const [showAll, setShowAll] = useState(false);

  if (state === "n_a" || state === "not_found") return null;

  const tracked = flaggedRecordKinds(flaggedKinds);
  const records = [...(company.records ?? [])].sort(byDateDesc);
  const top = records.filter((r) => tracked.has(r.kind));
  const rest = records.filter((r) => !tracked.has(r.kind));
  const allRecords = [...top, ...rest];
  const GRID_MAX = 4;
  const gridRecords = showAll ? allRecords : allRecords.slice(0, GRID_MAX);
  const hiddenCount = allRecords.length - GRID_MAX;

  return (
    <div class="sp-chain">
      {/* Brand node */}
      <div class="sp-chain__node">
        {company.brand ?? "Unknown brand"}
        <small>brand on this page</small>
      </div>

      {/* Chain link to parent */}
      {company.parent && company.parent !== company.brand && (
        <>
          <div class="sp-chain__link" />
          {company.match_via && (
            <span class="sp-chain__via">matched via {company.match_via}</span>
          )}
          <div class="sp-chain__node sp-chain__node--parent">
            {company.parent}
            {company.ch_number && (
              <small>Companies House {company.ch_number}</small>
            )}
          </div>
        </>
      )}

      {/* Records grid */}
      {allRecords.length > 0 && (
        <div class="sp-chain__records">
          {gridRecords.map((r) => (
            <a
              key={`${r.kind}_${r.date}`}
              href={r.source_url}
              target="_blank"
              rel="noopener noreferrer"
              class={tracked.has(r.kind) ? "sp-chain__rec" : "sp-chain__rec sp-chain__rec--neutral"}
              style="text-decoration:none;color:inherit"
            >
              {KIND_LABELS[r.kind] ?? r.kind.replace(/_/g, " ")}
              <small>{recSub(r)}</small>
            </a>
          ))}
        </div>
      )}

      {!showAll && hiddenCount > 0 && (
        <button type="button" class="sp-chain__show-more" onClick={() => setShowAll(true)}>
          Show {hiddenCount} more record{hiddenCount === 1 ? "" : "s"}
        </button>
      )}

      {records.length === 0 && (
        <p class="muted" style="margin-top:10px">No public records matched.</p>
      )}
    </div>
  );
}
