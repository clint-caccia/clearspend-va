import sqlite3

import pandas as pd

from clearspend import clean, load, transform


def sample_frame():
    rows = [
        # agency, secretariat, fy, date, category, amount, vendor
        ("Dept A", "FINANCE", 2024, "07-15-23", "SUPPLIES", 100.0, "ACME SUPPLY"),
        ("Dept A", "FINANCE", 2024, "08-15-23", "SUPPLIES", 300.0, "BETA SUPPLY"),
        ("Dept A", "FINANCE", 2025, "07-15-24", "SUPPLIES", 500.0, "ACME SUPPLY"),
        ("Dept A", "FINANCE", 2025, "07-20-24", "SUPPLIES", -50.0, "ACME SUPPLY"),
        ("Dept B", "EDUCATION", 2025, "09-01-24", "PERSONAL SERVICES", 1000.0, ""),
        ("Dept B", "EDUCATION", 2025, "09-02-24", "TRAVEL", 40.0, "DOE,JANE"),
    ]
    raw = pd.DataFrame(
        [{"BRANCH_NAME": "EXECUTIVE", "SECRETARIAT_NAME": s, "AGENCY_NAME": a, "FUND_NAME": "GENERAL",
          "CATEGORY_NAME": c, "EXPENSE_TYPE": "x", "TRANS_DATE": d, "FISCAL_YEAR": str(fy),
          "AMOUNT": str(amt), "VENDOR_NAME": v} for a, s, fy, d, c, amt, v in rows]
    )
    return clean.clean_frame(raw)


def build_db(tmp_path):
    df = sample_frame()
    monthly, vendor, quality = transform.build_tables([(df, len(df))])
    tables = load.build_star(monthly, vendor)
    return load.load_sqlite(tables, str(tmp_path / "t.db")), quality


def test_totals_and_refunds(tmp_path):
    con, quality = build_db(tmp_path)
    rows = dict(con.execute(
        "SELECT agency || ':' || fiscal_year, total_spend FROM v_agency_year").fetchall())
    assert rows == {"Dept A:2024": 400.0, "Dept A:2025": 450.0, "Dept B:2025": 1040.0}
    assert quality["refund_rows"] == 1
    assert quality["individual_rows"] == 1
    assert quality["no_vendor_rows"] == 1


def test_yoy_change(tmp_path):
    con, _ = build_db(tmp_path)
    change, pct = con.execute(
        "SELECT change, pct_change FROM v_agency_yoy WHERE agency='Dept A' AND fiscal_year=2025").fetchone()
    assert change == 50.0
    assert abs(pct - 0.125) < 1e-9


def test_concentration_ignores_people_and_payroll(tmp_path):
    con, _ = build_db(tmp_path)
    rows = con.execute(
        "SELECT agency, fiscal_year, vendor_count, top_vendor_share, hhi FROM v_vendor_concentration ORDER BY 1, 2"
    ).fetchall()
    # Dept B only paid payroll and a person, so it has no organization vendors
    assert [r[0] for r in rows] == ["Dept A", "Dept A"]
    fy24 = rows[0]
    assert fy24[2] == 2 and abs(fy24[3] - 0.75) < 1e-9
    assert abs(fy24[4] - (0.75 ** 2 + 0.25 ** 2) * 10000) < 1e-6


def test_no_person_names_in_vendor_table(tmp_path):
    con, _ = build_db(tmp_path)
    names = [r[0] for r in con.execute("SELECT vendor FROM dim_vendor")]
    assert "DOE,JANE" not in names and "DOE JANE" not in names
    assert clean.INDIVIDUAL in names


def test_fiscal_month_runs_july_to_june(tmp_path):
    con, _ = build_db(tmp_path)
    rows = dict(con.execute("SELECT DISTINCT substr(month, 6, 2), fiscal_month FROM fact_monthly").fetchall())
    assert rows["07"] == 1 and rows["08"] == 2 and rows["09"] == 3
