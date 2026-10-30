"""CBS localities reference table and the locality name aliases built from it.

Sources on data.gov.il:
- `localities-in-israel`: the yearly CBS localities file (one resource per year). The newest
  year fills `localities`; older years only contribute former names as aliases.
- `citiesandsettelments`: the Population Authority list, kept up to date, which adds its own
  Hebrew and English spellings as aliases.

Run `python -m apartment_data.reference.localities` to fetch, build and write CSV files, and
add `--load` to upsert them into the database at DATABASE_URL.
"""

import argparse
import csv
import re
from collections.abc import Iterable
from dataclasses import astuple, dataclass, fields
from pathlib import Path
from typing import Any

from apartment_data.config import REPO_ROOT, load_settings
from apartment_data.reference.geo import parse_cbs_coordinates
from apartment_data.reference.names import normalize_name
from apartment_data.sources.datagov import DataGovClient

CBS_PACKAGE = "localities-in-israel"
POPULATION_AUTHORITY_PACKAGE = "citiesandsettelments"
CITY_STATUS_CODE = 0  # 'עירייה'

# Alias priorities, lower wins when one spelling points at several localities.
PRIORITY_CBS_NAME = 0
PRIORITY_CBS_ENGLISH = 1
PRIORITY_POPULATION_AUTHORITY = 2
PRIORITY_HISTORICAL = 3
PRIORITY_MANUAL = 4

# Common short forms that no official file lists, mapped to the current CBS name.
MANUAL_ALIASES = {
    "תל אביב": "תל אביב -יפו",
    "תל אביב יפו": "תל אביב -יפו",
    "מודיעין": "מודיעין-מכבים-רעות",
    "יהוד": "יהוד-מונוסון",
    "מעלות": "מעלות-תרשיחא",
}

_CODE_KEYS = ("סמל יישוב", "סמל_ישוב", "סמל")
_NAME_KEYS = ("שם יישוב", "שם_ישוב")
_ENGLISH_KEYS = ("שם יישוב באנגלית", "תעתיק", "תעתיק פרסומים", "שם_ישוב_לועזי")


@dataclass(frozen=True)
class Locality:
    locality_code: int
    name_he: str
    name_en: str | None
    municipal_status: str | None
    district: str | None
    sub_district: str | None
    population: int | None
    is_city: bool
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class AliasResult:
    aliases: dict[str, int]
    ambiguous: dict[str, list[int]]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    text = _clean(value)
    return int(float(text)) if text is not None else None


def _first(record: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if _clean(record.get(key)) is not None:
            return record[key]
    return None


def _population(record: dict[str, Any]) -> int | None:
    key = next((k for k in record if k.startswith("סך הכל אוכלוסייה")), None)
    return _int(record[key]) if key else None


def parse_cbs_localities(records: Iterable[dict[str, Any]]) -> list[Locality]:
    """Map rows of a CBS localities file to `Locality` objects."""
    localities = []
    for record in records:
        code = _int(_first(record, _CODE_KEYS))
        name = _clean(_first(record, _NAME_KEYS))
        if code is None or name is None:
            continue
        position = parse_cbs_coordinates(record.get("קואורדינטות"))
        localities.append(
            Locality(
                locality_code=code,
                name_he=name,
                name_en=_clean(_first(record, _ENGLISH_KEYS)),
                municipal_status=_clean(record.get("שם מעמד מונציפאלי")),
                district=_clean(record.get("שם מחוז")),
                sub_district=_clean(record.get("שם נפה")),
                population=_population(record),
                is_city=_int(record.get("סמל מעמד מונציפאלי")) == CITY_STATUS_CODE,
                lat=position[0] if position else None,
                lon=position[1] if position else None,
            )
        )
    return localities


def names_from_records(records: Iterable[dict[str, Any]]) -> list[tuple[str, int]]:
    """(name, code) pairs for every Hebrew and English name in a localities table."""
    pairs = []
    for record in records:
        code = _int(_first(record, _CODE_KEYS))
        if code is None:
            continue
        for keys in (_NAME_KEYS, _ENGLISH_KEYS):
            name = _clean(_first(record, keys))
            if name:
                pairs.append((name, code))
    return pairs


def build_aliases(
    localities: Iterable[Locality], candidates: Iterable[tuple[str, int, int]]
) -> AliasResult:
    """Pick one locality per normalized spelling.

    `candidates` are (name, locality_code, priority) triples. Codes that are not in
    `localities` are ignored. When the best priority for a spelling is shared by several
    localities, the spelling is ambiguous and left out rather than guessed.
    """
    known = {loc.locality_code for loc in localities}
    best: dict[str, tuple[int, set[int]]] = {}
    for name, code, priority in candidates:
        key = normalize_name(name)
        if not key or code not in known:
            continue
        current = best.get(key)
        if current is None or priority < current[0]:
            best[key] = (priority, {code})
        elif priority == current[0]:
            current[1].add(code)

    aliases, ambiguous = {}, {}
    for key, (_, codes) in sorted(best.items()):
        if len(codes) == 1:
            aliases[key] = next(iter(codes))
        else:
            ambiguous[key] = sorted(codes)
    return AliasResult(aliases, ambiguous)


def cbs_resources_by_year(package: dict[str, Any]) -> dict[int, str]:
    """Map year to resource id for the yearly files in the CBS localities package."""
    by_year = {}
    for resource in package["resources"]:
        match = re.search(r"(19|20)\d{2}", resource.get("name") or "")
        if match and resource.get("datastore_active"):
            by_year[int(match.group())] = resource["id"]
    return by_year


def population_authority_resource(package: dict[str, Any]) -> str | None:
    """The continuously updated CSV with Hebrew headers in the Population Authority package."""
    for resource in package["resources"]:
        name = resource.get("name") or ""
        if (
            resource.get("format") == "CSV"
            and resource.get("datastore_active")
            and "מתעדכן" in name
            and "אנגלית" not in name
        ):
            return resource["id"]
    return None


def collect(client: DataGovClient, refresh: bool = False) -> tuple[list[Locality], AliasResult]:
    """Fetch every source and build the localities table and its aliases."""
    years = cbs_resources_by_year(client.package_show(CBS_PACKAGE))
    latest = max(years)
    current_records = client.datastore_records(years[latest], refresh=refresh)
    localities = parse_cbs_localities(current_records)

    candidates: list[tuple[str, int, int]] = []
    for loc in localities:
        candidates.append((loc.name_he, loc.locality_code, PRIORITY_CBS_NAME))
        if loc.name_en:
            candidates.append((loc.name_en, loc.locality_code, PRIORITY_CBS_ENGLISH))
    # Transliteration column, kept beside the English name in recent files.
    for record in current_records:
        code, translit = _int(_first(record, _CODE_KEYS)), _clean(record.get("תעתיק"))
        if code is not None and translit:
            candidates.append((translit, code, PRIORITY_CBS_ENGLISH))

    pa_id = population_authority_resource(client.package_show(POPULATION_AUTHORITY_PACKAGE))
    if pa_id:
        for name, code in names_from_records(client.datastore_records(pa_id, refresh=refresh)):
            candidates.append((name, code, PRIORITY_POPULATION_AUTHORITY))

    for year, resource_id in sorted(years.items()):
        if year == latest:
            continue
        for name, code in names_from_records(client.datastore_records(resource_id)):
            candidates.append((name, code, PRIORITY_HISTORICAL))

    by_name = {normalize_name(loc.name_he): loc.locality_code for loc in localities}
    for alias, canonical in MANUAL_ALIASES.items():
        code = by_name.get(normalize_name(canonical))
        if code is not None:
            candidates.append((alias, code, PRIORITY_MANUAL))

    return localities, build_aliases(localities, candidates)


def write_csv(path: Path, header: Iterable[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "reference")
    parser.add_argument("--refresh", action="store_true", help="ignore the raw response cache")
    parser.add_argument("--load", action="store_true", help="upsert into DATABASE_URL")
    args = parser.parse_args(argv)

    settings = load_settings()
    client = DataGovClient(settings.raw_data_dir, settings.request_delay_seconds)
    localities, result = collect(client, refresh=args.refresh)

    write_csv(
        args.out / "localities.csv",
        [f.name for f in fields(Locality)],
        (astuple(loc) for loc in localities),
    )
    write_csv(args.out / "locality_aliases.csv", ["alias", "locality_code"], result.aliases.items())
    print(
        f"{len(localities)} localities ({sum(loc.is_city for loc in localities)} cities), "
        f"{len(result.aliases)} aliases, {len(result.ambiguous)} ambiguous spellings skipped"
    )
    for alias, codes in result.ambiguous.items():
        print(f"  ambiguous: {alias!r} -> {codes}")

    if args.load:
        from apartment_data.storage.db import connect, replace_aliases, upsert_localities

        with connect(settings) as conn:
            upsert_localities(conn, localities)
            replace_aliases(conn, result.aliases)
        print("Loaded into the database.")


if __name__ == "__main__":
    main()
