# Apartment-data

Track Israeli apartment prices over time, per district and big city, from official
CBS / LAMAS data: average sale prices and rents by quarter and number of rooms, the
housing price index and the CPI, plus Bank of Israel mortgage rates.

**Website:** https://apartment-data.vercel.app: a map with a time slider, city
comparison over time, and a heatmap, in nominal or real (CPI-adjusted) prices; the monthly
mortgage payment on an average dwelling; and mortgage rates by track.

## Data pipeline

```bash
python -m apartment_data.reference.localities [--load]   # CBS localities, aliases, coordinates
python -m apartment_data.sources.cbs_index [--load]      # housing price indices and CPI
python -m apartment_data.sources.cbs_tables [--backfill] [--load]  # average prices and rents
python -m apartment_data.sources.boi_rates [--load]      # Bank of Israel mortgage rates
python -m apartment_data.export.web [--from-csv]         # web/data/data.json for the site
```

The `Update data` GitHub Actions workflow runs all of them monthly (and on demand), loads
Supabase using the `DATABASE_URL` secret and commits the refreshed website data.

## Project layout

```
src/apartment_data/   Python package: sources, reference, transform, analytics, storage, export
supabase/migrations/  Database schema (Supabase Postgres)
web/                  Static website (ECharts), deployed to Vercel; data in web/data/
tests/                Tests (pytest)
```

## Development

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` to work against the database.

See `HANDOFF.md` for the full plan, methodology and current status.
