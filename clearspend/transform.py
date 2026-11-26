"""Roll cleaned transactions up into the two tables the analysis needs.

Three years of Virginia spending is millions of transactions. Nobody needs every
row in a dashboard, so the pipeline keeps two summaries instead:

* monthly: spending by agency, month, fund, category and expense type
* vendor_year: spending by agency, vendor and category for each fiscal year

That takes the data from gigabytes of CSV down to a few hundred thousand rows,
which fits in the free Azure SQL tier and loads fast in Power BI.
"""

from collections import Counter

import pandas as pd

from .clean import ACCOUNTING, INDIVIDUAL, NO_VENDOR, NOT_REPORTED

MONTHLY_KEYS = ["fiscal_year", "month", "branch", "secretariat", "agency", "fund", "category", "expense_type"]
VENDOR_KEYS = ["fiscal_year", "branch", "secretariat", "agency", "category", "vendor"]


def summarize_chunk(df: pd.DataFrame):
    df = df.assign(refund_amount=df["amount"].where(df["is_refund"], 0.0), txn_count=1)
    monthly = df.groupby(MONTHLY_KEYS, dropna=False, observed=True)[["amount", "refund_amount", "txn_count"]].sum()
    vendor = df.groupby(VENDOR_KEYS, dropna=False, observed=True)[["amount", "txn_count"]].sum()
    return monthly, vendor


def combine(parts, keys):
    """Add up the per-chunk summaries into one table."""
    if not parts:
        return pd.DataFrame(columns=keys)
    return pd.concat(parts).groupby(level=list(range(len(keys)))).sum().reset_index()


def quality_counts(df: pd.DataFrame, raw_rows: int) -> Counter:
    return Counter(
        raw_rows=raw_rows,
        kept_rows=len(df),
        dropped_rows=raw_rows - len(df),
        refund_rows=int(df["is_refund"].sum()),
        zero_rows=int((df["amount"] == 0).sum()),
        no_vendor_rows=int((df["vendor"] == NO_VENDOR).sum()),
        individual_rows=int((df["vendor"] == INDIVIDUAL).sum()),
        adjustment_rows=int((df["vendor"] == ACCOUNTING).sum()),
        not_reported_rows=int((df["vendor"] == NOT_REPORTED).sum()),
    )


def build_tables(frames):
    """frames yields (cleaned_df, raw_row_count). Returns monthly, vendor, quality."""
    monthly_parts, vendor_parts, quality = [], [], Counter()
    for df, raw_rows in frames:
        quality += quality_counts(df, raw_rows)
        m, v = summarize_chunk(df)
        monthly_parts.append(m)
        vendor_parts.append(v)
        # combine as we go so memory stays flat on big years
        if len(monthly_parts) >= 8:
            monthly_parts = [combine(monthly_parts, MONTHLY_KEYS).set_index(MONTHLY_KEYS)]
            vendor_parts = [combine(vendor_parts, VENDOR_KEYS).set_index(VENDOR_KEYS)]
    return combine(monthly_parts, MONTHLY_KEYS), combine(vendor_parts, VENDOR_KEYS), quality
