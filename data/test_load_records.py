"""J2 (#8): records index tests.

Done when:
  * records.sqlite builds from one command.
  * A lookup by CH number returns dated records with source URLs.
  * The modern slavery decision is written down (see docs/adr/0001-...).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB = Path(__file__).parent / "records.sqlite"
LOADER = Path(__file__).parent / "load_records.py"


@pytest.fixture(scope="module")
def db():
    if not DB.exists():
        pytest.skip("records.sqlite not built — run: python data/load_records.py")
    return sqlite3.connect(DB)


def test_database_built_from_one_command():
    """The DB must exist and be non-empty; build it with `python data/load_records.py`."""
    assert DB.exists(), "records.sqlite missing — run: python data/load_records.py"
    con = sqlite3.connect(DB)
    count = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    con.close()
    assert count > 10_000, f"Expected >10,000 rows, got {count}"


def test_all_three_kinds_are_present(db):
    kinds = {r[0] for r in db.execute("SELECT DISTINCT kind FROM records")}
    assert "gender_pay_gap" in kinds
    assert "donation" in kinds
    assert "modern_slavery" in kinds


def test_ch_number_lookup_returns_dated_records_with_source_urls(db):
    """Core requirement: a CH lookup must return date and source_url on every row."""
    # Find any CH number that has records across at least one kind.
    ch = db.execute(
        "SELECT ch_number FROM records WHERE ch_number IS NOT NULL GROUP BY ch_number "
        "HAVING COUNT(*) >= 1 LIMIT 1"
    ).fetchone()[0]

    rows = db.execute(
        "SELECT kind, summary, date, source_url FROM records WHERE ch_number = ?",
        (ch,),
    ).fetchall()

    assert rows, f"No records for ch_number={ch}"
    for kind, summary, date, source_url in rows:
        assert kind, "kind is blank"
        assert summary, "summary is blank"
        assert date, f"date is blank for kind={kind} ch={ch}"
        # Donations link to their Electoral Commission record page.
        if kind in ("gender_pay_gap", "modern_slavery", "donation"):
            assert source_url, f"source_url missing for kind={kind} ch={ch}"


def test_gender_pay_gap_records_have_percentage_in_summary(db):
    row = db.execute(
        "SELECT summary FROM records WHERE kind='gender_pay_gap' LIMIT 1"
    ).fetchone()
    assert row and "%" in row[0]


def test_modern_slavery_records_have_statement_period(db):
    row = db.execute(
        "SELECT summary FROM records WHERE kind='modern_slavery' AND ch_number IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row and "statement" in row[0].lower()


def test_modern_slavery_null_ch_rows_exist(db):
    """The 835 name-only rows must be present (ch_number = NULL, not dropped)."""
    count = db.execute(
        "SELECT COUNT(*) FROM records WHERE kind='modern_slavery' AND ch_number IS NULL"
    ).fetchone()[0]
    assert count > 0, "Expected some modern_slavery rows with ch_number=NULL"


def test_ch_number_index_exists(db):
    indexes = {r[1] for r in db.execute("PRAGMA index_list(records)")}
    assert "idx_ch" in indexes


def test_no_verdict_words_in_summaries(db):
    verdict_words = ["unethical", "illegal", "broke the law", "corrupt", "guilty"]
    for word in verdict_words:
        count = db.execute(
            "SELECT COUNT(*) FROM records WHERE LOWER(summary) LIKE ?",
            (f"%{word}%",),
        ).fetchone()[0]
        assert count == 0, f"Verdict word '{word}' found in {count} summaries"


def test_adr_is_written():
    adr = Path(__file__).parent.parent / "docs" / "adr" / "0001-modern-slavery-join-strategy.md"
    assert adr.exists(), "ADR 0001 not found — write docs/adr/0001-modern-slavery-join-strategy.md"
    text = adr.read_text(encoding="utf-8")
    assert "CompanyNumber" in text, "ADR must mention the CompanyNumber column finding"
    assert "exact" in text.lower(), "ADR must describe the exact-name fallback decision"


# --- Dates are ISO and every record has a link (the panel sorts and formats ISO dates;
# --- the 40-URL test counts a record without a link as a wrong value).

def _loader():
    import importlib.util
    spec = importlib.util.spec_from_file_location("load_records", LOADER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("raw, iso", [
    ("15/06/2026", "2026-06-15"),           # modern slavery LastUpdated, EC AcceptedDate
    ("2024/04/02 10:11:12", "2024-04-02"),  # gender pay gap DateSubmitted
    ("2024/04/02", "2024-04-02"),
    ("2026-01-31T00:00:00", "2026-01-31"),
    ("", None),
    ("not a date", None),
])
def test_iso_date(raw, iso):
    assert _loader().iso_date(raw) == iso


def test_record_dates_are_iso(db):
    bad = db.execute(
        "SELECT kind, date FROM records WHERE date IS NOT NULL "
        "AND date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' LIMIT 5"
    ).fetchall()
    assert not bad, f"non-ISO dates: {bad}"


def test_donations_link_to_their_electoral_commission_record(db):
    missing = db.execute(
        "SELECT COUNT(*) FROM records WHERE kind='donation' AND (source_url IS NULL OR source_url = '')"
    ).fetchone()[0]
    assert missing == 0
    url = db.execute("SELECT source_url FROM records WHERE kind='donation' LIMIT 1").fetchone()[0]
    assert url.startswith("https://search.electoralcommission.org.uk/English/Donations/")
