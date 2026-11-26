"""Download the yearly expenditure extracts from Commonwealth Data Point.

Data Point (https://datapoint.apa.virginia.gov) is run by the Virginia Auditor
of Public Accounts. Each fiscal year is one zip of monthly CSV files.
"""

import os
import urllib.parse
import urllib.request

BASE = "https://www.datapoint.apa.virginia.gov/data/extracts/{fy}/"
NAME = "All Expenditures for Fiscal Year {fy}.zip"


def zip_url(fy: int) -> str:
    return BASE.format(fy=fy) + urllib.parse.quote(NAME.format(fy=fy))


def download_year(fy: int, folder: str = "data/raw") -> str:
    """Download one fiscal year's zip unless it's already there. Returns the local path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, NAME.format(fy=fy))
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"FY{fy}: already downloaded")
        return path
    print(f"FY{fy}: downloading {zip_url(fy)}")
    request = urllib.request.Request(zip_url(fy), headers={"User-Agent": "clearspend-va (student project)"})
    with urllib.request.urlopen(request) as response, open(path + ".part", "wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(path + ".part", path)
    print(f"FY{fy}: saved {os.path.getsize(path) / 1e6:.0f} MB")
    return path
