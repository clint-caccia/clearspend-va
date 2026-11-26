"""Static charts for the README, built straight from the SQL views."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

BLUE = "#257de0"
RED = "#ec4647"
INK = "#191919"
MUTED = "#666666"
GRID = "#e6e6e6"


def _style(ax):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _billions(x, _pos=None):
    """Axis ticks: whole numbers."""
    if x == 0:
        return "$0"
    return f"${x / 1e9:,.0f}B" if abs(x) >= 1e9 else f"${x / 1e6:,.0f}M"


def _label(x):
    """Data labels: one decimal on billions so $5.3B and $4.7B don't both read $5B."""
    return f"${x / 1e9:,.1f}B" if abs(x) >= 1e9 else f"${x / 1e6:,.0f}M"


def _title(fig, title, subtitle):
    fig.text(0.01, 0.97, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.91, subtitle, fontsize=9.5, color=MUTED, va="top")


def secretariat_chart(con, path, year):
    df = pd.read_sql(
        "SELECT secretariat, total_spend FROM v_secretariat_year WHERE fiscal_year = ? ORDER BY total_spend",
        con, params=(year,))
    df["secretariat"] = df["secretariat"].str.title().str.replace(" And ", " and ")
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=150)
    bars = ax.barh(df["secretariat"], df["total_spend"], color=BLUE, height=0.65)
    total = df["total_spend"].sum()
    for bar, value in zip(bars, df["total_spend"]):
        ax.text(bar.get_width() + total * 0.005, bar.get_y() + bar.get_height() / 2,
                f"{_label(value)}  ({value / total:.0%})" if value >= 1e9 else _label(value),
                va="center", fontsize=8.5, color=INK)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_billions))
    ax.set_xlim(0, df["total_spend"].max() * 1.22)
    _style(ax)
    _title(fig, f"Where Virginia's money went in FY{year}",
           f"State agency spending by secretariat, {_label(total)} total")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(path)
    plt.close(fig)


def monthly_chart(con, path):
    df = pd.read_sql("SELECT month, total_spend FROM v_monthly_trend ORDER BY month", con)
    df = df.groupby("month", as_index=False)["total_spend"].sum()
    df["month"] = pd.to_datetime(df["month"])
    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    ax.plot(df["month"], df["total_spend"], color=BLUE, linewidth=2)
    ax.scatter(df["month"], df["total_spend"], color=BLUE, s=14, zorder=3)
    peak = df.loc[df["total_spend"].idxmax()]
    ax.annotate(f"{peak['month']:%b %Y}: {_label(peak['total_spend'])}",
                (peak["month"], peak["total_spend"]), xytext=(8, 4), textcoords="offset points",
                fontsize=8.5, color=INK)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_billions))
    ax.set_ylim(0, df["total_spend"].max() * 1.15)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    first, last = df["month"].min(), df["month"].max()
    _title(fig, "Statewide spending by month",
           f"{first:%b %Y} to {last:%b %Y}, all state agencies")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(path)
    plt.close(fig)


def biggest_changes_chart(con, path, year, n=8):
    df = pd.read_sql(
        "SELECT agency, change FROM v_agency_yoy WHERE fiscal_year = ? AND change IS NOT NULL", con, params=(year,))
    up = df.nlargest(n, "change")
    down = df.nsmallest(n, "change")
    df = pd.concat([down, up]).drop_duplicates("agency").sort_values("change")
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    colors = [BLUE if c > 0 else RED for c in df["change"]]
    ax.barh(df["agency"], df["change"], color=colors, height=0.65)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    span = df["change"].abs().max()
    for y, value in enumerate(df["change"]):
        sign = "+" if value > 0 else "-"
        ax.text(value + (span * 0.02 if value > 0 else -span * 0.02), y, f"{sign}{_label(abs(value))}",
                va="center", ha="left" if value > 0 else "right", fontsize=8.5, color=INK)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: ("+" if x > 0 else "-" if x < 0 else "") + _billions(abs(x))))
    ax.set_xlim(-span * 1.35, span * 1.35)
    _style(ax)
    _title(fig, f"Biggest spending changes, FY{year - 1} to FY{year}",
           "Agencies with the largest increase (blue) and decrease (red) in dollars")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(path)
    plt.close(fig)


def make_all(con, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    years = [r[0] for r in con.execute("SELECT DISTINCT fiscal_year FROM v_agency_year ORDER BY 1")]
    full_years = [y for y in years if _month_count(con, y) == 12]
    latest_full = full_years[-1]
    secretariat_chart(con, folder / "spend_by_secretariat.png", latest_full)
    monthly_chart(con, folder / "monthly_trend.png")
    if latest_full - 1 in years:
        biggest_changes_chart(con, folder / "biggest_changes.png", latest_full)


def _month_count(con, year):
    return con.execute("SELECT COUNT(DISTINCT month) FROM fact_monthly WHERE fiscal_year = ?", (year,)).fetchone()[0]
