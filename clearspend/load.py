"""Load the summary tables into a database as a small star schema.

    dim_agency (agency_id, agency, secretariat, branch)
    dim_vendor (vendor_id, vendor, vendor_type)
    fact_monthly (agency_id, fiscal_year, month, fund, category, expense_type,
                  amount, refund_amount, txn_count, fiscal_month)
    fact_vendor_year (agency_id, vendor_id, fiscal_year, category, amount, txn_count)

SQLite is the default so anyone can run this. Set AZURE_SQL_CONNECTION_STRING to
load into Azure SQL instead; the same SQL views work on both.
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd

from .clean import ACCOUNTING, INDIVIDUAL, NO_VENDOR, NOT_REPORTED

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def build_star(monthly: pd.DataFrame, vendor: pd.DataFrame):
    agencies = (
        pd.concat([monthly[["agency", "secretariat", "branch"]], vendor[["agency", "secretariat", "branch"]]])
        .drop_duplicates("agency")
        .sort_values("agency")
        .reset_index(drop=True)
    )
    agencies.insert(0, "agency_id", range(1, len(agencies) + 1))

    vendors = pd.DataFrame({"vendor": sorted(vendor["vendor"].unique())})
    vendors.insert(0, "vendor_id", range(1, len(vendors) + 1))
    special = {NO_VENDOR: "No vendor listed", INDIVIDUAL: "Individual (withheld)", ACCOUNTING: "Accounting adjustment",
               NOT_REPORTED: "Not reported"}
    vendors["vendor_type"] = vendors["vendor"].map(lambda v: special.get(v, "Organization"))

    agency_ids = dict(zip(agencies["agency"], agencies["agency_id"]))
    vendor_ids = dict(zip(vendors["vendor"], vendors["vendor_id"]))

    fact_monthly = monthly.assign(agency_id=monthly["agency"].map(agency_ids))[
        ["agency_id", "fiscal_year", "month", "fund", "category", "expense_type", "amount", "refund_amount", "txn_count"]
    ].copy()
    month = pd.to_datetime(fact_monthly["month"])
    fact_monthly["month"] = month.dt.strftime("%Y-%m-%d")
    # 1 = July ... 12 = June, so partial years can be compared month for month
    fact_monthly["fiscal_month"] = (month.dt.month - 7) % 12 + 1

    fact_vendor = vendor.assign(
        agency_id=vendor["agency"].map(agency_ids), vendor_id=vendor["vendor"].map(vendor_ids)
    )[["agency_id", "vendor_id", "fiscal_year", "category", "amount", "txn_count"]]

    for frame in (fact_monthly, fact_vendor):
        frame["fiscal_year"] = frame["fiscal_year"].astype(int)
        frame["amount"] = frame["amount"].round(2)
        frame["txn_count"] = frame["txn_count"].astype(int)
    fact_monthly["refund_amount"] = fact_monthly["refund_amount"].round(2)

    return {
        "dim_agency": agencies,
        "dim_vendor": vendors,
        "fact_monthly": fact_monthly,
        "fact_vendor_year": fact_vendor,
    }


def _views_sql():
    return (SQL_DIR / "views.sql").read_text(encoding="utf-8")


def load_sqlite(tables, path="data/clearspend.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    for name, frame in tables.items():
        frame.to_sql(name, con, index=False)
    con.executescript(
        """
        CREATE INDEX ix_fm_agency_year ON fact_monthly(agency_id, fiscal_year);
        CREATE INDEX ix_fv_agency_year ON fact_vendor_year(agency_id, fiscal_year);
        CREATE INDEX ix_fv_vendor ON fact_vendor_year(vendor_id);
        """
    )
    con.executescript(_views_sql())
    con.commit()
    return con


def load_azure(tables, connection_string):
    """Load into Azure SQL with SQLAlchemy + pyodbc (pip install sqlalchemy pyodbc)."""
    from sqlalchemy import create_engine, text  # imported here so SQLite users don't need it

    engine = create_engine(connection_string, fast_executemany=True)
    with engine.begin() as conn:
        for view in ["v_agency_year", "v_agency_yoy", "v_secretariat_year", "v_category_year",
                     "v_monthly_trend", "v_vendor_concentration", "v_top_vendors"]:
            conn.execute(text(f"DROP VIEW IF EXISTS {view}"))
    for name, frame in tables.items():
        frame.to_sql(name, engine, index=False, if_exists="replace", chunksize=5000)
    with engine.begin() as conn:
        for statement in _views_sql().split(";"):
            if statement.strip():
                conn.execute(text(statement))
    return engine
