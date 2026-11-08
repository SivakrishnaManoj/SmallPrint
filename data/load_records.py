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
LGBT_TXT = RAW / "LGBT rights.txt"
ABORTION_TXT = RAW / "Abortion rights.txt"
CLIMATE_XLSX = RAW / "climet data.xlsx"

# The ethics-consideration datasets (LGBTQ+ rights, abortion rights, climate) carry
# no Companies House number, so they are inserted with ch_number = NULL and joined to
# a company by exact (case-insensitive) organisation name only. See ADR 0002.
SBTI_URL = "https://sciencebasedtargets.org/companies-taking-action/"


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


def iso_date(raw: str) -> str | None:
    """"15/06/2026", "2024/04/02 10:11:12" or "2026-01-31T…" → "YYYY-MM-DD", else None.

    The panel formats and sorts records by ISO date, so every source is normalised here.
    """
    s = (raw or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})[/-](\d{2})[/-](\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


EC_DONATION_URL = "https://search.electoralcommission.org.uk/English/Donations/{}"


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
            date = iso_date(row.get("DateSubmitted", ""))
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
            date = iso_date(row.get("LastUpdated", ""))
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
            accepted = row.get("AcceptedDate", "").strip()
            summary = f"Donated {value} to {recipient} (accepted {accepted})."
            ec_ref = row.get("ECRef", "").strip()
            source_url = EC_DONATION_URL.format(ec_ref) if ec_ref else None
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (ch, name, "donation", iso_date(accepted), summary, source_url),
            )
            n += 1
    return n


def load_lgbt(cur: sqlite3.Cursor) -> int:
    """LGBTQ+ rights: companies a campaign-finance tracker lists as donors to US
    candidates/committees with records opposing LGBTQ+ rights. No CH number; name-joined.

    Neutral, source-attributed summary — evidence, not a verdict.
    """
    n = 0
    with open(LGBT_TXT, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("anti_lgbtq_donor") or "").strip().lower() != "yes":
                continue
            name = (row.get("company") or "").strip()
            if not name:
                continue
            src = (row.get("source") or "").strip()
            by = "Accountable for Equality" if src.lower().startswith("accountable") else "a published campaign-finance tracker"
            summary = (
                f"Listed by {by} as a corporate donor to US candidates or committees "
                "with voting records opposing LGBTQ+ rights."
            )
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (None, name, "lgbtq_rights", None, summary, None),
            )
            n += 1
    return n


def load_abortion(cur: sqlite3.Cursor) -> int:
    """Abortion rights: organisations a campaign-finance tracker lists as donors to
    US candidates/committees with records opposing abortion rights. No CH number; name-joined.
    """
    n = 0
    with open(ABORTION_TXT, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            # The source file has a handful of malformed rows (commas inside names shift
            # the columns); keep only clean "Yes" rows.
            if (row.get("Anti-Choice") or "").strip().lower() != "yes":
                continue
            name = (row.get("Company Name") or "").strip()
            if not name:
                continue
            summary = (
                "Listed by Accountable for Equality Action as a donor to US candidates "
                "or committees with voting records opposing abortion rights."
            )
            cur.execute(
                "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
                (None, name, "abortion_rights", None, summary, None),
            )
            n += 1
    return n


def _climate_summary(near: str, near_year, nz_status: str, nz_year) -> str | None:
    """A neutral, factual one-liner from the Science Based Targets initiative status columns."""
    parts: list[str] = []
    if near == "Validated Targets":
        s = "Has a Science Based Targets initiative (SBTi) validated near-term emissions reduction target"
        if near_year:
            s += f" (target year {near_year})"
        parts.append(s + ".")
    elif near == "Commitment to Set Targets":
        parts.append("Committed to set a Science Based Targets initiative (SBTi) near-term emissions reduction target.")
    elif near == "Commitment Removed":
        parts.append("A previously listed Science Based Targets initiative (SBTi) emissions target commitment has been removed.")
    if nz_status == "Validated Targets":
        s = "Has a validated net-zero target"
        if nz_year:
            s += f" (by {nz_year})"
        parts.append(s + ".")
    return " ".join(parts) if parts else None


def load_climate(cur: sqlite3.Cursor) -> int:
    """Climate: Science Based Targets initiative (SBTi) company target status. No CH number; name-joined."""
    try:
        import openpyxl
    except ImportError:
        print("(openpyxl not installed — skipping climate; pip install openpyxl to load it)", end=" ")
        return 0
    wb = openpyxl.load_workbook(CLIMATE_XLSX, read_only=True)
    ws = wb["Merged"]
    n = 0
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:  # header
            continue
        name = (str(row[1]).strip() if row[1] else "")
        if not name:
            continue
        summary = _climate_summary(
            (row[8] or "").strip(), row[10], (row[14] or "").strip(), row[15]
        )
        if not summary:
            continue
        updated = row[21]  # date_updated (datetime or None)
        date = updated.date().isoformat() if hasattr(updated, "date") else iso_date(str(updated or ""))
        cur.execute(
            "INSERT INTO records (ch_number, company_name, kind, date, summary, source_url) VALUES (?,?,?,?,?,?)",
            (None, name, "climate", date, summary, SBTI_URL),
        )
        n += 1
    wb.close()
    return n


def main(ethics_only: bool = False) -> None:
    # Non-destructive, per-kind refresh: each kind whose source file is present is
    # rebuilt from scratch; kinds whose source file is absent keep their existing rows.
    # This lets the ethics datasets be added without dropping kinds (e.g. donations)
    # whose source CSV is not checked into the repo.
    #
    # With ethics_only=True (--ethics-only), only the three ethics datasets are
    # (re)loaded and every other kind is left exactly as it is in the committed DB.
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for statement in CREATE_SQL.strip().split(";"):
        s = statement.strip()
        if s:
            cur.execute(s)

    def gpg_all(c: sqlite3.Cursor) -> int:
        return sum(load_gpg(c, p) for p in GPG_CSVS)

    base_jobs = [
        ("gender_pay_gap", bool(GPG_CSVS), gpg_all),
        ("modern_slavery", SLAVERY_CSV.exists(), load_slavery),
        ("donation", DONATIONS_CSV.exists(), load_donations),
    ]
    ethics_jobs = [
        ("lgbtq_rights", LGBT_TXT.exists(), load_lgbt),
        ("abortion_rights", ABORTION_TXT.exists(), load_abortion),
        ("climate", CLIMATE_XLSX.exists(), load_climate),
    ]
    jobs = ethics_jobs if ethics_only else base_jobs + ethics_jobs
    for kind, available, fn in jobs:
        if not available:
            kept = cur.execute("SELECT COUNT(*) FROM records WHERE kind=?", (kind,)).fetchone()[0]
            print(f"{kind}: source file missing — kept {kept:,} existing rows")
            continue
        print(f"Loading {kind}…", end=" ", flush=True)
        cur.execute("DELETE FROM records WHERE kind=?", (kind,))
        n = fn(cur)
        print(f"{n:,} rows")

    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    ch_coverage = cur.execute("SELECT COUNT(*) FROM records WHERE ch_number IS NOT NULL").fetchone()[0]
    print(f"\nTotal records: {total:,}")
    print(f"With CH number: {ch_coverage:,} ({100*ch_coverage//total}%)")
    print(f"Database: {DB_PATH}")
    con.close()


if __name__ == "__main__":
    import sys
    main(ethics_only="--ethics-only" in sys.argv)
