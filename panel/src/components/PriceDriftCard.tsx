import { CardShell } from "./CardShell";
import type { PriceDrift, CardState } from "../types";

interface Props {
  priceDrift: PriceDrift;
  state: CardState;
}

export function PriceDriftCard({ priceDrift, state }: Props) {
  if (state === "n_a") {
    return <CardShell title="Price drift" state="n_a"><p class="muted">No price comparison available for this page.</p></CardShell>;
  }
  if (state === "not_found") {
    return <CardShell title="Price drift" state="not_found"><p>Price drift data wasn't found for this item.</p></CardShell>;
  }

  const { first_seen, at_checkout, added = [] } = priceDrift;
  const increase = at_checkout != null && first_seen != null ? at_checkout - first_seen : null;

  return (
    <CardShell title="Price drift" state={state}>
      {first_seen != null && <p>First seen: <strong>£{first_seen.toFixed(2)}</strong></p>}
      {at_checkout != null && <p>At checkout: <strong>£{at_checkout.toFixed(2)}</strong></p>}
      {increase != null && increase > 0 && (
        <p class="price-increase">↑ £{increase.toFixed(2)} added since first seen</p>
      )}
      {added.length > 0 && (
        <ul class="added-fees">
          {added.map((a, i) => (
            <li key={i}>{a.label}: <strong>+£{a.amount.toFixed(2)}</strong></li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}
