import { CardShell } from "./CardShell";
import { Evidence, hasEvidence } from "./Evidence";
import type { LockIn, LockInField, CardState } from "../types";

interface Props {
  lockIn: LockIn;
  state: CardState;
}

const yesNo = (v: boolean) => (v ? "Yes" : "No");

/** Field order and how each value reads. */
const FIELDS: { field: LockInField; label: string; show: (l: LockIn) => string | null }[] = [
  { field: "min_term_months", label: "Minimum term", show: (l) => (l.min_term_months != null ? `${l.min_term_months} months` : null) },
  { field: "exit_fee", label: "Exit fee", show: (l) => l.exit_fee ?? null },
  { field: "notice_days", label: "Notice to cancel", show: (l) => (l.notice_days != null ? `${l.notice_days} days` : null) },
  { field: "auto_renews", label: "Auto-renews", show: (l) => (l.auto_renews != null ? yesNo(l.auto_renews) : null) },
  { field: "cancel_method", label: "How to cancel", show: (l) => l.cancel_method ?? null },
  {
    field: "proprietary_refills",
    label: "Own-brand refills only",
    show: (l) => (l.proprietary_refills != null ? yesNo(l.proprietary_refills) : null),
  },
];

export function LockInCard({ lockIn, state }: Props) {
  if (state === "n_a") {
    return <CardShell title="Lock-in" state="n_a"><p class="muted">Lock-in terms don't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Lock-in" state="not_found"><p>Lock-in information wasn't found for this item.</p></CardShell>;
  }

  // Quote or null: each value is shown only with its own evidence entry.
  const rows = FIELDS.flatMap(({ field, label, show }) => {
    const value = show(lockIn);
    const ev = lockIn.evidence?.find((e) => e.field === field && hasEvidence(e.quote, e.url));
    return value != null && ev ? [{ field, label, value, quote: ev.quote, url: ev.url }] : [];
  });

  return (
    <CardShell title="Lock-in" state={state}>
      {rows.length === 0 ? (
        <p>No lock-in terms were found with a quote from the source.</p>
      ) : (
        <ul class="lock-in__list">
          {rows.map((r) => (
            <li key={r.field} class="lock-in__item" data-testid="lock-in-row">
              <span class="lock-in__label">{r.label}</span>
              <span class="lock-in__value">{r.value}</span>
              <Evidence quote={r.quote} url={r.url} />
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}
