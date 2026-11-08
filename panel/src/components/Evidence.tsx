/**
 * A verbatim quote and the link it came from. Every found value is shown with one
 * (contracts/README.md rule 2, "quote or null"); without both, the value isn't shown.
 */
interface Props {
  quote?: string | null;
  url?: string | null;
  /** Link text; defaults to the source's domain. */
  label?: string;
  /** How the backend got the document (`source_step`). Set when it fell back to search. */
  sourceStep?: string | null;
}

/** The backend's label for a document it found with web search because the browser couldn't fetch the T&C page. */
export const SEARCH_SOURCE_STEP = "tavily_search";

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

export function Evidence({ quote, url, label, sourceStep }: Props) {
  if (!hasEvidence(quote, url)) return null;
  return (
    <div class="evidence">
      <blockquote class="evidence-quote">{quote}</blockquote>
      <a href={url!} class="source-link" target="_blank" rel="noopener noreferrer">
        {label ?? sourceName(url!)} ↗
      </a>
      {/* Story 28: say when the T&C page couldn't be fetched and this came from a web search instead. */}
      {sourceStep === SEARCH_SOURCE_STEP && (
        <span class="muted evidence-source-step"> · found by web search, not from the page's own T&C link</span>
      )}
    </div>
  );
}
