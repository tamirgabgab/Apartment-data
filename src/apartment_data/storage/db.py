"""Postgres access for the ingestion jobs (Supabase, via DATABASE_URL)."""

from collections.abc import Iterable, Mapping
from dataclasses import astuple

import psycopg

from apartment_data.config import Settings
from apartment_data.reference.localities import Locality
from apartment_data.sources.cbs_index import IndexValue
from apartment_data.sources.cbs_tables import AveragePrice


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL is missing or malformed. Never carries any part of the URL."""


def connect(settings: Settings) -> psycopg.Connection:
    if not settings.database_url:
        raise DatabaseConfigError("DATABASE_URL is not set")
    try:
        return psycopg.connect(settings.database_url)
    except psycopg.ProgrammingError:
        # psycopg quotes the offending part of the URL, which can be the password, and
        # GitHub Actions logs are public. Report the problem without the original message.
        raise DatabaseConfigError(
            "DATABASE_URL is not a valid connection string. Check that the password has "
            "only letters and digits and that '[YOUR-PASSWORD]' was fully replaced."
        ) from None


def upsert_localities(conn: psycopg.Connection, localities: Iterable[Locality]) -> None:
    """Insert or update localities. Rows are never deleted, since deals reference them."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.localities (locality_code, name_he, name_en, municipal_status,
                district, sub_district, population, is_city, lat, lon)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (locality_code) do update set
                name_he = excluded.name_he,
                name_en = excluded.name_en,
                municipal_status = excluded.municipal_status,
                district = excluded.district,
                sub_district = excluded.sub_district,
                population = excluded.population,
                is_city = excluded.is_city,
                lat = excluded.lat,
                lon = excluded.lon,
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


def upsert_average_prices(conn: psycopg.Connection, values: Iterable[AveragePrice]) -> None:
    """Insert or update CBS average prices, never replacing a value from a newer edition."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.cbs_average_prices (kind, geo_level, geo_code, period, rooms,
                avg_price, n_deals, sampling_error, edition)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (kind, geo_level, geo_code, period, rooms) do update set
                avg_price = excluded.avg_price,
                n_deals = excluded.n_deals,
                sampling_error = excluded.sampling_error,
                edition = excluded.edition,
                fetched_at = now()
            where excluded.edition >= cbs_average_prices.edition
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
