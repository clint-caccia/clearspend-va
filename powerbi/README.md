# Power BI dashboard

The dashboard reads the files `run.py` writes to `data/powerbi/` (or the same tables in Azure SQL).

## 1. Load the data

**From the CSV files (no Azure needed)**

1. Open Power BI Desktop and pick **Get data > Text/CSV**.
2. Load `dim_agency.csv`, `dim_vendor.csv`, `fact_monthly.csv` and `fact_vendor_year.csv`.
3. Optional: also load `v_agency_yoy.csv`, `v_vendor_concentration.csv` and `v_top_vendors.csv`.
   These are the SQL views, already calculated.

**From Azure SQL**

1. **Get data > Azure > Azure SQL Database**.
2. Server is `<your-server>.database.windows.net`, database is the one you created.
3. Pick the four tables and the `v_` views.

## 2. Set up the model

In **Model view**, make sure these relationships exist (Power BI usually finds them):

| From | To | Type |
|---|---|---|
| `dim_agency[agency_id]` | `fact_monthly[agency_id]` | one to many |
| `dim_agency[agency_id]` | `fact_vendor_year[agency_id]` | one to many |
| `dim_vendor[vendor_id]` | `fact_vendor_year[vendor_id]` | one to many |

Then create the `FiscalYears` table and the measures from `measures.dax`, and relate
`FiscalYears[fiscal_year]` to `fiscal_year` in both fact tables (one to many).

Set `fact_monthly[month]` to the **Date** data type.

## 3. Build the pages

Apply the theme first: **View > Themes > Browse for themes > clearspend_theme.json**.

**Page 1: Overview**
- Slicers across the top: `FiscalYears[fiscal_year]`, `dim_agency[secretariat]`
- Cards: Total Spend, YoY %, Transactions, Months Reported
- Bar chart: `dim_agency[secretariat]` by Total Spend
- Line chart: `fact_monthly[month]` by Total Spend
- Table: `dim_agency[agency]`, Total Spend, Prior Year Spend, YoY Change, YoY %

**Page 2: Vendors**
- Slicer: `FiscalYears[fiscal_year]`
- Table: `dim_vendor[vendor]`, Organization Vendor Spend, sorted high to low, filtered to
  `dim_vendor[vendor_type] = Organization`
- Table from `v_vendor_concentration`: agency, vendor_count, top_vendor_share, hhi
  (filter `vendor_count >= 10` to skip pass-through accounts)

**Page 3: Data notes**
- Card per vendor type (`dim_vendor[vendor_type]` as a slicer or matrix) so it's clear how much
  money is payroll, ledger adjustments, unreported detail or withheld individuals.

Save as `powerbi/clearspend_va.pbix` and export a screenshot of each page to `docs/img/`.
