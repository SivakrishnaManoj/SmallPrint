import { CardShell } from "./CardShell";
import type { SmallPrintItem, CardState } from "../types";

interface Props {
  items: SmallPrintItem[];
  state: CardState;
}

export function SmallPrintCard({ items, state }: Props) {
  if (state === "n_a") {
    return <CardShell title="Small print" state="n_a"><p class="muted">Small print doesn't apply to this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Small print" state="not_found"><p>Small print wasn't found for this item.</p></CardShell>;
  }

  return (
    <CardShell title="Small print" state={state}>
      {items.length === 0 ? (
        <p>No small print clauses were found.</p>
      ) : (
        <ul class="small-print__list">
          {items.map((item, i) => (
            <li key={i} class="small-print__item">
              <strong>{item.field}</strong>
              {item.value && <span>: {item.value}</span>}
              {item.quote && <blockquote class="evidence-quote">{item.quote}</blockquote>}
              {item.url && (
                <a href={item.url} class="source-link" target="_blank" rel="noopener noreferrer">Source ↗</a>
              )}
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}
