/**
 * Cost model: turns `cost_streams` and a horizon into a lifetime total.
 *
 * A pure function with no network and no DOM. The cost card calls it every time the
 * user changes the horizon, so it runs in the browser. Unreadable input throws
 * `CostModelError`; the caller shows the card as `not_found` instead of a wrong number.
 *
 * Rules (the schema does not define these, so they are written down here):
 *  1. The horizon is 12 or 24 months. Months are numbered from 1.
 *  2. `one_off` is charged once.
 *  3. `recurring` is charged in every month from `from_month` (default 1) to `to_month`
 *     (default: the end of the horizon). A trial price and a full price are two recurring
 *     streams with different windows.
 *  4. `step_change` adds its `amount` to the monthly charge from `month` onward. It applies
 *     only in months where at least one recurring stream is active.
 *  5. `usage` is `unit_price x units_per_month x months in its window`, once for each of
 *     low, mid and high. Any usage stream makes the state `estimated`.
 *  6. The exit fee never changes `total`. `totalIfLeaving` adds it when the horizon ends
 *     before `minTermMonths`. With no minimum term given, the fee is taken to apply.
 *  7. A missing required field, an unknown type, a month below 1, or a window that ends
 *     before it starts is an error. Nothing is guessed or counted as zero.
 *  8. Totals are rounded to whole pence.
 */
import type { CardState, CostStream } from "../types";

export type Horizon = 12 | 24;
export type UsageLevel = "low" | "mid" | "high";
export type Range = Record<UsageLevel, number>;

export interface LifetimeCost {
  state: CardState;
  /** Cost of staying to the end of the horizon. `null` when there are no cost streams. */
  total: Range | null;
  /** `total` plus the exit fee, when leaving at the horizon would break the minimum term. */
  totalIfLeaving: Range | null;
}

export interface LifetimeCostOptions {
  /** Exit fee as a number of pounds. The caller must turn the quoted text into a number. */
  exitFee?: number | null;
  minTermMonths?: number | null;
}

export class CostModelError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CostModelError";
  }
}

const HORIZONS: readonly number[] = [12, 24];
const LEVELS: readonly UsageLevel[] = ["low", "mid", "high"];

/** What each stream type must carry before it can be counted. */
const REQUIRED_FIELDS: Record<CostStream["type"], readonly (keyof CostStream)[]> = {
  one_off: ["amount"],
  recurring: ["amount"],
  step_change: ["amount", "month"],
  usage: ["unit_price", "units_per_month"],
};

function validate(streams: readonly CostStream[], horizon: number): void {
  if (!HORIZONS.includes(horizon)) {
    throw new CostModelError(`horizon must be 12 or 24 months, got ${horizon}`);
  }
  for (const stream of streams) {
    const label = stream.label ?? "<unlabelled>";
    const required = REQUIRED_FIELDS[stream.type];
    if (required === undefined) {
      throw new CostModelError(`cost stream '${label}' has unknown type '${String(stream.type)}'`);
    }
    for (const field of required) {
      if (stream[field] == null) {
        throw new CostModelError(`cost stream '${label}' is missing '${field}'`);
      }
    }
    for (const field of ["from_month", "to_month", "month"] as const) {
      const value = stream[field];
      if (value != null && (!Number.isInteger(value) || value < 1)) {
        throw new CostModelError(`cost stream '${label}' has an invalid '${field}': ${value}`);
      }
    }
    if (stream.from_month != null && stream.to_month != null && stream.from_month > stream.to_month) {
      throw new CostModelError(
        `cost stream '${label}' ends (month ${stream.to_month}) before it starts (month ${stream.from_month})`,
      );
    }
    if (stream.type === "usage") {
      const missing = LEVELS.filter((level) => stream.units_per_month?.[level] == null);
      if (missing.length > 0) {
        throw new CostModelError(`cost stream '${label}' is missing units_per_month ${missing.join(", ")}`);
      }
    }
  }
}

function isActive(stream: CostStream, month: number, horizon: number): boolean {
  const first = stream.from_month ?? 1;
  const last = Math.min(stream.to_month ?? horizon, horizon);
  return first <= month && month <= last;
}

function monthlyCharge(streams: readonly CostStream[], month: number, horizon: number): number {
  const recurring = streams.filter((s) => s.type === "recurring" && isActive(s, month, horizon));
  if (recurring.length === 0) return 0;
  let charge = recurring.reduce((sum, s) => sum + (s.amount as number), 0);
  // A rise only exists while there is a recurring fee for it to apply to.
  charge += streams
    .filter((s) => s.type === "step_change" && (s.month as number) <= month)
    .reduce((sum, s) => sum + (s.amount as number), 0);
  return charge;
}

function usageCharge(stream: CostStream, level: UsageLevel, horizon: number): number {
  let months = 0;
  for (let month = 1; month <= horizon; month++) {
    if (isActive(stream, month, horizon)) months++;
  }
  const units = (stream.units_per_month as Range)[level];
  return (stream.unit_price as number) * units * months;
}

function exitFeeApplies(options: LifetimeCostOptions, horizon: number): boolean {
  if (options.exitFee == null) return false;
  // With no stated minimum term, the fee is taken to apply whenever you leave.
  return options.minTermMonths == null || horizon < options.minTermMonths;
}

/** Round to whole pence, so float drift (for example 119.88000000000001) never reaches the screen. */
function toPence(pounds: number): number {
  return Math.round(pounds * 100) / 100;
}

export function lifetimeCost(
  costStreams: readonly CostStream[],
  horizon: Horizon,
  options: LifetimeCostOptions = {},
): LifetimeCost {
  validate(costStreams, horizon);
  if (costStreams.length === 0) {
    return { state: "not_found", total: null, totalIfLeaving: null };
  }

  let fixed = costStreams
    .filter((s) => s.type === "one_off")
    .reduce((sum, s) => sum + (s.amount as number), 0);
  for (let month = 1; month <= horizon; month++) {
    fixed += monthlyCharge(costStreams, month, horizon);
  }

  const usageStreams = costStreams.filter((s) => s.type === "usage");
  const fee = exitFeeApplies(options, horizon) ? (options.exitFee as number) : 0;
  const total = {} as Range;
  const totalIfLeaving = {} as Range;
  for (const level of LEVELS) {
    const stay = fixed + usageStreams.reduce((sum, s) => sum + usageCharge(s, level, horizon), 0);
    total[level] = toPence(stay);
    totalIfLeaving[level] = toPence(stay + fee);
  }

  return { state: usageStreams.length > 0 ? "estimated" : "found", total, totalIfLeaving };
}
