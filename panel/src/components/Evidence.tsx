/**
 * A verbatim quote and the link it came from. Every found value is shown with one
 * (contracts/README.md rule 2, "quote or null"); without both, the value isn't shown.
 */
interface Props {
  quote?: string | null;
  url?: string | null;
  /** Link text; defaults to the source's domain. */
  label?: string;
}

export function hasEvidence(quote?: string | null, url?: string | null): boolean {
  return !!quote?.trim() && !!url?.trim();
}

export function sourceName(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Source";
  }
}

export function Evidence({ quote, url, label }: Props) {
  if (!hasEvidence(quote, url)) return null;
  return (
    <div class="evidence">
      <blockquote class="evidence-quote">{quote}</blockquote>
      <a href={url!} class="source-link" target="_blank" rel="noopener noreferrer">
        {label ?? sourceName(url!)} ↗
      </a>
    </div>
  );
}
