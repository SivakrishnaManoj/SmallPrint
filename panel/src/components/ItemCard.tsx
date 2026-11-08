import { CardShell } from "./CardShell";
import type { ItemInfo, CardState } from "../types";

interface Props {
  item: ItemInfo;
  state: CardState;
  purchaseTypes: string[];
}

export function ItemCard({ item, state, purchaseTypes }: Props) {
  if (state === "n_a") {
    return (
      <CardShell title="Purchase" state="n_a">
        <p class="muted">No purchase detected on this page — try a product, subscription or checkout page.</p>
      </CardShell>
    );
  }
  return (
    <CardShell title="Purchase" state={state}>
      {item.name && <p class="item__name">{item.name}</p>}
      {item.brand && <p class="item__meta">Brand: <strong>{item.brand}</strong></p>}
      {item.seller && <p class="item__meta">Seller: {item.seller}</p>}
      {purchaseTypes.length > 0 && (
        <p class="item__meta">Type: {purchaseTypes.join(", ")}</p>
      )}
      {item.url && (
        <p class="item__meta">
          <a href={item.url} target="_blank" rel="noopener noreferrer" class="source-link">
            View page ↗
          </a>
        </p>
      )}
    </CardShell>
  );
}
