# Apartment-data

Track Israeli apartment prices over time, per city, based on executed transactions
(Israel Tax Authority deals and CBS / LAMAS data).

**Website:** _coming soon — the link will be added here after the first Vercel deployment._

## Project layout

```
src/apartment_data/   Python package: sources, reference, transform, analytics, storage, export
supabase/migrations/  Database schema (Supabase Postgres)
web/                  Static website, deployed to Vercel
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
