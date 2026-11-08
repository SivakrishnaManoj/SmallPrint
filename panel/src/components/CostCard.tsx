import { useEffect, useState } from "preact/hooks";
import { hasEvidence } from "./Evidence";
import type { CostStream, CardState, LockIn, PriceDrift } from "../types";
import { CostModelError, lifetimeCost, type Horizon, type Range } from "../cost/lifetimeCost";
import { parseExitFee } from "../cost/exitFee";

interface Props {
  costStreams: CostStream[];
  state: CardState;
  horizon: Horizon;
  lockIn?: LockIn;
  priceDrift?: PriceDrift;
}

const money = (n: number) => `£${n.toFixed(2)}`;
const range = (r: Range) => (r.low === r.high ? money(r.mid) : `${money(r.low)} – ${money(r.high)}`);

function receiptLabel(s: CostStream, horizon: number): string {
  const from = s.from_month ?? 1;
  const to = Math.min(s.to_month ?? horizon, horizon);
  const months = Math.max(0, to - from + 1);

  switch (s.type) {
    case "one_off":
      return s.label;
    case "recurring":
      return `${s.label} × ${months}`;
    case "usage": {
      const qty = Math.round(s.units_per_month!.mid * months);
      return `${s.label} ${qty}× ${money(s.unit_price ?? 0)}`;
    }
    case "step_change":
      return s.label;
  }
}

function receiptAmount(s: CostStream, horizon: number): number {
  const from = s.from_month ?? 1;
  const to = Math.min(s.to_month ?? horizon, horizon);
  const months = Math.max(0, to - from + 1);

  switch (s.type) {
    case "one_off":
      return s.amount ?? 0;
    case "recurring":
      return (s.amount ?? 0) * months;
    case "usage":
      return (s.unit_price ?? 0) * s.units_per_month!.mid * months;
    case "step_change":
      if (s.month == null || s.month > horizon) return 0;
      return (s.amount ?? 0) * (horizon - s.month + 1);
  }
}

export function CostCard({ costStreams, state, horizon, lockIn, priceDrift }: Props) {
  const [displayHorizon, setDisplayHorizon] = useState<Horizon>(horizon);
  useEffect(() => setDisplayHorizon(horizon), [horizon]);

  if (state === "n_a" || state === "not_found") return null;

  const verified = costStreams.filter((s) => hasEvidence(s.evidence?.quote, s.evidence?.url));
  if (verified.length === 0) return null;

  let totalDisplay: string | null = null;
  let isEstimated = false;
  try {
    const result = lifetimeCost(
      verified,
      displayHorizon,
      { exitFee: parseExitFee(lockIn?.exit_fee), minTermMonths: lockIn?.min_term_months },
    );
    if (result?.total) {
      totalDisplay = range(result.total);
      isEstimated = result.state === "estimated";
    }
  } catch (err) {
    if (!(err instanceof CostModelError)) throw err;
  }

  const addedFees = priceDrift?.added ?? [];

  return (
    <div class="sp-receipt">
      <div class="sp-receipt__header">
        <span>Receipt <em>{displayHorizon} months</em></span>
        <div class="sp-receipt__horizon-group">
          {([12, 24] as Horizon[]).map((h) => (
            <button
              key={h}
              type="button"
              class={displayHorizon === h ? "sp-receipt__hz-btn active" : "sp-receipt__hz-btn"}
              onClick={() => setDisplayHorizon(h)}
            >
              {h}mo
            </button>
          ))}
        </div>
      </div>

      {verified.map((s, i) => (
        <div key={i} class="sp-receipt__row">
          <span>{receiptLabel(s, displayHorizon)}</span>
          <span>{money(receiptAmount(s, displayHorizon))}</span>
        </div>
      ))}

      {totalDisplay && (
        <>
          <div class="sp-receipt__divider" />
          <div class="sp-receipt__row sp-receipt__row--total">
            <span>Total {displayHorizon} months{isEstimated ? " (est.)" : ""}</span>
            <span>{totalDisplay}</span>
          </div>
        </>
      )}

      {addedFees.length > 0 && (
        <>
          <div class="sp-receipt__divider" />
          {addedFees.map((fee, i) => (
            <div key={i} class="sp-receipt__row sp-receipt__row--fee">
              <span>+ {fee.label}</span>
              <span>+{money(fee.amount)}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
