# ADR 0001: Modern slavery statements — join strategy

**Date:** 2026-11-08  
**Status:** Accepted  
**Decider:** J2 (Records index)

## Context

The J2 ticket required checking whether the modern slavery statement CSV
(`data/rawData/StatementSummaries2026.csv`) carries a Companies House number,
so we could decide whether to join on CH number or fall back to exact name.

## Finding

The CSV has a `CompanyNumber` column. Sampling the 11,839 rows:

| Metric | Count |
|--------|-------|
| Total rows | 11,839 |
| Rows with CompanyNumber | 11,004 (93%) |
| Rows without CompanyNumber | 835 (7%) |

The 835 rows without a number are mostly charities, public bodies and
overseas-registered entities that have no UK Companies House entry.

## Decision

**Primary join: Companies House number.**  
For the 11,004 rows that carry a `CompanyNumber`, records are keyed on the
normalised CH number (8-char uppercase, zero-padded for numeric-only values).

**Fallback for the 835 rows without a CH number: exact organisation name.**  
These rows are inserted with `ch_number = NULL`. The company matcher (J5) may
surface them via an exact name match, but they will never be joined to a
CH-matched company via a fuzzy or partial name — only a verified CH number
creates a trusted link.

**No fuzzy matching.**  
A name that looks similar can belong to a different legal entity. The rule
"quote or null" applies to company matching as much as to T&C extraction.

## Consequences

- 93% of modern slavery records join cleanly on CH number alongside gender pay
  gap and donations data.
- The 7% name-only records may still appear for companies matched by name in J5,
  but only on an exact (case-insensitive) name match.
- The `records` table carries both `ch_number` (nullable) and `company_name`
  columns, with indexes on both, to support both join paths.
