#!/usr/bin/env python3
"""Build data/records.sqlite from the three government CSVs in data/rawData/.

Usage:
    python data/load_records.py

Output: data/records.sqlite
"""
from __future__ import annotations
import csv
import re
import sqlite3
from pathlib import Path

RAW = Path(__file__).parent / "rawData"
DB_PATH = Path(__file__).parent / "records.sqlite"

GPG_CSVS = sorted(RAW.glob("UK Gender Pay Gap Data*.csv"))
SLAVERY_CSV = RAW / "StatementSummaries2026.csv"
DONATIONS_CSV = RAW / "DonationData.csv"


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

    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    ch_coverage = cur.execute("SELECT COUNT(*) FROM records WHERE ch_number IS NOT NULL").fetchone()[0]
    print(f"\nTotal records: {total:,}")
    print(f"With CH number: {ch_coverage:,} ({100*ch_coverage//total}%)")
    print(f"Database: {DB_PATH}")
    con.close()


if __name__ == "__main__":
    main()
