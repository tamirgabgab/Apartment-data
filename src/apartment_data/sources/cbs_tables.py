"""CBS Price Statistics Monthly tables of average prices by district and big city.

- Table 2.2: average prices of dwellings sold (NIS thousand), with number of transactions.
- Table 4.9: average monthly rent (NIS), with sampling errors.

Both tables are published monthly as Excel files (English edition) and each edition covers
roughly the last two years by quarter and by number of rooms. Older periods only appear in
older editions, so a backfill walks every edition; values from newer editions win, since
recent quarters are provisional and revised.

Run `python -m apartment_data.sources.cbs_tables [--backfill] [--load]`.
"""

import argparse
import csv
import io
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import astuple, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import openpyxl
import xlrd

from apartment_data.config import REPO_ROOT, load_settings

BASE_URL = "https://www.cbs.gov.il/he/publications/Madad/DocLib"
USER_AGENT = "apartment-data/0.1 (+https://github.com/tamirgabgab/Apartment-data)"


@dataclass(frozen=True)
class TableSpec:
    kind: str  # 'sale' or 'rent'
    folder_suffix: str  # publication folder is f"price{MM}{suffix}"
    file_stem: str
    price_factor: float  # multiply published prices to get NIS
    first_edition: tuple[int, int]  # earliest (year, month) edition worth trying


TABLES = {
    "sale": TableSpec("sale", "aa", "aa2_2_e", 1000.0, (2018, 12)),
    "rent": TableSpec("rent", "a", "a4_9_e", 1.0, (2018, 12)),
}

DISTRICT_CODES = {
    "jerusalem": 1,
    "north": 2,
    "northern": 2,
    "haifa": 3,
    "center": 4,
    "central": 4,
    "centeral": 4,
    "tel aviv": 5,
    "south": 6,
    "southern": 6,
}
# Big cities as named in editions that print no locality code (codes from later editions).
CITY_CODES = {
    "ashdod": 70,
    "ashkelon": 7100,
    "beer sheva": 9000,
    "beit shemesh": 2610,
    "bnei brak": 6100,
    "bat yam": 6200,
    "herzliya": 6400,
    "herzlliya": 6400,
    "hadera": 6500,
    "holon": 6600,
    "haifa": 4000,
    "jerusalem": 3000,
    "kfar saba": 6900,
    "netanya": 7400,
    "petah tiqwa": 7900,
    "rishon lezion": 8300,
    "rehovot": 8400,
    "ramat gan": 8600,
    "tel aviv": 5000,
}
QUARTER_MONTH = {"I-III": 1, "IV-VI": 4, "VII-IX": 7, "X-XII": 10}

_ROOMS = re.compile(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$")
_ROOMS_UP_TO = re.compile(r"^up to (\d+(?:\.\d+)?)(?: rooms?)?$", re.IGNORECASE)
_ROOMS_PLUS = re.compile(r"^(\d+(?:\.\d+)?)\s*\+$")
# The rent table's top group was published as '4.5-6' and later as '4.5+'.
_OPEN_TOP = {"4.5": "4.5-6"}
_CODED_NAME = re.compile(r"^(.*?)\s*-\s*(\d+)\s*$")
_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"


@dataclass(frozen=True)
class AveragePrice:
    kind: str
    geo_level: str  # 'national', 'district' or 'city'
    geo_code: int  # 0 for national, district number, or CBS locality code
    period: date  # first day of the quarter
    rooms: str  # 'all' or a range such as '2.5-3'
    avg_price: float | None  # NIS
    n_deals: int | None
    sampling_error: float | None
    edition: str  # 'YYYY-MM' of the publication


class UnknownGeography(ValueError):
    pass


def _cell(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def read_rows(content: bytes) -> list[list[Any]]:
    """Rows of the first sheet of an .xlsx or .xls file, with empty cells as None."""
    if content.startswith(_XLSX_MAGIC):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        return [[_cell(v) for v in row] for row in wb.worksheets[0].iter_rows(values_only=True)]
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    return [[_cell(v) for v in sheet.row_values(i)] for i in range(sheet.nrows)]


def normalize_rooms(label: str) -> str | None:
    """'3-2.5' and '2.5-3' both become '2.5-3'; anything else returns None."""
    label = label.strip()
    if match := _ROOMS_UP_TO.match(label):
        return f"1-{float(match.group(1)):g}"
    if match := _ROOMS_PLUS.match(label):
        low = f"{float(match.group(1)):g}"
        return _OPEN_TOP.get(low, f"{low}+")
    match = _ROOMS.match(label)
    if not match:
        return None
    low, high = sorted((float(match.group(1)), float(match.group(2))))
    return f"{low:g}-{high:g}"


def _number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _column_map(rows: list[list[Any]], header: int) -> dict[int, tuple[date, str]]:
    """Map column index to (quarter start, measure) from the three header rows."""
    years, periods, measures = rows[header], rows[header + 1], rows[header + 2]
    width = max(len(years), len(periods), len(measures))
    columns = {}
    year = period = None
    for j in range(1, width):
        y = years[j] if j < len(years) else None
        p = periods[j] if j < len(periods) else None
        m = measures[j] if j < len(measures) else None
        if y is not None and re.fullmatch(r"\d{4}(\.0)?", str(y)):
            year = int(float(y))
        if p is not None:
            period = re.sub(r"\s+", " ", str(p))
        if m is None or year is None or period not in QUARTER_MONTH:
            continue
        text = str(m).lower()
        if "average" in text:
            measure = "price"
        elif "transac" in text:
            measure = "n_deals"
        elif "sampling" in text:
            measure = "sampling_error"
        else:
            continue
        columns[j] = (date(year, QUARTER_MONTH[period], 1), measure)
    return columns


def parse_table(
    rows: list[list[Any]],
    spec: TableSpec,
    edition: str,
    unknown: set[str] | None = None,
) -> list[AveragePrice]:
    """Parse one edition. Labels of unrecognized places are skipped and added to `unknown`."""
    header = next(
        i for i, row in enumerate(rows) if row and str(row[0] or "").startswith("Districts")
    )
    columns = _column_map(rows, header)
    results: list[AveragePrice] = []
    section = None
    geo: tuple[str, int] | None = None

    for row in rows[header + 3 :]:
        label = str(row[0]).strip() if row and row[0] is not None else ""
        if not label:
            continue
        if label.startswith("("):
            break
        values: dict[date, dict[str, float | None]] = {}
        for j, (period, measure) in columns.items():
            if j < len(row):
                values.setdefault(period, {})[measure] = _number(row[j])
        if not any(v is not None for m in values.values() for v in m.values()):
            low = label.lower()
            if "district" in low:
                section = "district"
            elif "cit" in low:
                section = "city"
            continue

        rooms = normalize_rooms(label)
        if rooms is None:
            rooms = "all"
            try:
                geo = _geography(label, section)
            except UnknownGeography:
                geo = None
                if unknown is not None:
                    unknown.add(label)
        if geo is None:
            continue
        for period, measures in sorted(values.items()):
            price = measures.get("price")
            n_deals = measures.get("n_deals")
            results.append(
                AveragePrice(
                    kind=spec.kind,
                    geo_level=geo[0],
                    geo_code=geo[1],
                    period=period,
                    rooms=rooms,
                    avg_price=round(price * spec.price_factor, 1) if price is not None else None,
                    n_deals=int(n_deals) if n_deals is not None else None,
                    sampling_error=measures.get("sampling_error"),
                    edition=edition,
                )
            )
    return results


def _geography(label: str, section: str | None) -> tuple[str, int]:
    if label.lower() == "total":
        return ("national", 0)
    match = _CODED_NAME.match(label)
    name, code = (match.group(1), int(match.group(2))) if match else (label, None)
    key = re.sub(r"\s*district\s*", " ", name.lower()).strip()
    if section != "city" and ("district" in name.lower() or key in DISTRICT_CODES):
        return ("district", code if code is not None else DISTRICT_CODES[key])
    if code is None:
        code = CITY_CODES.get(re.sub(r"\s+", " ", name.lower()))
    if code is None:
        raise UnknownGeography(label)
    return ("city", code)


def merge_editions(values: Iterable[AveragePrice]) -> list[AveragePrice]:
    """Keep one value per key, from the newest edition."""
    best: dict[tuple, AveragePrice] = {}
    for v in values:
        key = (v.kind, v.geo_level, v.geo_code, v.period, v.rooms)
        if key not in best or v.edition > best[key].edition:
            best[key] = v
    return sorted(best.values(), key=lambda v: (v.kind, v.geo_level, v.geo_code, v.period, v.rooms))


class CbsTablesClient:
    """Throttled downloader that caches every edition file (editions never change)."""

    def __init__(
        self, cache_dir: Path, delay_seconds: float = 1.0, client: httpx.Client | None = None
    ) -> None:
        self.cache_dir = cache_dir / "cbs" / "tables"
        self.delay_seconds = delay_seconds
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
        )
        self._last_request = 0.0

    def _get(self, url: str) -> bytes | None:
        wait = self._last_request + self.delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        response = self._client.get(url)
        self._last_request = time.monotonic()
        if response.status_code == 404:
            return None
        response.raise_for_status()
        content = response.content
        # Missing files come back as a small HTML page with status 200.
        return content if content[:4] in (_XLSX_MAGIC, _XLS_MAGIC) else None

    def edition(self, spec: TableSpec, year: int, month: int) -> bytes | None:
        stem = self.cache_dir / f"{spec.file_stem}_{year}_{month:02d}"
        for ext in ("xlsx", "xls"):
            if stem.with_suffix(f".{ext}").exists():
                return stem.with_suffix(f".{ext}").read_bytes()
        missing = stem.with_suffix(".missing")
        if missing.exists():
            return None
        folder = f"{BASE_URL}/{year}/price{month:02d}{spec.folder_suffix}"
        for ext in ("xlsx", "xls"):
            content = self._get(f"{folder}/{spec.file_stem}.{ext}")
            if content is not None:
                cached = self.cache_dir / f"{spec.file_stem}_{year}_{month:02d}.{ext}"
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(content)
                return content
        # A past month without a file stays missing; the current month may still appear.
        if (year, month) < (date.today().year, date.today().month):
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.touch()
        return None


def months(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    year, month = start
    while (year, month) <= end:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def collect(
    client: CbsTablesClient,
    spec: TableSpec,
    editions: Iterable[tuple[int, int]],
) -> tuple[list[AveragePrice], list[str]]:
    """Parse every available edition. Returns the values and a list of warnings."""
    values, warnings = [], []
    for year, month in editions:
        content = client.edition(spec, year, month)
        if content is None:
            continue
        edition = f"{year}-{month:02d}"
        unknown: set[str] = set()
        try:
            values.extend(parse_table(read_rows(content), spec, edition, unknown))
        except (StopIteration, ValueError) as exc:
            warnings.append(f"{spec.kind} {edition}: cannot parse ({type(exc).__name__}: {exc})")
        if unknown:
            warnings.append(f"{spec.kind} {edition}: skipped unknown places {sorted(unknown)}")
    return values, warnings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "cbs")
    parser.add_argument("--backfill", action="store_true", help="walk every edition")
    parser.add_argument("--load", action="store_true", help="upsert into DATABASE_URL")
    args = parser.parse_args(argv)

    settings = load_settings()
    client = CbsTablesClient(settings.raw_data_dir, settings.request_delay_seconds)

    today = date.today()
    end = (today.year, today.month)
    rows: list[AveragePrice] = []
    for spec in TABLES.values():
        if args.backfill:
            start = spec.first_edition
        else:
            start = (today.year - 1, today.month) if today.month > 1 else (today.year - 2, 12)
        values, warnings = collect(client, spec, months(start, end))
        for warning in warnings:
            print(f"warning: {warning}")
        merged = merge_editions(values)
        editions = sorted({v.edition for v in values})
        print(
            f"{spec.kind}: {len(merged)} values from {len(editions)} editions "
            f"({editions[0] if editions else '-'} .. {editions[-1] if editions else '-'})"
        )
        rows.extend(merged)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "average_prices.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([fl.name for fl in fields(AveragePrice)])
        writer.writerows(astuple(row) for row in rows)

    if args.load:
        from apartment_data.storage.db import connect, upsert_average_prices

        with connect(settings) as conn:
            upsert_average_prices(conn, rows)
        print("Loaded into the database.")


if __name__ == "__main__":
    main()
