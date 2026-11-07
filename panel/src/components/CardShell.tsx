import type { ComponentChildren } from "preact";
import type { CardState } from "../types";

interface Props {
  title: string;
  state: CardState;
  children: ComponentChildren;
}

function stateBadge(state: CardState) {
  const map: Record<CardState, { label: string; cls: string }> = {
    found: { label: "Found", cls: "badge badge--found" },
    estimated: { label: "Estimated", cls: "badge badge--estimated" },
    not_found: { label: "Not found", cls: "badge badge--not-found" },
    n_a: { label: "N/A", cls: "badge badge--na" },
  };
  return map[state] ?? map.not_found;
}

export function CardShell({ title, state, children }: Props) {
  const badge = stateBadge(state);
  return (
    <section class={`card card--${state}`}>
      <div class="card__header">
        <h2 class="card__title">{title}</h2>
        <span class={badge.cls}>{badge.label}</span>
      </div>
      <div class="card__body">{children}</div>
    </section>
  );
}
