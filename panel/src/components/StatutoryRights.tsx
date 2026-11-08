import { rightsFor } from "../statutory/rights";

interface Props {
  purchaseTypes: string[];
}

/**
 * Statutory rights, kept apart from the evidence cards: these come from the law, not from
 * the seller's terms, and are general information rather than advice.
 */
export function StatutoryRights({ purchaseTypes }: Props) {
  const rights = rightsFor(purchaseTypes);
  return (
    <section class="statutory" aria-labelledby="statutory-title" data-testid="statutory-rights">
      <div class="statutory__header">
        <h2 id="statutory-title" class="card__title">Your statutory rights</h2>
        <span class="badge badge--na">Not legal advice</span>
      </div>
      <p class="statutory__intro">
        General information about UK consumer law, not legal advice. These rights apply whatever the seller's terms say.
      </p>
      <ul class="statutory__list">
        {rights.map((r) => (
          <li key={r.id} class="statutory__item">
            <strong>{r.title}</strong>
            <p>{r.text}</p>
            <a href={r.source.url} class="source-link" target="_blank" rel="noopener noreferrer">{r.source.label} ↗</a>
          </li>
        ))}
      </ul>
      <p class="muted statutory__more">
        More from{" "}
        <a href="https://www.gov.uk/consumer-protection-rights" class="source-link" target="_blank" rel="noopener noreferrer">GOV.UK ↗</a>
      </p>
    </section>
  );
}
