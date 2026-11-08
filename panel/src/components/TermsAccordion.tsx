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
  value: string | null;
  quote: string | null;
  url: string | null;
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
      const ev = lockIn.evidence?.find((e) => e.field === field && hasEvidence(e.quote, e.url));
      items.push({ id: `li_${field}`, label, value, quote: ev?.quote ?? null, url: ev?.url ?? null });
    }
  }

  if (smallPrint) {
    for (const item of smallPrint) {
      if (hasEvidence(item.quote, item.url)) {
        const label = /_/.test(item.field)
          ? item.field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
          : item.field;
        items.push({ id: `sp_${item.field}`, label, value: item.value ?? null, quote: item.quote ?? null, url: item.url ?? null });
      }
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

        return (
          <Fragment key={item.id}>
            <div
              class={[
                "sp-acc-row",
                isOpen ? "sp-acc-row--open" : "",
                !canExpand ? "sp-acc-row--disabled" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => canExpand && toggle(item.id)}
              role={canExpand ? "button" : undefined}
              aria-expanded={canExpand ? isOpen : undefined}
            >
              <span>{item.label}</span>
              <div class="sp-acc-row__right">
                <span class={item.value ? "sp-acc-row__value" : "sp-acc-row__value sp-acc-row__value--muted"}>
                  {item.value ?? "Not found"}
                </span>
                {canExpand && <span class="sp-acc-row__chev">{isOpen ? "▾" : "▸"}</span>}
              </div>
            </div>
            {isOpen && canExpand && (
              <div class="sp-acc-quote">
                "{item.quote}"{" "}
                <a href={item.url!} target="_blank" rel="noopener noreferrer">
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
