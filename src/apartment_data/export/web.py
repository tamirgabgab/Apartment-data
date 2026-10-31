"""Export the database to the static JSON the website reads (`web/data/data.json`).

Run `python -m apartment_data.export.web` with DATABASE_URL set, or add `--from-csv` to build
it from the CSV files the source pipelines write under `data/` (handy for local work).
"""

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from apartment_data.config import REPO_ROOT, load_settings

CPI_CODE = "120010"
INDEX_CODES = ["40010", "60000", "60100", "60200", "60300", "60400", "60500", "70000"]
CHAIN_FROM = date(2010, 1, 1)  # CPI bases before this are not needed for the website

DISTRICTS = {
    1: ("מחוז ירושלים", "ירושלים", "60000"),
    2: ("מחוז הצפון", "הצפון", "60100"),
    3: ("מחוז חיפה", "חיפה", "60200"),
    4: ("מחוז המרכז", "המרכז", "60300"),
    5: ("מחוז תל אביב", "תל אביב", "60400"),
    6: ("מחוז הדרום", "הדרום", "60500"),
}
DISTRICT_BY_NAME = {short: code for code, (_, short, _) in DISTRICTS.items()}
ROOMS_ORDER = ["all", "1-2", "2.5-3", "3.5-4", "4.5-5", "4.5-6", "5.5-6"]

NOTES = [
    "מחירים ממוצעים של דירות שנמכרו (טבלה 2.2) ושכר דירה ממוצע (טבלה 4.9) מתוך הירחון "
    "לסטטיסטיקה של מחירים של הלשכה המרכזית לסטטיסטיקה, ללא תקנון איכות.",
    "הנתונים לרבעון האחרון ארעיים ועשויים להתעדכן.",
    "החל מהרבעון הרביעי של 2022 הממוצעים אינם כוללים עסקאות בסבסוד ממשלתי.",
    "מחיר ריאלי: מתואם למדד המחירים לצרכן, בשקלים של הרבעון האחרון.",
    'כשיש 5 עסקאות או פחות בתא, הלמ"ס אינה מפרסמת ממוצע.',
    "יחס מחיר לשכירות: המחיר הממוצע של דירה חלקי שכר הדירה השנתי הממוצע באותו מקום "
    "ורבעון, כלומר כמה שנות שכירות שווה דירה. זה יחס בין שני ממוצעים, לא של אותן דירות.",
    "ממוצע נע: הממוצע של 4 הרבעונים האחרונים, שמחליק קפיצות בין רבעונים.",
    "ריביות: הריבית הממוצעת על משכנתאות חדשות לפי מסלול, בכל המערכת הבנקאית, מתוך נתוני "
    "בנק ישראל. בנק ישראל אינו מפרסם את הריבית במסלול הפריים, ולכן מוצגת ריבית הפריים "
    "עצמה (ריבית בנק ישראל ועוד 1.5%). במסלול הפריים בפועל הבנקים נותנים לרוב הנחה או "
    "תוספת על ריבית זו.",
    "החזר חודשי: ההחזר ההתחלתי על הלוואה בלוח שפיצר, לפי המחיר הממוצע, אחוז המימון, "
    "התקופה והריבית הממוצעת באותו רבעון. במסלולים צמודים ההחזר גדל עם המדד, ובמסלול "
    "הפריים הוא משתנה עם הריבית. התמהיל הוא שליש פריים, שליש קבועה לא צמודה ושליש "
    "קבועה צמודה. זו הערכה, לא הצעה של בנק.",
]
RATE_ORDER = [
    "mortgage_fixed_unindexed",
    "mortgage_fixed_cpi",
    "mortgage_variable_cpi",
    "prime",
    "boi_rate",
]


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def quarter_of(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def chain_cpi(rows: Iterable[dict[str, Any]]) -> dict[date, float]:
    """Monthly CPI on one continuous scale, linking each 'YYYY ממוצע' base to the previous one.

    A new base 'YYYY ממוצע' sets the average of the months of YYYY to 100, and those months
    were published on the previous base, so the link factor is their average / 100.
    """
    months = sorted(
        ((_date(r["period"]), float(r["value"]), str(r["base_period"] or "")) for r in rows),
        key=lambda m: m[0],
    )
    chained: dict[date, float] = {}
    factors: dict[str, float] = {}
    for period, value, base in months:
        if period < CHAIN_FROM:
            continue
        if base not in factors:
            if not factors:
                factors[base] = 1.0
            else:
                year = int(base.split()[0])
                linked = [v for p, v in chained.items() if p.year == year]
                if len(linked) != 12:
                    raise ValueError(f"cannot link CPI base {base!r}: {len(linked)} months")
                factors[base] = fmean(linked) / 100
        chained[period] = value * factors[base]
    return chained


def quarterly_mean(monthly: dict[date, float]) -> dict[date, float]:
    groups: dict[date, list[float]] = defaultdict(list)
    for period, value in monthly.items():
        groups[quarter_of(period)].append(value)
    return {q: fmean(v) for q, v in groups.items() if len(v) == 3}


def build_rates(rates: list[dict[str, Any]], periods: list[date]) -> dict[str, Any]:
    """Monthly rates for the rates chart, and quarterly means aligned with the price periods.

    The chart starts at the first month with mortgage rates. A quarter's mean uses the months
    published so far, so the newest quarter can rest on one or two months.
    """
    monthly: dict[str, dict[date, float]] = defaultdict(dict)
    names: dict[str, str] = {}
    for row in rates:
        code = str(row["series_code"])
        monthly[code][_date(row["period"])] = float(row["value"])
        names[code] = str(row["series_name"])
    mortgage_months = [m for c, v in monthly.items() if c.startswith("mortgage_") for m in v]
    if not mortgage_months:
        return {"months": [], "series": {}, "quarterly": {}}
    start = min(mortgage_months)
    months = sorted({m for v in monthly.values() for m in v if m >= start})
    codes = [c for c in RATE_ORDER if c in monthly]
    quarterly = {}
    for code in codes:
        groups: dict[date, list[float]] = defaultdict(list)
        for month, value in monthly[code].items():
            groups[quarter_of(month)].append(value)
        quarterly[code] = [round(fmean(groups[p]), 3) if p in groups else None for p in periods]
    return {
        "months": [m.isoformat() for m in months],
        "series": {
            code: {"name": names[code], "values": [monthly[code].get(m) for m in months]}
            for code in codes
        },
        "quarterly": quarterly,
    }


def build_payload(
    localities: list[dict[str, Any]],
    indices: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    periods = sorted({_date(p["period"]) for p in prices})
    pos = {p: i for i, p in enumerate(periods)}
    by_code = {int(loc["locality_code"]): loc for loc in localities}

    series: dict[str, dict[str, dict[str, dict[str, list]]]] = {}
    rooms_seen: dict[str, set[str]] = defaultdict(set)
    places_used: set[tuple[str, int]] = set()
    for p in prices:
        kind, level, code, rooms = p["kind"], p["geo_level"], int(p["geo_code"]), p["rooms"]
        place_id = {"national": "n", "district": "d", "city": "c"}[level] + str(code)
        places_used.add((level, code))
        rooms_seen[kind].add(rooms)
        cell = series.setdefault(kind, {}).setdefault(place_id, {}).setdefault(rooms, {})
        i = pos[_date(p["period"])]
        for key, raw in (("price", p["avg_price"]), ("deals", p.get("n_deals"))):
            value = _float(raw)
            if kind == "rent" and key == "deals":
                continue
            values = cell.setdefault(key, [None] * len(periods))
            values[i] = None if value is None else (int(value) if key == "deals" else value)

    places = [{"id": "n0", "level": "national", "code": 0, "name": "כל הארץ"}]
    for code, (name, _, _) in DISTRICTS.items():
        if ("district", code) in places_used:
            places.append({"id": f"d{code}", "level": "district", "code": code, "name": name})
    cities = []
    for level, code in places_used:
        if level != "city":
            continue
        loc = by_code.get(code, {})
        district = DISTRICT_BY_NAME.get(str(loc.get("district") or ""))
        cities.append(
            {
                "id": f"c{code}",
                "level": "city",
                "code": code,
                "name": loc.get("name_he") or str(code),
                "name_en": loc.get("name_en"),
                "district": f"d{district}" if district else None,
                "population": int(loc["population"]) if loc.get("population") else None,
                "lat": _float(loc.get("lat")),
                "lon": _float(loc.get("lon")),
            }
        )
    places.extend(sorted(cities, key=lambda c: c["name"]))

    by_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in indices:
        by_series[str(row["series_code"])].append(row)

    cpi_q = quarterly_mean(chain_cpi(by_series.get(CPI_CODE, [])))
    covered = [p for p in periods if p in cpi_q]
    real_factor: list[float | None] = [None] * len(periods)
    base_quarter = covered[-1] if covered else None
    if base_quarter:
        for p in covered:
            real_factor[pos[p]] = round(cpi_q[base_quarter] / cpi_q[p], 5)

    index_payload = {}
    for code in INDEX_CODES:
        rows = by_series.get(code, [])
        if not rows:
            continue
        quarterly = quarterly_mean({_date(r["period"]): float(r["value"]) for r in rows})
        index_payload[code] = {
            "name": rows[0]["series_name"],
            "values": [round(quarterly[p], 2) if p in quarterly else None for p in periods],
        }

    return {
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "periods": [p.isoformat() for p in periods],
        "places": places,
        "rooms": {k: [r for r in ROOMS_ORDER if r in v] for k, v in sorted(rooms_seen.items())},
        "series": series,
        "real_factor": real_factor,
        "real_base": base_quarter.isoformat() if base_quarter else None,
        "indices": index_payload,
        "district_index": {f"d{c}": idx for c, (_, _, idx) in DISTRICTS.items()},
        "rates": build_rates(rates or [], periods),
        "notes": NOTES,
    }


def load_from_db(settings) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    from psycopg.rows import dict_row

    from apartment_data.storage.db import connect

    with connect(settings) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from public.localities")
        localities = cur.fetchall()
        cur.execute("select * from public.official_indices")
        indices = cur.fetchall()
        cur.execute("select * from public.cbs_average_prices")
        prices = cur.fetchall()
        cur.execute("select * from public.interest_rates")
        rates = cur.fetchall()
    return localities, indices, prices, rates


def load_from_csv(data_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    def read(path: Path) -> list[dict]:
        with path.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))

    rates = data_dir / "boi" / "interest_rates.csv"
    return (
        read(data_dir / "reference" / "localities.csv"),
        read(data_dir / "cbs" / "official_indices.csv"),
        read(data_dir / "cbs" / "average_prices.csv"),
        read(rates) if rates.exists() else [],
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "web" / "data")
    parser.add_argument("--from-csv", action="store_true", help="read data/ CSVs, not the DB")
    args = parser.parse_args(argv)

    settings = load_settings()
    loaded = load_from_csv(REPO_ROOT / "data") if args.from_csv else load_from_db(settings)
    payload = build_payload(*loaded)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "data.json"
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    target.write_text(text, encoding="utf-8")
    n = sum(len(v) for v in payload["series"].values())
    print(
        f"Wrote {target} ({len(text) // 1024} KB, {len(payload['periods'])} quarters, {n} series)"
    )


if __name__ == "__main__":
    main()
