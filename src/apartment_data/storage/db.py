"""Postgres access for the ingestion jobs (Supabase, via DATABASE_URL)."""

from collections.abc import Iterable, Mapping
from dataclasses import astuple

import psycopg

from apartment_data.config import Settings
from apartment_data.reference.localities import Locality
from apartment_data.sources.cbs_index import IndexValue


def connect(settings: Settings) -> psycopg.Connection:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(settings.database_url)


def upsert_localities(conn: psycopg.Connection, localities: Iterable[Locality]) -> None:
    """Insert or update localities. Rows are never deleted, since deals reference them."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.localities (locality_code, name_he, name_en, municipal_status,
                district, sub_district, population, is_city)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (locality_code) do update set
                name_he = excluded.name_he,
                name_en = excluded.name_en,
                municipal_status = excluded.municipal_status,
                district = excluded.district,
                sub_district = excluded.sub_district,
                population = excluded.population,
                is_city = excluded.is_city,
                updated_at = now()
            """,
            [astuple(loc) for loc in localities],
        )


def upsert_official_indices(conn: psycopg.Connection, values: Iterable[IndexValue]) -> None:
    """Insert or update published index values, keyed by series and period."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.official_indices (series_code, series_name, period, value,
                base_period)
            values (%s, %s, %s, %s, %s)
            on conflict (series_code, period) do update set
                series_name = excluded.series_name,
                value = excluded.value,
                base_period = excluded.base_period,
                fetched_at = now()
            """,
            [astuple(v) for v in values],
        )


def replace_aliases(conn: psycopg.Connection, aliases: Mapping[str, int]) -> None:
    """Replace the whole aliases table; it is fully derived from the reference files."""
    with conn.cursor() as cur:
        cur.execute("delete from public.locality_aliases")
        cur.executemany(
            "insert into public.locality_aliases (alias, locality_code) values (%s, %s)",
            list(aliases.items()),
        )
