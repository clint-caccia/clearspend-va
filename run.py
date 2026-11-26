"""ClearSpend VA pipeline.

    python run.py                      # FY2024-FY2026, everything
    python run.py --years 2025 2026    # just some years
    python run.py --skip-download      # use zips already in data/raw

Steps: download -> clean -> summarize -> load database -> charts -> findings
-> (optional) AI briefing.

Set AZURE_SQL_CONNECTION_STRING to also load Azure SQL, and the AZURE_OPENAI_*
variables (see clearspend/ai_summary.py) for the AI briefing.
"""

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from clearspend import ai_summary, charts, clean, download, insights, load, transform

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
EXPORT = ROOT / "data" / "powerbi"


def process_year(fy: int, skip_download: bool):
    cached_m = PROCESSED / f"monthly_{fy}.parquet"
    cached_v = PROCESSED / f"vendor_{fy}.parquet"
    cached_q = PROCESSED / f"quality_{fy}.json"
    if cached_m.exists() and cached_v.exists() and cached_q.exists():
        print(f"FY{fy}: using cached summaries")
        return pd.read_parquet(cached_m), pd.read_parquet(cached_v), json.loads(cached_q.read_text())

    zip_path = RAW / download.NAME.format(fy=fy)
    if not zip_path.exists():
        if skip_download:
            raise SystemExit(f"missing {zip_path}")
        download.download_year(fy, str(RAW))

    start = time.time()
    monthly, vendor, quality = transform.build_tables(clean.iter_month_frames(str(zip_path)))
    quality = {k: int(quality.get(k, 0)) for k in
               ["raw_rows", "kept_rows", "dropped_rows", "refund_rows", "zero_rows", "no_vendor_rows", "individual_rows", "adjustment_rows", "not_reported_rows"]}
    quality["file_fiscal_year"] = fy
    print(f"FY{fy}: {quality['raw_rows']:,} rows in {time.time() - start:.0f}s "
          f"-> {len(monthly):,} monthly rows, {len(vendor):,} vendor rows")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(cached_m, index=False)
    vendor.to_parquet(cached_v, index=False)
    cached_q.write_text(json.dumps(quality, indent=2))
    return monthly, vendor, quality


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    monthly_parts, vendor_parts, quality = [], [], []
    for fy in args.years:
        m, v, q = process_year(fy, args.skip_download)
        monthly_parts.append(m)
        vendor_parts.append(v)
        quality.append(q)

    monthly = transform.combine([m.set_index(transform.MONTHLY_KEYS) for m in monthly_parts], transform.MONTHLY_KEYS)
    vendor = transform.combine([v.set_index(transform.VENDOR_KEYS) for v in vendor_parts], transform.VENDOR_KEYS)
    tables = load.build_star(monthly, vendor)

    EXPORT.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(EXPORT / f"{name}.csv", index=False)

    conn_str = os.environ.get("AZURE_SQL_CONNECTION_STRING")
    if conn_str:
        print("Loading Azure SQL...")
        load.load_azure(tables, conn_str)
    con = load.load_sqlite(tables, str(ROOT / "data" / "clearspend.db"))
    print("SQLite database: data/clearspend.db")
    # the analysis views too, so Power BI can use them without a database connection
    for view in ["v_agency_yoy", "v_vendor_concentration", "v_top_vendors"]:
        pd.read_sql(f"SELECT * FROM {view}", con).to_csv(EXPORT / f"{view}.csv", index=False)
    print("Power BI files: data/powerbi/")

    charts.make_all(con, ROOT / "docs" / "img")
    report = insights.build_report(con, quality)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "findings.md").write_text(report, encoding="utf-8")
    print("Wrote docs/findings.md")

    if ai_summary.configured():
        brief = ai_summary.summarize(report)
        (ROOT / "docs" / "ai_summary.md").write_text(
            "# AI briefing\n\nWritten by Azure OpenAI from docs/findings.md. Check numbers against that file.\n\n"
            + brief + "\n", encoding="utf-8")
        print("Wrote docs/ai_summary.md")
    else:
        print("Azure OpenAI not configured, skipping the AI briefing")


if __name__ == "__main__":
    main()
