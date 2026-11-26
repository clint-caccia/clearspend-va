-- Analysis views. Written in plain SQL that runs on both SQLite and Azure SQL
-- (no LIMIT/TOP, no engine-specific functions).

-- Total spending for each agency in each fiscal year
CREATE VIEW v_agency_year AS
SELECT
    a.agency,
    a.secretariat,
    a.branch,
    f.fiscal_year,
    SUM(f.amount)        AS total_spend,
    SUM(f.refund_amount) AS refunds,
    SUM(f.txn_count)     AS transactions
FROM fact_monthly f
JOIN dim_agency a ON a.agency_id = f.agency_id
GROUP BY a.agency, a.secretariat, a.branch, f.fiscal_year;

-- Year-over-year change per agency, using LAG to grab the prior year
CREATE VIEW v_agency_yoy AS
SELECT
    agency,
    secretariat,
    fiscal_year,
    total_spend,
    LAG(total_spend) OVER (PARTITION BY agency ORDER BY fiscal_year) AS prior_year_spend,
    total_spend - LAG(total_spend) OVER (PARTITION BY agency ORDER BY fiscal_year) AS change,
    (total_spend - LAG(total_spend) OVER (PARTITION BY agency ORDER BY fiscal_year)) * 1.0
        / NULLIF(LAG(total_spend) OVER (PARTITION BY agency ORDER BY fiscal_year), 0) AS pct_change
FROM v_agency_year;

-- Spending by secretariat, with each one's share of the year's total
CREATE VIEW v_secretariat_year AS
SELECT
    a.secretariat,
    f.fiscal_year,
    SUM(f.amount) AS total_spend,
    SUM(f.amount) * 1.0 / SUM(SUM(f.amount)) OVER (PARTITION BY f.fiscal_year) AS share_of_year
FROM fact_monthly f
JOIN dim_agency a ON a.agency_id = f.agency_id
GROUP BY a.secretariat, f.fiscal_year;

-- What the money is spent on (personal services, transfer payments, etc.)
CREATE VIEW v_category_year AS
SELECT
    category,
    fiscal_year,
    SUM(amount) AS total_spend,
    SUM(amount) * 1.0 / SUM(SUM(amount)) OVER (PARTITION BY fiscal_year) AS share_of_year
FROM fact_monthly
GROUP BY category, fiscal_year;

-- Statewide spending by month
CREATE VIEW v_monthly_trend AS
SELECT
    fiscal_year,
    month,
    SUM(amount)    AS total_spend,
    SUM(txn_count) AS transactions
FROM fact_monthly
GROUP BY fiscal_year, month;

-- How dependent each agency is on a few vendors.
-- Only named organizations count: payroll and individual payees are left out.
-- hhi is the Herfindahl-Hirschman Index (sum of squared market shares x 10,000).
-- Above 2,500 means spending is highly concentrated.
CREATE VIEW v_vendor_concentration AS
WITH vendor_totals AS (
    SELECT f.agency_id, f.fiscal_year, f.vendor_id, SUM(f.amount) AS amount
    FROM fact_vendor_year f
    JOIN dim_vendor v ON v.vendor_id = f.vendor_id
    WHERE v.vendor_type = 'Organization'
    GROUP BY f.agency_id, f.fiscal_year, f.vendor_id
    HAVING SUM(f.amount) > 0
),
shares AS (
    SELECT
        agency_id, fiscal_year, vendor_id, amount,
        amount * 1.0 / SUM(amount) OVER (PARTITION BY agency_id, fiscal_year) AS share
    FROM vendor_totals
)
SELECT
    a.agency,
    a.secretariat,
    s.fiscal_year,
    COUNT(*)                     AS vendor_count,
    SUM(s.amount)                AS vendor_spend,
    MAX(s.share)                 AS top_vendor_share,
    SUM(s.share * s.share) * 10000 AS hhi
FROM shares s
JOIN dim_agency a ON a.agency_id = s.agency_id
GROUP BY a.agency, a.secretariat, s.fiscal_year;

-- Biggest vendors statewide each year, ranked
CREATE VIEW v_top_vendors AS
SELECT
    v.vendor,
    f.fiscal_year,
    SUM(f.amount) AS total_paid,
    COUNT(DISTINCT f.agency_id) AS agencies_paying,
    RANK() OVER (PARTITION BY f.fiscal_year ORDER BY SUM(f.amount) DESC) AS rank_in_year
FROM fact_vendor_year f
JOIN dim_vendor v ON v.vendor_id = f.vendor_id
WHERE v.vendor_type = 'Organization'
GROUP BY v.vendor, f.fiscal_year;
