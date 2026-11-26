"""Read the monthly CSVs out of a Data Point zip and clean them.

Problems in the raw data, and what this module does about each one:

* Most of FY2025 is padded text with   -> split on fixed column positions instead of
  no quotes, so commas inside values       trusting the commas (see padded_layout)
  break normal CSV parsing.
* Dates are MM-DD-YY strings.             -> parsed into real dates
* AMOUNT has refunds and reversals (< 0). -> kept, so totals net out, but flagged
* About 30% of rows have no vendor,       -> labeled "No vendor listed (payroll or internal)"
  mostly payroll.
* Many vendors are individual people      -> grouped as "Individual or small payee (name
  ("LAST,FIRST M"), e.g. reimbursements.     withheld)" so nobody's name ends up public
* Universities and a few others report  -> labeled "Vendor detail not reported"
  "** DETAILED DATA NOT YET AVAILABLE **".         and left out of vendor rankings
* Ledger adjustments sit in the vendor    -> labeled "Accounting adjustment (no payee)"
  column ("MISCELLANEOUS ADJUSTMENT").       and left out of vendor rankings
* The same company is spelled several     -> uppercased, punctuation stripped, legal
  ways ("ACME, INC." vs "Acme Inc").         suffixes like INC / LLC removed
* Inconsistent capitalization in text     -> stripped and collapsed whitespace
  columns.
"""

import io
import re
import zipfile
from collections import Counter
from typing import Iterator

import pandas as pd

COLUMNS = [
    "BRANCH_NAME", "SECRETARIAT_NAME", "AGENCY_NAME", "FUNCTION_NAME", "PROGRAM_NAME",
    "SERVICE_AREA_NAME", "FUND_NAME", "FUND_DETAIL_NAME", "CATEGORY_NAME", "EXPENSE_TYPE",
    "TRANS_DATE", "FISCAL_YEAR", "AMOUNT", "VENDOR_NAME",
]
KEEP = {
    "BRANCH_NAME": "branch",
    "SECRETARIAT_NAME": "secretariat",
    "AGENCY_NAME": "agency",
    "FUND_NAME": "fund",
    "CATEGORY_NAME": "category",
    "EXPENSE_TYPE": "expense_type",
    "TRANS_DATE": "trans_date",
    "FISCAL_YEAR": "fiscal_year",
    "AMOUNT": "amount",
    "VENDOR_NAME": "vendor_raw",
}

NO_VENDOR = "No vendor listed (payroll or internal)"
INDIVIDUAL = "Individual or small payee (name withheld)"
ACCOUNTING = "Accounting adjustment (no payee)"
NOT_REPORTED = "Vendor detail not reported"

# Ledger entries that show up in the vendor column but aren't payees at all.
ACCOUNTING_RE = re.compile(r"^\W*(MISCELLANEOUS ADJUSTMENT|WARRANT REGISTER\b|JOURNAL ENTRY|ADJUSTMENT)")
# Placeholder some agencies (mostly universities) use instead of per-vendor detail.
NOT_REPORTED_RE = re.compile(r"^\W*(DETAILED DATA NOT YET AVAILABLE|CONTACT AGENCY FOR MORE INFO)")
# A corporate suffix means a registered business, so the name is safe to show.
CORP_SUFFIX = re.compile(
    r"\b(INC|INCORPORATED|LLC|L L C|LLP|LLLP|LTD|CORP|CORPORATION|CO|COMPANY|LP|PLC|NA|N A|GMBH|USA)\b\.?"
)
# Suffixes a one-person practice uses. "JANE Q PUBLIC PC" is still a person's name.
PERSONAL_SUFFIX = re.compile(r"(?:[ ,]+(?:P\.?\s?C|PLLC|P\.?\s?A|ESQ|MD|DDS|DMD|PHD|CPA|JR|SR|II|III|IV)\.?)+$")
# Words that mark a payee as an organization rather than a person.
ORG_WORDS = re.compile(
    r"\b(GROUP|ASSOC|ASSOCIATES|ASSOCIATION|SERVICES?|SOLUTIONS|SYSTEMS|TECHNOLOGIES|TECHNOLOGY|"
    r"BANK|TRUST|FUND|FOUNDATION|INSURANCE|HEALTH|HEALTHCARE|HOSPITAL|MEDICAL|MEDICINE|CLINIC|"
    r"PHARMACY|DRUGS?|UNIVERSITY|COLLEGE|SCHOOLS?|ACADEMY|INSTITUTE|CENTER|CENTRE|AUTHORITY|AGENCY|"
    r"DEPARTMENT|DEPT|BOARD|COMMISSION|COUNCIL|COUNTY|CITY|TOWN|COMMONWEALTH|VIRGINIA|STATE|"
    r"UNITED|NATIONAL|AMERICA|AMERICAN|INTERNATIONAL|ENERGY|POWER|ELECTRIC|WATER|GAS|OIL|"
    r"CONSTRUCTION|CONTRACTORS?|CONTRACTING|ENGINEERING|ENGINEERS|PARTNERS|PARTNERSHIP|ENTERPRISES?|"
    r"INDUSTRIES|HOLDINGS|PROPERTIES|REALTY|MANAGEMENT|CONSULTING|COMMUNICATIONS|WIRELESS|SUPPLY|"
    r"SUPPLIES|MARKET|STORE|SHOP|OFFICE|PRODUCTS|EQUIPMENT|MOTORS|AUTO|LAW|LEGAL|CHURCH|MINISTRIES|"
    r"COMMUNITY|SOCIETY|CLUB|NETWORK|SOFTWARE|DATA|LABS?|LABORATORIES|TREASURER|POSTMASTER|"
    r"RAILROAD|TRANSIT|TRANSPORTATION|HOTEL|INN|RESORT|AIRLINES?|DISTRICT|REGIONAL|PROGRAM|"
    r"PROJECT|SHERIFF|COURT|CLERK|EXPRESS|LINES|FREIGHT|LOGISTICS|VENTURES?|JOINT|HOMES|BUILDERS?|"
    r"BUILDS|CIVIL|PAVING|ELECTRICAL|MECHANICAL|PLUMBING|ROOFING|LANDSCAPING|SECURITY|STAFFING|"
    r"INTERACTIVE|DIGITAL|MEDIA|PRESS|PUBLISHING|DISTILLERS?|DISTILLERIES|SPIRITS|WINES?|BREWING|"
    r"FARMS?|FOODS?|RESTAURANT|CAFE|GRILL|CATERING|RENTALS?|LEASING|CAPITAL|FINANCIAL|INVESTMENTS|"
    r"CONSORTIUM|ALLIANCE|COALITION|COOPERATIVE|COOP|LEAGUE|BATTLEFIELDS|MUSEUM|LIBRARY|THEATRE|"
    r"THEATER|ARTS|CARE|LIVING|SENIOR|CHILDREN|FAMILY|YOUTH|HOUSING|SHELTER|RECOVERY|COUNSELING|"
    r"THERAPY|DENTAL|VISION|PEDIATRICS|ASSISTED|NURSING|REHAB|REHABILITATION|THE|OF|AND|FOR)\b"
)
# "SMITH,JOHN A" or "Sample,Alex": letters, one comma, letters.
COMMA_PERSON = re.compile(r"^[A-Za-z'\-. ]+,\s?[A-Za-z'\-. ]+$")
# "MARY ANN SAMPLE" or "JANE Q PUBLIC": two to four plain words, no digits.
PLAIN_NAME = re.compile(r"^[A-Za-z'\-.]+(?: [A-Za-z'\-.]+){1,3}$")
# In a mixed-case name, a short all-caps token is an acronym ("Western Tidewater CSB").
ACRONYM = re.compile(r"\b[A-Z]{2,5}\b")
SUFFIX_RE = re.compile(r"\b(INCORPORATED|INC|LLC|L L C|LLP|LLLP|LTD|CORPORATION|CORP|CO|COMPANY|PLLC|PC|LP)\b\.?$")
NON_ALNUM = re.compile(r"[^A-Z0-9& ]+")
SPACES = re.compile(r"\s+")


def looks_like_person(text: str) -> bool:
    """True when a payee string could be a person's name.

    Errs on the side of hiding. A small business that ends up behind "name withheld"
    costs nothing, but a real person's name on a public dashboard is a problem. So a
    name is only shown when something marks it as an organization: a corporate
    suffix, a word like COUNTY or SUPPLY, a digit or symbol, or an acronym.
    """
    clean_text = SPACES.sub(" ", text).strip()
    upper = clean_text.upper()
    stripped = PERSONAL_SUFFIX.sub("", upper).strip(" ,.")
    if stripped == upper and CORP_SUFFIX.search(upper):
        return False
    if ORG_WORDS.search(stripped) or re.search(r"[0-9&/@#]", stripped):
        return False
    if clean_text != upper and ACRONYM.search(PERSONAL_SUFFIX.sub("", clean_text)):
        return False
    return bool(COMMA_PERSON.match(stripped) or PLAIN_NAME.match(stripped))


def classify_vendor(raw) -> str:
    """Map a raw vendor string to a cleaned name, or to one of the two privacy groups."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return NO_VENDOR
    # some names come zero-padded ("0000000000000000000JANE Q PUBLIC")
    text = re.sub(r"^0{3,}", "", str(raw).strip()).strip()
    if not text:
        return NO_VENDOR
    if ACCOUNTING_RE.match(text.upper()):
        return ACCOUNTING
    if NOT_REPORTED_RE.match(text.upper()):
        return NOT_REPORTED
    if looks_like_person(text):
        return INDIVIDUAL
    name = NON_ALNUM.sub(" ", text.upper())
    name = SPACES.sub(" ", name).strip()
    # strip trailing legal suffixes, possibly more than one ("CO INC")
    for _ in range(2):
        name = SUFFIX_RE.sub("", name).strip()
    # "ANTHEM HEALTH PLANS OF VIRGINIA" and "...OF VA" are the same payee
    name = re.sub(r"\bVIRGINIA$", "VA", name)
    return name or NO_VENDOR


_VENDOR_CACHE: dict = {}


def _tidy_text(series: pd.Series) -> pd.Series:
    return series.fillna("Unknown").astype(str).str.strip().str.replace(SPACES, " ", regex=True)


def clean_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw[list(KEEP)].rename(columns=KEEP)
    for col in ["branch", "secretariat", "agency", "fund", "category", "expense_type"]:
        df[col] = _tidy_text(df[col])
    # most of FY2025 was exported as padded fixed-width text, so strip everything first
    df["trans_date"] = pd.to_datetime(df["trans_date"].str.strip(), format="%m-%d-%y", errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"].str.strip(), errors="coerce")
    fy = pd.to_numeric(df["fiscal_year"].str.strip(), errors="coerce")
    df["fiscal_year"] = fy.where(fy % 1 == 0).astype("Int64")
    df = df.dropna(subset=["trans_date", "amount", "fiscal_year"])
    df["month"] = df["trans_date"].dt.to_period("M").dt.to_timestamp()
    df["is_refund"] = df["amount"] < 0
    # vendor cleanup is the slow step, so do each distinct string once
    df["vendor_raw"] = df["vendor_raw"].fillna("").str.strip()
    for v in df["vendor_raw"].unique():
        if v not in _VENDOR_CACHE:
            _VENDOR_CACHE[v] = classify_vendor(v)
    lookup = _VENDOR_CACHE
    df["vendor"] = df["vendor_raw"].map(lookup)
    return df.drop(columns=["vendor_raw"])


DATE_AFTER = re.compile(r",\s*\d\d-\d\d-\d\d\s*,")
TAIL_RE = re.compile(r"^\s*(\d\d-\d\d-\d\d)\s*,\s*(\d+)\s*,\s*(-?\d*\.?\d*)\s*,(.*)$")


def padded_layout(sample_lines):
    """Find where the commas sit in a padded, unquoted export.

    Most of FY2025 came out of Data Point as space-padded text with no quotes, so a
    comma inside "Travel, Personal Vehicle" or "SMITH, JOHN" breaks a normal CSV
    parser (about 1 in 6 rows). The first ten columns are padded to fixed widths,
    so the real separators sit at the same positions on every line. Any comma that
    shows up in every sampled line is a separator, and the first ten of those end
    the ten padded columns.
    """
    lines = [line for line in sample_lines if line]
    seen, date_seen = Counter(), Counter()
    for line in lines:
        for i, ch in enumerate(line):
            if ch == ",":
                seen[i] += 1
                if DATE_AFTER.match(line, i):
                    date_seen[i] += 1
    # a stray bad line shouldn't break detection, so "every line" means 95% of them
    common = {pos for pos, n in seen.items() if n >= 0.95 * len(lines)}
    date_commas = [pos for pos, n in date_seen.items() if n >= 0.95 * len(lines)]
    if len(date_commas) != 1:
        raise ValueError("could not find the fixed column layout in a padded file")
    date_comma = date_commas[0]
    before = sorted(c for c in common if c < date_comma)
    if len(before) != 9:
        raise ValueError("could not find the fixed column layout in a padded file")
    return tuple(before) + (date_comma,)


def split_padded(line, commas):
    """Split one padded line into the 14 columns using the fixed comma positions."""
    if len(line) <= commas[-1] or any(line[c] != "," for c in commas):
        return None
    starts = (0,) + tuple(c + 1 for c in commas[:-1])
    head = [line[s:e] for s, e in zip(starts, commas)]
    tail = TAIL_RE.match(line[commas[-1] + 1:])
    if not tail:
        return None
    return head + list(tail.groups())


def _padded_chunks(handle, chunksize):
    text = io.TextIOWrapper(handle, encoding="latin-1", newline="")
    text.readline()  # header
    first = [text.readline().rstrip("\r\n") for _ in range(2000)]
    first = [line for line in first if not _is_junk(line)]
    commas = padded_layout(first)
    rows, bad = [], 0

    def lines():
        yield from first
        for raw in text:
            yield raw.rstrip("\r\n")

    for line in lines():
        if _is_junk(line):
            continue
        parts = split_padded(line, commas)
        if parts is None:
            bad += 1
            continue
        rows.append(parts)
        if len(rows) >= chunksize:
            yield pd.DataFrame(rows, columns=COLUMNS), len(rows) + bad
            rows, bad = [], 0
    if rows or bad:
        yield pd.DataFrame(rows, columns=COLUMNS), len(rows) + bad


def _is_junk(line):
    """Some FY2025 exports include SQL*Plus messages ("SP2-0044: ...") between rows."""
    return line.startswith(("SP2-", "SQL>")) or not line.strip()


def _is_padded(archive, member):
    with archive.open(member) as handle:
        head = handle.read(8192).decode("latin-1")
    lines = head.split("\n")
    data = [line for line in lines[1:-1] if not _is_junk(line)]
    return not lines[0].startswith('"') and any("  ," in line for line in data[:5])


def iter_month_frames(zip_path: str, chunksize: int = 250_000) -> Iterator[pd.DataFrame]:
    """Yield (cleaned chunk, raw row count) from every monthly CSV in one fiscal-year zip."""
    with zipfile.ZipFile(zip_path) as archive:
        members = [i.filename for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".csv")]
        for member in sorted(members):
            if _is_padded(archive, member):
                with archive.open(member) as handle:
                    for chunk, raw_rows in _padded_chunks(handle, chunksize):
                        yield clean_frame(chunk), raw_rows
                continue
            with archive.open(member) as handle:
                reader = pd.read_csv(handle, dtype=str, chunksize=chunksize, encoding="latin-1",
                                     on_bad_lines="warn", usecols=lambda c: c in KEEP)
                for chunk in reader:
                    yield clean_frame(chunk), len(chunk)
