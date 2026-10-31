"""Bank of Israel interest rates (SDMX API at edge.boi.org.il) for `interest_rates`.

Monthly average rates on new housing loans by track (dataflow BIR_MRTG_99, banking system
including syndications, from 2011-07) and the Bank of Israel policy rate (dataflow BR, daily,
stored as the rate in effect at the end of each month). The prime rate is the policy rate
plus 1.5 percentage points.

Run `python -m apartment_data.sources.boi_rates` to fetch and write a CSV, and add `--load`
to upsert into the database at DATABASE_URL.
"""

import argparse
import csv
import gzip
import io
import time
from collections import defaultdict
from dataclasses import astuple, dataclass, fields
from datetime import date
from pathlib import Path

import httpx

from apartment_data.config import REPO_ROOT, load_settings

BASE_URL = "https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS"
USER_AGENT = "apartment-data/0.1 (+https://github.com/tamirgabgab/Apartment-data)"
START = "2010-01"
PRIME_SPREAD = 1.5  # Israeli banks set prime at the policy rate + 1.5 points

# Output series -> BOI series codes summed to make it. The CPI-linked variable track is
# published as its benchmark rate plus its margin.
MORTGAGE_SERIES = {
    "mortgage_fixed_unindexed": (
        "ריבית ממוצעת על משכנתאות חדשות - קבועה לא צמודה",
        ["BNK_99034_LR_BIR_MRTG_467"],
    ),
    "mortgage_fixed_cpi": (
        "ריבית ממוצעת על משכנתאות חדשות - קבועה צמודה למדד",
        ["BNK_99034_LR_BIR_MRTG_1492"],
    ),
    "mortgage_variable_cpi": (
        "ריבית ממוצעת על משכנתאות חדשות - משתנה צמודה למדד",
        ["BNK_99034_LR_BIR_MRTG_1489", "BNK_99034_LR_BIR_MRTG_1488"],
    ),
}
POLICY_SERIES = "MNT_RIB_BOI_D"
POLICY_NAMES = {"boi_rate": "ריבית בנק ישראל", "prime": "ריבית הפריים"}


@dataclass(frozen=True)
class RateValue:
    series_code: str
    series_name: str
    period: date  # first day of the month
    value: float  # percent per year


class BoiClient:
    """Throttled client for the BOI SDMX API that keeps the latest raw responses."""

    def __init__(
        self, cache_dir: Path, delay_seconds: float = 1.0, client: httpx.Client | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
        self._client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=180)
        self._last_request = 0.0

    def fetch_csv(self, dataflow: str, key: str = "") -> str:
        wait = self._last_request + self.delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        url = f"{BASE_URL}/{dataflow}/1.0/{key}"
        response = self._client.get(url, params={"format": "csv", "startperiod": START})
        self._last_request = time.monotonic()
        response.raise_for_status()
        text = response.text
        cache_file = self.cache_dir / "boi" / f"{dataflow}{'_' + key if key else ''}.csv.gz"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(cache_file, "wt", encoding="utf-8") as f:
            f.write(text)
        return text


def _observations(text: str) -> dict[str, dict[str, float]]:
    """SERIES_CODE -> TIME_PERIOD -> value, skipping empty observations."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        raw = (row.get("OBS_VALUE") or "").strip()
        if raw:
            out[row["SERIES_CODE"]][row["TIME_PERIOD"]] = float(raw)
    return out


def _month(period: str) -> date:
    year, month = period.split("-")[:2]
    return date(int(year), int(month), 1)


def parse_mortgage_rates(text: str) -> list[RateValue]:
    """Rates by track; a month is kept only when every part of its series is published."""
    obs = _observations(text)
    rows = []
    for code, (name, parts) in MORTGAGE_SERIES.items():
        missing = [p for p in parts if p not in obs]
        if missing:
            raise ValueError(f"BOI dataflow is missing series {', '.join(missing)}")
        periods = set.intersection(*(set(obs[p]) for p in parts))
        for period in sorted(periods):
            value = round(sum(obs[p][period] for p in parts), 4)
            rows.append(RateValue(code, name, _month(period), value))
    return rows


def parse_policy_rate(text: str) -> list[RateValue]:
    """Policy rate and prime rate in effect on the last published day of each month."""
    daily = _observations(text).get(POLICY_SERIES)
    if not daily:
        raise ValueError(f"BOI dataflow is missing series {POLICY_SERIES}")
    month_end: dict[date, tuple[str, float]] = {}
    for day, value in daily.items():
        month = _month(day)
        if month not in month_end or day > month_end[month][0]:
            month_end[month] = (day, value)
    rows = []
    for month in sorted(month_end):
        value = month_end[month][1]
        rows.append(RateValue("boi_rate", POLICY_NAMES["boi_rate"], month, value))
        prime = round(value + PRIME_SPREAD, 4)
        rows.append(RateValue("prime", POLICY_NAMES["prime"], month, prime))
    return rows


def fetch_all(client: BoiClient) -> list[RateValue]:
    rows = parse_mortgage_rates(client.fetch_csv("BIR_MRTG_99"))
    rows += parse_policy_rate(client.fetch_csv("BR", POLICY_SERIES))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "boi")
    parser.add_argument("--load", action="store_true", help="upsert into DATABASE_URL")
    args = parser.parse_args(argv)

    settings = load_settings()
    rows = fetch_all(BoiClient(settings.raw_data_dir, settings.request_delay_seconds))
    by_series: dict[str, list[RateValue]] = defaultdict(list)
    for row in rows:
        by_series[row.series_code].append(row)
    for code, values in by_series.items():
        print(f"{code}: {len(values)} months, {values[0].period} .. {values[-1].period}")

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "interest_rates.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([fl.name for fl in fields(RateValue)])
        writer.writerows(astuple(row) for row in rows)

    if args.load:
        from apartment_data.storage.db import connect, upsert_interest_rates

        with connect(settings) as conn:
            upsert_interest_rates(conn, rows)
        print("Loaded into the database.")


if __name__ == "__main__":
    main()
