export type CardState = "found" | "estimated" | "not_found" | "n_a";

export interface Evidence {
  quote?: string | null;
  url?: string | null;
  fetched?: string | null;
  source_step?: string | null;
}

export interface CostStream {
  label: string;
  type: "one_off" | "recurring" | "usage" | "step_change";
  amount?: number;
  unit_price?: number;
  units_per_month?: { low: number; mid: number; high: number };
  from_month?: number;
  to_month?: number;
  month?: number;
  evidence: Evidence;
}

export interface LockIn {
  min_term_months?: number | null;
  exit_fee?: string | null;
  notice_days?: number | null;
  auto_renews?: boolean | null;
  cancel_method?: string | null;
  proprietary_refills?: boolean | null;
}

export interface SmallPrintItem {
  field: string;
  value?: string | null;
  quote?: string | null;
  url?: string | null;
  source_step?: string | null;
}

export interface CompanyRecord {
  kind: string;
  summary: string;
  date: string;
  source_url: string;
}

export interface Company {
  brand?: string | null;
  parent?: string | null;
  ch_number?: string | null;
  match_via?: string | null;
  records?: CompanyRecord[];
}

export interface PriceDriftAdded {
  label: string;
  amount: number;
}

export interface PriceDrift {
  first_seen?: number | null;
  at_checkout?: number | null;
  added?: PriceDriftAdded[];
}

export interface ItemInfo {
  name?: string | null;
  brand?: string | null;
  seller?: string | null;
  url?: string | null;
  id?: string | null;
}

export interface CardStates {
  cost: CardState;
  lock_in: CardState;
  small_print: CardState;
  company: CardState;
  price_drift: CardState;
}

export interface AnalyseResult {
  purchase_types: string[];
  item: ItemInfo;
  cost_streams: CostStream[];
  lock_in: LockIn;
  small_print: SmallPrintItem[];
  company: Company;
  price_drift: PriceDrift;
  card_states: CardStates;
}

export type CardName = "item" | "cost" | "lock_in" | "small_print" | "company" | "price_drift";

export interface StreamCard {
  card: CardName;
  state: CardState;
  payload: unknown;
}

export interface Settings {
  horizon: 12 | 24;
  recordKinds: string[];
}

export const DEFAULT_SETTINGS: Settings = {
  horizon: 12,
  recordKinds: ["political_donations", "gender_pay_gap", "nmw_underpayment", "prompt_payment", "modern_slavery", "regulator_decisions"],
};

export interface AnalyseRequest {
  item: {
    name?: string | null;
    brand?: string | null;
    price?: number | null;
    seller?: string | null;
    url: string;
    id?: string | null;
  };
  purchase_type_signals: string[];
  links: { url: string; text: string; kind: string }[];
  page_text_snippets: string[];
  price_drift: { first_seen: number | null; current: number | null };
  install_id: string;
}
