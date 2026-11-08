import { CardShell, LimitReached } from "./CardShell";
import { Evidence, hasEvidence } from "./Evidence";
import type { SmallPrintItem, CardState } from "../types";

interface Props {
  items: SmallPrintItem[];
  state: CardState;
}

/** "returns_window" → "Returns window"; labels that are already words are left alone. */
const label = (field: string) => (/_/.test(field) ? field.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : field);

export function SmallPrintCard({ items, state }: Props) {
  if (state === "n_a") {
    return <CardShell title="Small print" state="n_a"><p class="muted">Small print doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Small print" state="not_found"><p>Small print wasn't found for this item.</p></CardShell>;
  }
  if (state === "limit_reached") return <LimitReached title="Small print" what="Small print clauses" />;

  // Quote or null: a clause is shown only with its verbatim quote and link.
  const shown = items.filter((i) => hasEvidence(i.quote, i.url));

  return (
    <CardShell title="Small print" state={state}>
      {shown.length === 0 ? (
        <p>No small print clauses were found with a quote from the source.</p>
      ) : (
        <ul class="small-print__list">
          {shown.map((item, i) => (
            <li key={i} class="small-print__item" data-testid="small-print-row">
              <strong>{label(item.field)}</strong>
              {item.value && <span class="small-print__value">{item.value}</span>}
              <Evidence quote={item.quote} url={item.url} />
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}
