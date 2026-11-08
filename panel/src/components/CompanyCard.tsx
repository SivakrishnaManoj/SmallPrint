import { useState } from "preact/hooks";
import type { Company, CompanyRecord, CardState } from "../types";

type FlagState = "idle" | "open" | "submitting" | "done" | "error";

interface Props {
  company: Company;
  state: CardState;
  flaggedKinds: string[];
  /** Called when the user submits a wrong-match report. Returns true on success. */
  onFlag?: (correction?: string) => Promise<boolean>;
}

export const KIND_LABELS: Record<string, string> = {
  donation: "Political donation",
  gender_pay_gap: "Gender pay gap",
  modern_slavery: "Slavery statement",
  asa_ruling: "ASA ruling",
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

/** "Wrong match?" report (v4): only when a match was made and a handler is wired up. */
function WrongMatch({ company, onFlag }: { company: Company; onFlag: (correction?: string) => Promise<boolean> }) {
  const [flagState, setFlagState] = useState<FlagState>("idle");
  const [correction, setCorrection] = useState("");
  async function send() {
    setFlagState("submitting");
    setFlagState((await onFlag(correction.trim() || undefined)) ? "done" : "error");
  }
  return (
    <div class="company__flag" data-testid="company-flag">
      {flagState === "idle" && (
        <button type="button" class="company__flag-trigger" onClick={() => setFlagState("open")}>Wrong match?</button>
      )}
      {flagState === "open" && (
        <div class="company__flag-form">
          {company.parent && (
            <p class="company__flag-prompt">
              Is <strong>{company.parent}</strong> the wrong parent for <strong>{company.brand}</strong>?
            </p>
          )}
          <input
            type="text"
            class="text-input"
            placeholder="Correct parent company (optional)"
            value={correction}
            maxLength={200}
            onInput={(e) => setCorrection((e.target as HTMLInputElement).value)}
          />
          <div class="company__flag-actions">
            <button type="button" class="btn btn--primary" onClick={send}>Flag this match</button>
            <button type="button" class="btn btn--ghost" onClick={() => setFlagState("idle")}>Cancel</button>
          </div>
        </div>
      )}
      {flagState === "submitting" && <span class="muted">Sending…</span>}
      {flagState === "done" && <span class="company__flag-done" data-testid="flag-done">✓ Flagged — we'll review this match.</span>}
      {flagState === "error" && (
        <span class="company__flag-error">
          Couldn't send. <button type="button" class="company__flag-trigger" onClick={send}>Retry</button>
        </span>
      )}
    </div>
  );
}

export function CompanyCard({ company, state, flaggedKinds, onFlag }: Props) {
  const [showAll, setShowAll] = useState(false);

  if (state === "n_a") return null;

  // A non-match is still an answer (W6): say so rather than hide the section.
  if (state === "not_found") {
    return (
      <div class="sp-chain" data-testid="company-not-found">
        <div class="sp-chain__node">
          {company?.brand || "Unknown brand"}
          <small>brand on this page</small>
        </div>
        <p class="muted" style="margin-top:10px">Owner not identified.</p>
        <p class="muted" data-testid="no-records">No public records matched.</p>
      </div>
    );
  }

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

      {onFlag && (company.match_via || company.ch_number) && <WrongMatch company={company} onFlag={onFlag} />}

      {records.length === 0 && (
        <p class="muted" style="margin-top:10px" data-testid="no-records">No public records matched.</p>
      )}
    </div>
  );
}
