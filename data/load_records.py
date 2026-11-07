#!/usr/bin/env python3
"""Build data/records.sqlite from government CSVs/XLSXs in data/rawData/.

Usage:
    python data/load_records.py

Output: data/records.sqlite
"""
from __future__ import annotations
import csv
import re
import sqlite3
from pathlib import Path

import openpyxl

RAW = Path(__file__).parent / "rawData"
DB_PATH = Path(__file__).parent / "records.sqlite"

GPG_CSVS = sorted(RAW.glob("UK Gender Pay Gap Data*.csv"))
SLAVERY_CSV = RAW / "StatementSummaries2026.csv"
DONATIONS_CSV = RAW / "DonationData.csv"
PROMPT_CSVS = sorted(RAW.glob("*prompt-payments*.csv"))
NMW_XLSXS = sorted(RAW.glob("*.xlsx"), key=lambda p: (
    0 if "Round_" in p.name else 1 if "List_of_named" in p.name else 99
))


def normalise_ch(raw: str) -> str | None:
    """Normalise a Companies House number to 8-char uppercase string, or None."""
    s = raw.strip().upper().replace(" ", "")
    if not s:
        return None
    # Numeric only: zero-pad to 8 digits
    if s.isdigit():
        return s.zfill(8)
    # Scottish/NI prefix + digits (SC123456, NI123456, etc.)
    m = re.match(r"^([A-Z]{2})(\d+)$", s)
    if m:
        return m.group(1) + m.group(2).zfill(6)
    # Already looks like a valid CH number
    if re.match(r"^[A-Z0-9]{6,8}$", s):
        return s.ljust(8) if len(s) < 8 else s
    return None


def parse_gbp(value: str) -> str:
    """Return a clean £X,XXX string from Electoral Commission value column."""
    return value.strip().replace('"', "")


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ch_number   TEXT,
    company_name TEXT NOT NULL,
    kind        TEXT NOT NULL,
    date        TEXT,
    summary     TEXT NOT NULL,
    source_url  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ch ON records(ch_number);
CREATE INDEX IF NOT EXISTS idx_name ON records(company_name COLLATE NOCASE);
"""


def load_gpg(cur: sqlite3.Cursor, path: Path) -> int:
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ch = normalise_ch(row.get("CompanyNumber", ""))
            name = (row.get("CurrentName") or row.get("EmployerName", "")).strip()
            if not name:
                continue
            mean = row.get("DiffMeanHourlyPercent", "").strip()
            if not mean:
                continue
            try:
                pct = float(mean)
            except ValueError:
                continue
            direction = "in favour of men" if pct > 0 else "in favour of women" if pct < 0 else "no gap"
            year_label = re.search(r"(\d{4} to \d{4})", path.name)
            year_str = year_label.group(1) if year_label else "latest"
            summary = f"Mean gender pay gap of {abs(pct):.1f}% {direction} ({year_str} reporting year)."
            date = row.get("DateSubmitted", "").strip()[:10]
            source_url = row.get("CompanyLinkToGPGInfo", "").strip() or None
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (ch, name, "gender_pay_gap", date, summary, source_url),
            )
            n += 1
    return n


def load_slavery(cur: sqlite3.Cursor) -> int:
    n = 0
    with open(SLAVERY_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ch_raw = row.get("CompanyNumber", "").strip()
            # Edge case: OrganisationName is numeric (10 rows in this dataset)
            if not ch_raw:
                org = row.get("OrganisationName", "").strip()
                ch_raw = org if org.isdigit() else ""
            ch = normalise_ch(ch_raw)
            name = row.get("OrganisationName", "").strip()
            if not name or name.isdigit():
                name = row.get("ParentName", "").strip()
            if not name:
                continue
            start = row.get("StatementStartDate", "").strip()
            end = row.get("StatementEndDate", "").strip()
            period = f"{start} to {end}" if start and end else start or end or "unknown period"
            summary = f"Published a modern slavery and human trafficking statement covering {period}."
            date = row.get("LastUpdated", "").strip()[:10]
            source_url = row.get("StatementURL", "").strip() or None
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (ch, name, "modern_slavery", date, summary, source_url),
            )
            n += 1
    return n


def load_nmw(cur: sqlite3.Cursor, path: Path) -> int:
    """Load NMW named-employer spreadsheet.

    Both files have a title banner in row 1, blank row 2, and real headers in row 3.
    No Companies House number is present — records are matched by name only.
    """
    n = 0
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = iter(ws.iter_rows(values_only=True))

    # Skip banner rows until we find the header row (col B = "Employer / Company name")
    headers: tuple | None = None
    for row in rows:
        if row[1] == "Employer / Company name":
            headers = row
            break
    if headers is None:
        wb.close()
        return 0

    col = {v: i for i, v in enumerate(headers) if v is not None}

    for row in rows:
        name = row[col.get("Employer / Company name", 1)]
        if not name:
            continue
        name = str(name).strip()
        if not name:
            continue

        arrears_raw = row[col.get("Arrears", 10)]
        workers_raw = row[col.get("Number of Workers", 11)]
        start_raw = row[col.get("Start of Arrears Period", 13)]
        end_raw = row[col.get("End of Arrears Period", 14)]

        try:
            arrears = float(arrears_raw) if arrears_raw is not None else None
        except (TypeError, ValueError):
            arrears = None

        try:
            workers = int(workers_raw) if workers_raw is not None else None
        except (TypeError, ValueError):
            workers = None

        def _fmt_date(d) -> str:
            if d is None:
                return ""
            if hasattr(d, "strftime"):
                return d.strftime("%Y-%m-%d")
            return str(d)[:10]

        start_str = _fmt_date(start_raw)
        end_str = _fmt_date(end_raw)
        period = f"{start_str} to {end_str}" if start_str and end_str else start_str or end_str or "unknown period"

        parts = ["Named for National Minimum Wage underpayment"]
        if arrears is not None:
            parts.append(f"of £{arrears:,.2f}")
        if workers is not None:
            parts.append(f"to {workers:,} workers")
        parts.append(f"(arrears period: {period}).")
        summary = " ".join(parts)

        cur.execute(
            "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
            (None, name, "nmw_underpayment", end_str, summary, None),
        )
        n += 1

    wb.close()
    return n


def load_prompt_payments(cur: sqlite3.Cursor) -> int:
    """Load Prompt Payment Code filings, keeping only the latest report per company."""
    # Collect all rows, then deduplicate to latest filing per CH number.
    latest: dict[str, dict] = {}  # ch_number -> row dict

    for path in PROMPT_CSVS:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ch = normalise_ch(row.get("Company number", ""))
                if not ch:
                    continue
                filing_date = row.get("Filing date", "").strip()
                existing = latest.get(ch)
                if existing is None or filing_date > existing.get("Filing date", ""):
                    latest[ch] = row

    n = 0
    for ch, row in latest.items():
        name = row.get("Company", "").strip()
        if not name:
            continue

        avg_days_raw = row.get("Average time to pay", "").strip()
        pct_30_raw = row.get("% Invoices paid within 30 days", "").strip()
        pct_60_raw = row.get("% Invoices paid later than 60 days", "").strip()
        start = row.get("Start date", "").strip()[:10]
        end = row.get("End date", "").strip()[:10]
        filing_date = row.get("Filing date", "").strip()[:10]
        url = row.get("URL", "").strip() or None

        parts = ["Prompt payment report:"]
        if pct_30_raw:
            parts.append(f"paid {pct_30_raw}% of invoices within 30 days")
        if avg_days_raw:
            parts.append(f"(average {avg_days_raw} days)")
        if pct_60_raw and pct_60_raw != "0":
            parts.append(f"; {pct_60_raw}% paid later than 60 days")
        period = f"{start} to {end}" if start and end else start or end or ""
        if period:
            parts.append(f"— period {period}.")
        summary = " ".join(parts)

        cur.execute(
            "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
            (ch, name, "prompt_payment", filing_date, summary, url),
        )
        n += 1

    return n


def load_donations(cur: sqlite3.Cursor) -> int:
    n = 0
    with open(DONATIONS_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            # Only company donors
            if row.get("DonorStatus", "").strip().lower() != "company":
                continue
            ch = normalise_ch(row.get("CompanyRegistrationNumber", ""))
            name = row.get("DonorName", "").strip()
            if not name:
                continue
            recipient = row.get("RegulatedEntityName", "").strip()
            value = parse_gbp(row.get("Value", ""))
            date = row.get("AcceptedDate", "").strip()
            summary = f"Donated {value} to {recipient} (accepted {date})."
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (ch, name, "donation", date, summary, None),
            )
            n += 1
    return n


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for statement in CREATE_SQL.strip().split(";"):
        s = statement.strip()
        if s:
            cur.execute(s)

    gpg_total = 0
    for gpg_path in GPG_CSVS:
        print(f"Loading gender pay gap ({gpg_path.name})…", end=" ", flush=True)
        n = load_gpg(cur, gpg_path)
        print(f"{n:,} rows")
        gpg_total += n

    print("Loading modern slavery…", end=" ", flush=True)
    n = load_slavery(cur)
    print(f"{n:,} rows")

    print("Loading donations…", end=" ", flush=True)
    n = load_donations(cur)
    print(f"{n:,} rows")

    nmw_total = 0
    for nmw_path in NMW_XLSXS:
        if any(kw in nmw_path.name for kw in ("List_of_named", "Round_")):
            print(f"Loading NMW named employers ({nmw_path.name})…", end=" ", flush=True)
            n = load_nmw(cur, nmw_path)
            print(f"{n:,} rows")
            nmw_total += n

    if PROMPT_CSVS:
        print(f"Loading prompt payment reports ({len(PROMPT_CSVS)} file(s))…", end=" ", flush=True)
        n = load_prompt_payments(cur)
        print(f"{n:,} companies (latest report each)")
    else:
        n = 0
    prompt_total = n

    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    ch_coverage = cur.execute("SELECT COUNT(*) FROM records WHERE ch_number IS NOT NULL").fetchone()[0]
    print(f"\nTotal records: {total:,}")
    print(f"With CH number: {ch_coverage:,} ({100*ch_coverage//total}%)")
    print("By kind:")
    for kind, count in cur.execute("SELECT kind, COUNT(*) FROM records GROUP BY kind ORDER BY kind"):
        print(f"  {kind}: {count:,}")
    print(f"Database: {DB_PATH}")
    con.close()


if __name__ == "__main__":
    main()
