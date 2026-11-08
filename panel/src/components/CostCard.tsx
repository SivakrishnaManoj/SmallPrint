import { useState } from "preact/hooks";
import { CardShell } from "./CardShell";
import type { CostStream, CardState } from "../types";
import { CostModelError, lifetimeCost, type Horizon, type UsageLevel } from "../cost/lifetimeCost";

interface Props {
  costStreams: CostStream[];
  state: CardState;
  horizon: Horizon;
}

/** The total for the chosen usage level, or `null` when no trustworthy total exists. */
function totalFor(streams: CostStream[], horizon: Horizon, usageLevel: UsageLevel): number | null {
  try {
    return lifetimeCost(streams, horizon).total?.[usageLevel] ?? null;
  } catch (error) {
    if (error instanceof CostModelError) return null;
    throw error;
  }
}

export function CostCard({ costStreams, state, horizon }: Props) {
  const [usageLevel, setUsageLevel] = useState<UsageLevel>("mid");
  const [displayHorizon, setDisplayHorizon] = useState<12 | 24>(horizon);

  if (state === "n_a") {
    return <CardShell title="Cost over time" state="n_a"><p class="muted">Cost analysis doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Cost over time" state="not_found"><p>Cost information wasn't found for this item.</p></CardShell>;
  }

  const total = totalFor(costStreams, displayHorizon, usageLevel);
  if (total === null) {
    // A stream could not be read, so no total is shown rather than a wrong one.
    return <CardShell title="Cost over time" state="not_found"><p>Cost information wasn't found for this item.</p></CardShell>;
  }
  const hasUsage = costStreams.some((s) => s.type === "usage");

  return (
    <CardShell title="Cost over time" state={state}>
      <div class="cost__controls">
        <div class="toggle-group">
          <button class={displayHorizon === 12 ? "toggle active" : "toggle"} onClick={() => setDisplayHorizon(12)}>12 months</button>
          <button class={displayHorizon === 24 ? "toggle active" : "toggle"} onClick={() => setDisplayHorizon(24)}>24 months</button>
        </div>
        {hasUsage && (
          <div class="slider-group">
            <label>Usage: </label>
            {(["low", "mid", "high"] as UsageLevel[]).map((l) => (
              <button key={l} class={usageLevel === l ? "toggle active" : "toggle"} onClick={() => setUsageLevel(l)}>
                {l.charAt(0).toUpperCase() + l.slice(1)}
              </button>
            ))}
          </div>
        )}
      </div>

      <p class="cost__total">
        Total over {displayHorizon} months:{" "}
        <strong>£{total.toFixed(2)}</strong>
        {state === "estimated" && <span class="estimated-label"> (estimated)</span>}
      </p>

      <ul class="cost__streams">
        {costStreams.map((s, i) => (
          <li key={i} class="cost__stream-item">
            <span class="stream__label">{s.label}</span>
            <span class="stream__detail">
              {s.type === "one_off" && `£${s.amount?.toFixed(2)} once`}
              {s.type === "recurring" && `£${s.amount?.toFixed(2)}/month`}
              {s.type === "step_change" && `+£${s.amount?.toFixed(2)}/month from month ${s.month}`}
              {s.type === "usage" && s.unit_price != null && s.units_per_month && (
                `£${(s.unit_price * (s.units_per_month[usageLevel] ?? 0)).toFixed(2)}/month (${usageLevel})`
              )}
            </span>
            {s.evidence?.quote && (
              <blockquote class="evidence-quote">{s.evidence.quote}</blockquote>
            )}
            {s.evidence?.url && (
              <a href={s.evidence.url} class="source-link" target="_blank" rel="noopener noreferrer">Source ↗</a>
            )}
          </li>
        ))}
      </ul>
    </CardShell>
  );
}
