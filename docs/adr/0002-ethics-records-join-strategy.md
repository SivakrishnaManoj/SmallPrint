# ADR 0002: Ethics-consideration records — join strategy

**Date:** 2026-11-08
**Status:** Accepted
**Decider:** Ethics-consideration records (LGBTQ+ rights, abortion rights, climate)
**Extends:** ADR 0001 (modern slavery join strategy)

## Context

Three new datasets were added to the records index so the company card can
surface ethics considerations alongside the existing kinds:

| Kind | Source | Content |
|------|--------|---------|
| `lgbtq_rights` | `data/rawData/LGBT rights.txt` | Companies a campaign-finance tracker lists as donors to US candidates/committees with records opposing LGBTQ+ rights. |
| `abortion_rights` | `data/rawData/Abortion rights.txt` | Organisations the same tracker lists as donors to candidates/committees with records opposing abortion rights. |
| `climate` | `data/rawData/climet data.xlsx` | Science Based Targets initiative (SBTi) company target status. |

None of the three carry a Companies House number. The LGBTQ+ and abortion
datasets are US organisations; the SBTi dataset is global and has only partial
LEI coverage and no CH column. Under ADR 0001's rule ("primary join: CH
number") these rows would never reach a company card, because `_load_records`
only queried `WHERE ch_number = ?`.

ADR 0001 already *permitted* an exact-name fallback for its own name-only rows,
but the code never implemented it.

## Decision

**Implement the exact-name join ADR 0001 describes, and use it for these
datasets.** All three are inserted with `ch_number = NULL` and a
`company_name`. `_load_records` now runs two queries:

1. `WHERE ch_number = ?` — the trusted CH join (unchanged).
2. `WHERE ch_number IS NULL AND company_name = ? COLLATE NOCASE`, for the
   company's resolved **brand** and **parent** names.

The name query only touches `ch_number IS NULL` rows, so a name match can never
override, shadow or duplicate a CH-keyed record. Name matching runs **only after
a company has been identified** (a CH number was found); an unidentified brand
still returns "Brand not identified" with no records, exactly as before.

**No fuzzy matching.** Exact, case-insensitive name equality only — a
look-alike name can be a different legal entity. This is the same "quote or
null" discipline applied to company matching.

## Framing

The raw data uses advocacy labels (`anti_lgbtq_donor: yes`, `Anti-Choice:
Yes`). Those are restated as neutral, source-attributed facts — "Listed by
Accountable for Equality as a corporate donor to US candidates or committees
with voting records opposing LGBTQ+ rights." — in keeping with the project's
"evidence, not verdicts" rule. No verdict words; the summary names its source.

## Consequences

- The ethics datasets reach a company card only through an exact brand/parent
  name match. Coverage is therefore narrower and noisier than the CH-keyed
  kinds, and depends on the brand/parent the matcher resolves.
- US brands can surface via the page brand name (e.g. "Amazon") once the
  matcher identifies a company, which is the intended cross-reference.
- `records.sqlite` grows by ~50k rows (mostly the global SBTi set). The
  `idx_name` index already exists to keep name lookups fast.
- The datasets are opt-in-visible through the existing values filter and are on
  by default in `DEFAULT_SETTINGS.recordKinds`.
