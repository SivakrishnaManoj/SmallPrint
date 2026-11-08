import { useEffect, useState } from "preact/hooks";
import { CardShell } from "./CardShell";
import { Evidence, hasEvidence } from "./Evidence";
import type { CostStream, CardState, LockIn } from "../types";
import { CostModelError, lifetimeCost, type Horizon, type LifetimeCost, type Range } from "../cost/lifetimeCost";
import { parseExitFee } from "../cost/exitFee";

interface Props {
  costStreams: CostStream[];
  state: CardState;
  /** The user's default horizon from settings; the switch on the card overrides it. */
  horizon: Horizon;
  /** For the "if you leave at the end of the horizon" line. Optional. */
  lockIn?: LockIn;
}

const money = (n: number) => `£${n.toFixed(2)}`;
const range = (r: Range) => (r.low === r.high ? money(r.mid) : `${money(r.low)} – ${money(r.high)}`);

/** Per-month (or one-off) detail for one stream, as the user reads it. */
function streamDetail(s: CostStream): string {
  switch (s.type) {
    case "one_off":
      return `${money(s.amount ?? 0)} once`;
    case "recurring": {
      const window = s.from_month != null || s.to_month != null
        ? ` (months ${s.from_month ?? 1}–${s.to_month ?? "end"})`
        : "";
      return `${money(s.amount ?? 0)} a month${window}`;
    }
    case "step_change":
      return `+${money(s.amount ?? 0)} a month from month ${s.month}`;
    case "usage": {
      const u = s.units_per_month!;
      const p = s.unit_price ?? 0;
      return `${money(p)} each × ${u.low}–${u.high} a month = ${money(p * u.low)} – ${money(p * u.high)} a month (estimate)`;
    }
  }
}

/** The lifetime total, or null when a stream can't be read (shown as not_found, never a wrong number). */
function compute(streams: CostStream[], horizon: Horizon, lockIn?: LockIn): LifetimeCost | null {
  try {
    return lifetimeCost(streams, horizon, { exitFee: parseExitFee(lockIn?.exit_fee), minTermMonths: lockIn?.min_term_months });
  } catch (error) {
    if (error instanceof CostModelError) return null;
    throw error;
  }
}

const NotFound = () => (
  <CardShell title="Cost over time" state="not_found">
    <p>Cost information wasn't found for this item.</p>
  </CardShell>
);

export function CostCard({ costStreams, state, horizon, lockIn }: Props) {
  const [displayHorizon, setDisplayHorizon] = useState<Horizon>(horizon);
  // Follow the settings when the user changes their default horizon.
  useEffect(() => setDisplayHorizon(horizon), [horizon]);

  if (state === "n_a") {
    return <CardShell title="Cost over time" state="n_a"><p class="muted">Cost analysis doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") return <NotFound />;

  // Quote or null: a cost without its quote and link is neither shown nor counted.
  const verified = costStreams.filter((s) => hasEvidence(s.evidence?.quote, s.evidence?.url));
  const skipped = costStreams.length - verified.length;
  const result = compute(verified, displayHorizon, lockIn);
  if (!result || !result.total) return <NotFound />;

  // An estimate in the model makes the whole card an estimate, whatever the server said.
  const shownState: CardState = result.state === "estimated" ? "estimated" : state;
  const total = result.total;
  const leaving = result.totalIfLeaving;
  const usage = verified.filter((s) => s.type === "usage");

  return (
    <CardShell title="Cost over time" state={shownState}>
      <div class="cost__controls">
        <div class="toggle-group" role="group" aria-label="Horizon">
          {([12, 24] as Horizon[]).map((h) => (
            <button
              key={h}
              type="button"
              class={displayHorizon === h ? "toggle active" : "toggle"}
              aria-pressed={displayHorizon === h}
              onClick={() => setDisplayHorizon(h)}
            >
              {h} months
            </button>
          ))}
        </div>
      </div>

      <p class="cost__total" data-testid="cost-total">
        Total over {displayHorizon} months: <strong>{range(total)}</strong>
        {usage.length > 0 && <span class="estimated-label"> (estimated range)</span>}
      </p>
      {usage.length > 0 && (
        <p class="cost__note">
          The range comes from low and high usage of {usage.map((s) => s.label).join(", ")}; the sources are quoted below.
        </p>
      )}
      {leaving && leaving.mid !== total.mid && (
        <p class="cost__note" data-testid="cost-if-leaving">
          If you leave at month {displayHorizon}, before the minimum term ends: <strong>{range(leaving)}</strong>, including the exit fee.
        </p>
      )}

      <ul class="cost__streams">
        {verified.map((s, i) => (
          <li key={i} class="cost__stream-item" data-testid="cost-stream">
            <span class="stream__label">{s.label}</span>
            <span class="stream__detail">{streamDetail(s)}</span>
            <Evidence quote={s.evidence.quote} url={s.evidence.url} />
          </li>
        ))}
      </ul>
      {skipped > 0 && (
        <p class="muted">
          {skipped === 1 ? "1 cost was" : `${skipped} costs were`} found without a quote from the source, so {skipped === 1 ? "it isn't" : "they aren't"} shown or counted.
        </p>
      )}
    </CardShell>
  );
}
