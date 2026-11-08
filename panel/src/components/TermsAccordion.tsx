import { useState } from "preact/hooks";
import { Fragment } from "preact";
import type { LockIn, LockInField, SmallPrintItem } from "../types";
import { hasEvidence, sourceName } from "./Evidence";

interface Props {
  lockIn?: LockIn | null;
  smallPrint?: SmallPrintItem[];
}

interface AccItem {
  id: string;
  label: string;
  value: string;
  quote: string | null;
  url: string | null;
  kind: "lock_in" | "small_print";
}

const LOCKIN_FIELDS: { field: LockInField; label: string; show: (l: LockIn) => string | null }[] = [
  { field: "proprietary_refills", label: "Refills", show: (l) => l.proprietary_refills != null ? (l.proprietary_refills ? "Own brand only" : "Any brand") : null },
  { field: "min_term_months", label: "Minimum term", show: (l) => l.min_term_months != null ? `${l.min_term_months} months` : null },
  { field: "exit_fee", label: "Exit fee", show: (l) => l.exit_fee ?? null },
  { field: "notice_days", label: "Notice to cancel", show: (l) => l.notice_days != null ? `${l.notice_days} days` : null },
  { field: "auto_renews", label: "Auto-renews", show: (l) => l.auto_renews != null ? (l.auto_renews ? "Yes" : "No") : null },
  { field: "cancel_method", label: "How to cancel", show: (l) => l.cancel_method ?? null },
];

function buildItems(lockIn?: LockIn | null, smallPrint?: SmallPrintItem[]): AccItem[] {
  const items: AccItem[] = [];

  if (lockIn) {
    for (const { field, label, show } of LOCKIN_FIELDS) {
      const value = show(lockIn);
      if (value === null) continue;
      const ev = lockIn.evidence?.find((e) => e.field === field && hasEvidence(e.quote, e.url));
      items.push({ id: `li_${field}`, label, value, quote: ev?.quote ?? null, url: ev?.url ?? null, kind: "lock_in" });
    }
  }

  if (smallPrint) {
    for (const item of smallPrint) {
      if (!hasEvidence(item.quote, item.url) || item.value == null) continue;
      const label = /_/.test(item.field)
        ? item.field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
        : item.field;
      items.push({ id: `sp_${item.field}`, label, value: item.value, quote: item.quote ?? null, url: item.url ?? null, kind: "small_print" });
    }
  }

  return items;
}

export function TermsAccordion({ lockIn, smallPrint }: Props) {
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  const items = buildItems(lockIn, smallPrint);
  if (items.length === 0) return null;

  function toggle(id: string) {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div class="sp-accordion">
      {items.map((item) => {
        const canExpand = hasEvidence(item.quote, item.url);
        const isOpen = openIds.has(item.id);
        const testId = item.kind === "lock_in" ? "lock-in-row" : "small-print-row";

        return (
          <Fragment key={item.id}>
            <div
              class={["sp-acc-row", isOpen ? "sp-acc-row--open" : "", !canExpand ? "sp-acc-row--disabled" : ""].filter(Boolean).join(" ")}
              data-testid={testId}
              onClick={() => canExpand && toggle(item.id)}
              role={canExpand ? "button" : undefined}
              aria-expanded={canExpand ? isOpen : undefined}
            >
              <span class="sp-acc-row__label">{item.label}</span>
              <div class="sp-acc-row__right">
                <span class="sp-acc-row__value">{item.value}</span>
                {canExpand && <span class="sp-acc-row__chev">{isOpen ? "▾" : "▸"}</span>}
              </div>
            </div>
            {isOpen && canExpand && (
              <div class="sp-acc-quote">
                <blockquote class="evidence-quote">{item.quote}</blockquote>
                <a href={item.url!} class="source-link" target="_blank" rel="noopener noreferrer">
                  {sourceName(item.url!)} ↗
                </a>
              </div>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
