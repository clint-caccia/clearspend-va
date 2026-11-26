import io
import zipfile

import pandas as pd

from clearspend import clean

HEADER = ",".join(clean.COLUMNS)


def quoted_row(agency, date, fy, amount, vendor, expense="Travel, Personal Vehicle"):
    vals = ["EXECUTIVE", "FINANCE", agency, "GEN GOV", "Prog", "Svc", "GENERAL", "General Fund",
            "CONTRACTUAL SERVICES", expense, None, None, None, vendor]
    out = ",".join(f'"{v}"' for v in vals[:10]) + f",{date},{fy},{amount}," + f'"{vendor}"'
    return out


WIDTHS = [30, 35, 100, 100, 100, 100, 100, 100, 100, 100]


def padded_row(agency, date, fy, amount, vendor, expense="Travel, Personal Vehicle"):
    vals = ["EXECUTIVE", "FINANCE", agency, "GEN GOV", "Prog", "Svc", "GENERAL", "General Fund",
            "CONTRACTUAL SERVICES", expense]
    head = ",".join(v.ljust(w) for v, w in zip(vals, WIDTHS))
    return f"{head},{date},{fy:>11},{amount:>10},{vendor}"


def make_zip(tmp_path, members):
    path = tmp_path / "fy.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("All Expenditure For Fiscal Year 2025/", "")
        for name, text in members.items():
            z.writestr(f"All Expenditure For Fiscal Year 2025/{name}", text)
    return str(path)


def test_vendor_privacy_groups():
    assert clean.classify_vendor("SMITH,JOHN A") == clean.INDIVIDUAL
    assert clean.classify_vendor("YI CHUN SAUNDERS") == clean.INDIVIDUAL
    assert clean.classify_vendor("KAREN L LOFTIN PC") == clean.INDIVIDUAL
    assert clean.classify_vendor("") == clean.NO_VENDOR
    assert clean.classify_vendor(None) == clean.NO_VENDOR
    assert clean.classify_vendor("Jason Harvey") == clean.INDIVIDUAL
    assert clean.classify_vendor("BEAUPRE SR, PAUL F") == clean.INDIVIDUAL


def test_accounting_entries_are_not_vendors():
    assert clean.classify_vendor("MISCELLANEOUS ADJUSTMENT") == clean.ACCOUNTING
    assert clean.classify_vendor("WARRANT REGISTER - BOA") == clean.ACCOUNTING
    assert clean.classify_vendor("** DETAILED DATA NOT YET AVAILABLE **") == clean.NOT_REPORTED


def test_companies_named_like_people_still_show_when_registered():
    assert clean.classify_vendor("Computer Aid Inc") == "COMPUTER AID"
    assert clean.classify_vendor("Western Tidewater CSB") == "WESTERN TIDEWATER CSB"
    assert clean.classify_vendor("ESTES EXPRESS LINES") == "ESTES EXPRESS LINES"


def test_vendor_names_are_standardized():
    assert clean.classify_vendor("Dominion Energy Virginia") == "DOMINION ENERGY VA"
    assert clean.classify_vendor("Anthem Health Plans of Virginia") == clean.classify_vendor("ANTHEM HEALTH PLANS OF VA")
    assert clean.classify_vendor("City of Virginia Beach") == "CITY OF VIRGINIA BEACH"
    assert clean.classify_vendor("ROANOKE FAMILY MEDICINE, INC.") == "ROANOKE FAMILY MEDICINE"
    assert clean.classify_vendor("Roanoke Family Medicine Inc") == "ROANOKE FAMILY MEDICINE"


def test_quoted_and_padded_files_parse_the_same(tmp_path):
    quoted = "\n".join([HEADER,
                        quoted_row("Dept of Health", "08-13-24", 2025, 10.48, "ROANOKE FAMILY MEDICINE INC"),
                        quoted_row("Dept of Health", "08-14-24", 2025, -5.00, "SMITH, JOHN", expense="Postal Services")]) + "\n"
    padded = "\n".join([HEADER,
                        padded_row("Dept of Health", "08-13-24", 2025, "10.48", "ROANOKE FAMILY MEDICINE INC"),
                        padded_row("Dept of Health", "08-14-24", 2025, "-5", "SMITH, JOHN", expense="Postal Services")]) + "\n"
    path = make_zip(tmp_path, {"Expenditure Aug 2024.csv": quoted, "Expenditure Sep 2024.csv": padded})
    frames = list(clean.iter_month_frames(path))
    assert len(frames) == 2
    a, b = frames[0][0].reset_index(drop=True), frames[1][0].reset_index(drop=True)
    cols = ["agency", "expense_type", "trans_date", "fiscal_year", "amount", "vendor", "is_refund"]
    pd.testing.assert_frame_equal(a[cols], b[cols])
    assert b.loc[0, "expense_type"] == "Travel, Personal Vehicle"
    assert b.loc[1, "expense_type"] == "Postal Services"
    assert b.loc[1, "vendor"] == clean.INDIVIDUAL
    assert bool(b.loc[1, "is_refund"])
    assert b.loc[0, "fiscal_year"] == 2025


def test_bad_rows_are_counted_not_silently_lost(tmp_path):
    good = [padded_row("Dept of Health", "08-13-24", 2025, f"{i}.00", "ACME SUPPLY",
                       expense=["Postal Services", "Travel, Personal Vehicle", "Office Supplies"][i % 3])
            for i in range(1, 41)]
    padded = "\n".join([HEADER] + good[:20] + ["garbage line that is not a record"] + good[20:]) + "\n"
    path = make_zip(tmp_path, {"Expenditure Aug 2024.csv": padded})
    (df, raw_rows), = list(clean.iter_month_frames(path))
    assert len(df) == 40
    assert raw_rows == 41
    assert df["amount"].sum() == sum(range(1, 41))


def test_sqlplus_messages_are_skipped(tmp_path):
    good = [padded_row("Dept of Health", "01-13-25", 2025, f"{i}.00", "ACME SUPPLY",
                       expense=["Postal Services", "Travel, Personal Vehicle", "Office Supplies"][i % 3])
            for i in range(1, 31)]
    junk = "SP2-0044: For a list of known commands enter HELP"
    padded = "\r\n".join([HEADER, junk] + good + [junk, ""]) 
    path = make_zip(tmp_path, {"Expenditure Jan 2025.csv": padded})
    (df, raw_rows), = list(clean.iter_month_frames(path))
    assert len(df) == 30 and raw_rows == 30
