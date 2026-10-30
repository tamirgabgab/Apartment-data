"""CBS price index series (https://api.cbs.gov.il/index) for `official_indices`.

Values are stored as published: each month carries the base it was published on
(`base_period`, e.g. '1993 ממוצע'). The CPI changes base every two years, so chaining to a
single base is left to the analytics step.

Run `python -m apartment_data.sources.cbs_index` to fetch every series and write a CSV, and
add `--load` to upsert into the database at DATABASE_URL.
"""

import argparse
import csv
import gzip
import json
import time
from dataclasses import astuple, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from apartment_data.config import REPO_ROOT, load_settings

BASE_URL = "https://api.cbs.gov.il/index/data/price"
USER_AGENT = "apartment-data/0.1 (+https://github.com/tamirgabgab/Apartment-data)"
PAGE_SIZE = 1000

SERIES = {
    "40010": "מדד מחירי דירות - כלל הארץ",
    "60000": "מדד מחירי דירות - מחוז ירושלים",
    "60100": "מדד מחירי דירות - מחוז צפון",
    "60200": "מדד מחירי דירות - מחוז חיפה",
    "60300": "מדד מחירי דירות - מחוז מרכז",
    "60400": "מדד מחירי דירות - מחוז תל אביב",
    "60500": "מדד מחירי דירות - מחוז דרום",
    "70000": "מדד מחירי דירות חדשות",
    "120010": "מדד המחירים לצרכן - כללי",
}

# The API answers 500 for some ranges of some series; start those where it works.
SERIES_START = {"70000": "01-2019"}


@dataclass(frozen=True)
class IndexValue:
    series_code: str
    series_name: str
    period: date
    value: float
    base_period: str | None


class CbsIndexClient:
    """Throttled client for the CBS price index API that keeps the latest raw responses."""

    def __init__(
        self, cache_dir: Path, delay_seconds: float = 1.0, client: httpx.Client | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
        self._client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)
        self._last_request = 0.0

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        wait = self._last_request + self.delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        response = self._client.get(BASE_URL, params=params)
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response.json()

    def fetch_series(self, code: str) -> list[dict[str, Any]]:
        """Every page of one series, as returned by the API."""
        pages = []
        page = 1
        while True:
            payload = self._get(
                {
                    "id": code,
                    "format": "json",
                    "download": "false",
                    "startPeriod": SERIES_START.get(code, "01-1950"),
                    "endPeriod": f"12-{date.today().year}",
                    "PageSize": PAGE_SIZE,
                    "Page": page,
                }
            )
            pages.append(payload)
            if page >= (payload.get("paging") or {}).get("last_page", 1):
                break
            page += 1

        cache_file = self.cache_dir / "cbs" / f"index_{code}.json.gz"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(cache_file, "wt", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        return pages


def parse_monthly(code: str, pages: list[dict[str, Any]]) -> list[IndexValue]:
    """Monthly values of one series. Quarterly-only history (before monthly data) is skipped."""
    values = {}
    for payload in pages:
        for series in payload.get("month") or []:
            if str(series.get("code")) != code:
                continue
            for point in series.get("date") or []:
                base = point.get("currBase") or {}
                if base.get("value") is None:
                    continue
                period = date(point["year"], point["month"], 1)
                values[period] = IndexValue(
                    series_code=code,
                    series_name=SERIES.get(code, series.get("name") or code),
                    period=period,
                    value=float(base["value"]),
                    base_period=base.get("baseDesc"),
                )
    return [values[p] for p in sorted(values)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "cbs")
    parser.add_argument("--load", action="store_true", help="upsert into DATABASE_URL")
    args = parser.parse_args(argv)

    settings = load_settings()
    client = CbsIndexClient(settings.raw_data_dir, settings.request_delay_seconds)
    rows: list[IndexValue] = []
    failed = []
    for code in SERIES:
        try:
            series = parse_monthly(code, client.fetch_series(code))
        except httpx.HTTPError as exc:
            # One broken series should not block the others; the job still fails at the end.
            print(f"::warning::{code}: {type(exc).__name__}: {exc}")
            failed.append(code)
            continue
        print(f"{code}: {len(series)} months, {series[0].period} .. {series[-1].period}")
        rows.extend(series)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "official_indices.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([fl.name for fl in fields(IndexValue)])
        writer.writerows(astuple(row) for row in rows)

    if args.load:
        from apartment_data.storage.db import connect, upsert_official_indices

        with connect(settings) as conn:
            upsert_official_indices(conn, rows)
        print("Loaded into the database.")
    if failed:
        raise SystemExit(f"Failed series: {', '.join(failed)}")


if __name__ == "__main__":
    main()
