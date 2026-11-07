import { CardShell } from "./CardShell";
import type { LockIn, CardState } from "../types";

interface Props {
  lockIn: LockIn;
  state: CardState;
}

export function LockInCard({ lockIn, state }: Props) {
  if (state === "n_a") {
    return <CardShell title="Lock-in" state="n_a"><p class="muted">Lock-in terms don't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Lock-in" state="not_found"><p>Lock-in information wasn't found for this item.</p></CardShell>;
  }

  const rows: { label: string; value: string }[] = [];
  if (lockIn.min_term_months != null) rows.push({ label: "Minimum term", value: `${lockIn.min_term_months} months` });
  if (lockIn.exit_fee) rows.push({ label: "Exit fee", value: lockIn.exit_fee });
  if (lockIn.notice_days != null) rows.push({ label: "Notice period", value: `${lockIn.notice_days} days` });
  if (lockIn.auto_renews != null) rows.push({ label: "Auto-renews", value: lockIn.auto_renews ? "Yes" : "No" });
  if (lockIn.cancel_method) rows.push({ label: "How to cancel", value: lockIn.cancel_method });
  if (lockIn.proprietary_refills != null) rows.push({ label: "Proprietary refills", value: lockIn.proprietary_refills ? "Yes — only manufacturer refills" : "No" });

  return (
    <CardShell title="Lock-in" state={state}>
      {rows.length === 0 ? (
        <p>No lock-in terms were found.</p>
      ) : (
        <dl class="lock-in__list">
          {rows.map((r) => (
            <>
              <dt>{r.label}</dt>
              <dd>{r.value}</dd>
            </>
          ))}
        </dl>
      )}
    </CardShell>
  );
}
