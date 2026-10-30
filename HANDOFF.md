# HANDOFF

Living document that carries project context between work sessions.
Read it at the start of every session and update it at the end.

_Last updated: 2026-10-30_

---

## 1. Project goal

Collect Israeli housing price data from multiple sources and **track apartment prices
over time, broken down by city**, based on **executed transactions only** (apartments
that were actually sold), and publish it as an **interactive website** linked from
the README.

## 2. Decisions so far

| Topic | Decision |
|---|---|
| Scope | Cities only for now: CBS municipal status "עירייה" (about 80 cities) |
| History | As far back as possible, target from 2000 onward |
| Output | Interactive, **public** website, link in `README.md` |
| Website stack | Plain static HTML + a chart library (ECharts / Chart.js), no framework |
| Storage / hosting | New dedicated Supabase project (data) and Vercel project (website) |
| Update frequency | Deals weekly, CBS series monthly |
| Price type | Executed transactions only. Asking prices of active listings are **out of scope** |
| Yad2 / Madlan | Allowed, but only their executed-deal data, not listings |
| Dev network | Owner will add the source hosts to the environment's Allowed domains |

## 3. Current state

- Phase 0 mostly done: Python package skeleton (`src/apartment_data/`), `pyproject.toml`,
  ruff + pytest, CI workflow (`.github/workflows/ci.yml`), `.env.example`,
  placeholder website (`web/index.html`, Hebrew RTL).
- **Supabase:** project `apartment-data`, ref `mbjownaqzevdhinczrgx`, region
  `eu-central-1` (Frankfurt), free plan, org "tamirgabgab's Org".
  - Migration `initial_schema` applied (tables: `localities`, `locality_aliases`,
    `deals`, `official_indices`, `city_price_stats`, `ingestion_runs`). RLS is on with
    no policies on purpose: the website reads static JSON, only the ingestion jobs
    (postgres role via `DATABASE_URL`) touch the database.
  - Migration `index_tweaks` applied: index on `locality_aliases.locality_code`.
  - Deferred: `drop index public.deals_valid_locality_date_idx` (redundant partial index,
    saves a little storage). The Supabase MCP asks for a confirmation on destructive
    statements and the prompt never reached the owner, so it was split out. Run it in
    a later migration, or by hand in the Supabase SQL Editor.
- **Vercel:** project `apartment-data` (id `prj_859ty9pe0LsMUupyS13M2bnI4U9C`, team
  `team_ZhDyYoJQ7ch1tCHoRn41zIrH`, Hobby plan), linked to `tamirgabgab/Apartment-data`,
  root directory `web`. Production deploys from `main` to
  **https://apartment-data.vercel.app** (linked in `README.md`); other branches get
  preview deployments. Deployment protection is the default (`all_except_custom_domains`);
  the session network cannot reach `vercel.app`, so the owner has to confirm the
  production URL opens without a Vercel login. Relax protection if it does not.
- **Network:** the environment uses Custom network access with the source hosts in
  Allowed domains. Verified working on 2026-10-30: `www.nadlan.gov.il` (site HTML),
  `api.cbs.gov.il` (price-index API returns JSON; the bare root does not answer, that is
  normal), `data.gov.il` (CKAN API returns JSON; the bare root returns a WAF 403, that is
  normal), `www.cbs.gov.il`, `apartment-data.vercel.app`. Yad2 / Madlan are not allowed
  on purpose (deferred). GitHub Actions is not affected by these settings.
- **Website:** https://apartment-data.vercel.app is public (no Vercel login).
- **Phase 1:** `python -m apartment_data.reference.localities [--load]` builds
  `localities` (newest CBS file, 1,484 localities, 82 cities) and `locality_aliases`
  (2,864 normalized spellings, ambiguous ones skipped) and writes CSVs to `data/reference/`.
- **Loading runs in GitHub Actions**, not in the cloud session: the session network only
  allows HTTPS through a proxy, so it cannot open Postgres connections. The workflow
  `.github/workflows/update-data.yml` (manual dispatch + monthly on the 20th) loads
  localities, aliases and CBS indices using the `DATABASE_URL` repository secret
  (Supabase session pooler string). Dispatch it with the GitHub MCP `actions_run_trigger`
  on `main`. Loaded 2026-10-30: 1,484 localities, 2,864 aliases, 1,928 index values.
- **Security note:** a malformed `DATABASE_URL` once printed part of the password into a
  public Actions log (logs deleted, password reset, `connect()` now hides the URL). Keep the
  database password to letters and digits.
- Cleanup pending: `drop extension if exists http;` (installed for a one-off load; the
  Supabase MCP confirmation prompt timed out). Run it in the SQL Editor.
- **nadlan.gov.il is blocked by its Terms of Use** (see `docs/sources/nadlan.md`): they
  forbid scripts, bots and API use without explicit permission, and any non-personal use
  needs written approval; the deals API is behind reCAPTCHA Enterprise. Nothing is fetched
  from it. Owner decision: two tracks in parallel:
  1. Build the site now on official CBS data (Phase 2).
  2. Request deal data: drafts in `docs/requests/permission-nadlan.md` (Survey of Israel)
     and `docs/requests/foi-tax-authority.md` (FOI request). The owner sends them.
- **Phase 2:** `python -m apartment_data.sources.cbs_index [--load]` fetches the national
  and six district housing price indices and the CPI (1,928 monthly values) as published,
  with their base (loaded). District indices start 2017-10.
- If deal data arrives later: raw responses go to a private Supabase Storage bucket, and the
  pilot cities are Tel Aviv-Yafo, Jerusalem, Haifa, Beer Sheva, Sderot (owner decisions).

---

## 4. Data sources

| Source | What it gives | Role | Access |
|---|---|---|---|
| **nadlan.gov.il** (Israel Tax Authority deals) | Every reported sale: date, price, address / gush-helka, rooms, area, floor, build year, deal type, fraction sold | **Primary source of truth** for transactions | Public site backed by an unofficial, undocumented JSON API that changes from time to time |
| **CBS / LAMAS – Localities file** (קובץ יישובים) | Official locality codes (סמל יישוב), Hebrew/English names, municipal status, district, population | **Reference table**, defines which localities are "cities" | data.gov.il (CKAN API) / CBS site |
| **CBS – Housing Price Index** (מדד מחירי הדירות) | Official quality-adjusted index, national and by district, long history | Baseline and validation; covers years where deal data is sparse | Official CBS price-index API + Excel tables |
| **CBS – Average dwelling prices by city** | Average transaction price by city and number of rooms, quarterly | Validation per city | Excel tables in CBS publications |
| **CBS – Consumer Price Index** | Inflation | Convert nominal prices to real prices | Official CBS price-index API |
| **Yad2 – "deals" section** | Executed deals shown on Yad2 | Cross-check only | No public API; ToS restrictions |
| **Madlan – deals data** | Executed deals shown on Madlan | Cross-check only | No public API; ToS restrictions |

Key observation about Yad2 and Madlan: their **executed-deal** data is itself derived
from the Tax Authority reports, i.e. the same data as nadlan.gov.il, sometimes with
extra enrichment (geocoding, neighborhood). Therefore:

- nadlan.gov.il is the single source of truth for deals.
- Yad2 / Madlan add little new information and carry ToS / anti-bot risk, so they
  are deferred to a later, optional cross-validation phase.
- Their listing (asking) prices are explicitly excluded.

Notes:
- **Verify endpoints at implementation time.** nadlan.gov.il has been redesigned more
  than once; do not trust hard-coded URLs from old blog posts or GitHub projects.
- **History:** online deal coverage for the early 2000s must be checked. If deal
  data before some year is sparse, the site will show the CBS index for those years
  and mark the switch clearly.
- Respect rate limits: throttle requests, cache raw responses, never hammer a site.

---

## 5. Architecture

```
GitHub Actions (cron)
   │  Python fetchers: nadlan, CBS
   ▼
raw responses (gzipped JSON, kept for re-parsing)
   │
   ▼
normalize + clean + map to CBS locality code
   │
   ▼
Supabase Postgres ── deals, localities, official_indices
   │
   ▼
aggregation job ── city_price_stats (per city / quarter / segment)
   │
   ├──► export to static JSON files
   ▼
Vercel website (interactive charts, Hebrew RTL UI) ── link in README
```

Stack:

- **Ingestion and analytics:** Python 3.12, `httpx`, `polars` or `pandas`, `pydantic`,
  `pytest`, `ruff`. Runs in GitHub Actions on a schedule.
- **Database:** Supabase Postgres.
- **Website:** static site on Vercel (Next.js static export, or plain HTML + a chart
  library such as ECharts / Chart.js). It reads small pre-computed JSON files, so it
  is fast, cheap, and does not expose the database directly.

Storage sizing (to keep an eye on): Israel has roughly 100k residential deals per
year. Cities only, 2000 to today, may reach 1.5–2.5 million rows. The Supabase free
tier is 500 MB, which can be tight with indexes. Options if needed: keep only the
needed columns in Postgres, store raw responses as compressed files outside the
database (GitHub release assets / Vercel Blob / Supabase Storage), or upgrade the plan.

Proposed repository layout:

```
src/apartment_data/
    sources/          # nadlan.py, cbs.py (yad2.py, madlan.py later)
    reference/        # localities, name aliases
    transform/        # cleaning, normalization, deduplication
    analytics/        # medians, rolling windows, indices, CPI deflation
    storage/          # Supabase / Postgres access layer
    export/           # JSON export for the website
supabase/migrations/  # SQL schema
web/                  # the website (deployed to Vercel)
tests/
.github/workflows/    # scheduled ingestion + aggregation
```

### Data model (draft)

- `localities` — `locality_code` (CBS code, PK), `name_he`, `name_en`,
  `municipal_status`, `district`, `sub_district`, `population`, `is_city`.
- `locality_aliases` — alternative spellings mapped to `locality_code`.
- `deals` — `deal_id` (source key or stable hash, PK), `source`, `deal_date`,
  `price_ils`, `locality_code`, `street`, `house_number`, `gush`, `helka`,
  `sub_helka`, `rooms`, `area_sqm`, `floor`, `build_year`, `property_type`,
  `deal_nature`, `fraction_sold`, `is_new_construction`, `is_valid`,
  `invalid_reason`, `fetched_at`.
- `official_indices` — CBS series (housing index, CPI) stored as-is.
- `city_price_stats` — `locality_code`, `period` (quarter), `segment`, `n_deals`,
  `median_price`, `median_price_per_sqm`, `p25`, `p75`, `real_median_price_per_sqm`,
  `is_reliable`, `is_provisional`.

---

## 6. Methodology

Raw averages are misleading because the mix of sold apartments changes every period.
The plan, from simplest to most robust:

1. **Median price per sqm** per city per quarter, plus number of deals. MVP metric.
2. **Segments**: rooms (up to 3, 4, 5+) and new vs. second-hand.
3. **Reliability**: rolling 4-quarter median and an `is_reliable` flag when
   `n_deals` is below a threshold (e.g. 20). The last 1–2 quarters are flagged
   `is_provisional` because reports arrive with a delay.
4. **Real prices**: deflate by CPI so inflation is separated from real appreciation.
5. **Later — quality-adjusted index**: hedonic regression or repeat-sales index,
   validated against the CBS index at district level.

Cleaning rules (applied before any statistic):

- Partial sales (`fraction_sold < 1`): exclude, or normalize price by the fraction.
- Non-market deals: zero / symbolic prices, extreme low prices, family transfers.
- Outliers per city and period (outside the 1st–99th percentile of price per sqm).
- Duplicates (same gush-helka-sub-helka, date and price).
- Residential types only (apartment, garden apartment, penthouse, duplex, cottage...).
- Every deal mapped to a CBS `locality_code` via the aliases table.
- Invalid deals are kept in the table with `is_valid = false` and a reason, never
  silently dropped, so the rules can be audited and changed.

---

## 7. Website (MVP features)

- City selector with search (Hebrew), price trend chart per quarter.
- Toggle: price per sqm / total price, nominal / real (CPI adjusted).
- Segment filter: rooms, new vs. second-hand.
- Compare up to several cities on one chart.
- Number of deals shown under the chart; unreliable / provisional points marked.
- CBS index overlay for context.
- "Last updated" date and data source credits.
- Hebrew RTL interface, mobile friendly.

---

## 8. Roadmap

### Phase 0 — Setup
- [x] Answer the open questions (section 9).
- [x] Allow the source hosts in the environment network settings (section 3).
- [x] Python project skeleton: `pyproject.toml`, `ruff`, `pytest`, `.gitignore`, src layout.
- [x] CI workflow (lint + tests).
- [x] Create the Supabase project and apply the initial schema.
- [x] Apply the `index_tweaks` migration.
- [ ] Drop the redundant partial index `deals_valid_locality_date_idx` (deferred).
- [x] Create the Vercel project and link it to the repository.
- [x] Add `DATABASE_URL` as a GitHub repository secret.
- [x] Merge to `main`, get the production URL, put it in `README.md`.
- [x] Confirm https://apartment-data.vercel.app opens without a Vercel login.

### Phase 1 — Reference data
- [x] Ingest the CBS localities file into `localities`, mark `is_city`.
- [x] Build `locality_aliases` (code done).
- [x] Load `locality_aliases` into Supabase.

### Phase 2 — CBS series
- [x] Housing price index (national + districts) and CPI fetcher (`sources/cbs_index.py`).
- [x] Load them into `official_indices`.
- [ ] CBS average prices by city for validation.

### Phase 3 — Transactions (blocked: needs permission or FOI data)
- [x] Investigate the current API, document it in `docs/sources/nadlan.md` (ToS forbid it).
- [x] Draft the permission request and the FOI request (`docs/requests/`).
- [ ] Owner sends both requests; track the answers here.
- [ ] Fetcher per city and date range, with throttling, retries and raw caching.
- [ ] Pilot on 3–5 cities, check how far back the data really goes.
- [ ] Backfill all cities from 2000 (or the earliest available year).
- [ ] Incremental updates: recent months only, upsert by `deal_id`.

### Phase 4 — Cleaning and validation
- [ ] Implement the cleaning rules from section 6.
- [ ] Data validation tests (schema, ranges, null rates, duplicates).
- [ ] Compare our city medians against CBS averages by city.

### Phase 5 — Analytics
- [ ] `city_price_stats` per quarter and segment, rolling medians, flags.
- [ ] CPI-deflated prices.

### Phase 6 — Website
- [ ] JSON export job.
- [ ] Interactive site (section 7), deploy to Vercel, add the link to `README.md`.

### Phase 7 — Automation
- [ ] GitHub Actions cron: weekly deals update, monthly CBS update, then re-export.
- [ ] Alerts when a source fails or returns an unexpected schema.

### Phase 8 — Optional
- [ ] Cross-check against Yad2 / Madlan deal data (after ToS review).
- [ ] Hedonic / repeat-sales index.
- [ ] Extend beyond cities: local councils, neighborhoods.

---

## 9. Open questions (for the project owner)

- Which CBS city-level table to use for average prices by city (CBS publishes average
  dwelling prices for selected large cities, quarterly, in Excel). To be checked next.
- Answers to the two data requests (`docs/requests/`).

## 10. Risks

- Unofficial APIs (nadlan.gov.il) can change without notice — each source is isolated
  in its own module and raw responses are kept so data can be re-parsed.
- Deal reports arrive weeks to months late; recent quarters are provisional.
- Early-2000s deal coverage may be sparse.
- Supabase free-tier size limit (see section 5).
- ToS / legal exposure if Yad2 / Madlan are scraped.

## 11. Session log

- **2026-10-30 (1)** — Repository reviewed (empty). Wrote the first version of this
  handoff and added project `CLAUDE.md`.
- **2026-10-30 (2)** — Owner decisions recorded (cities, from 2000, interactive site
  on Vercel, Supabase, executed deals only). Found that Yad2 / Madlan deal data is
  derived from the Tax Authority, so nadlan.gov.il is the primary source. Found that
  the session network blocks all data source hosts. Next: answer section 9, then Phase 0.
- **2026-10-30 (3)** — Owner answered all open questions (section 2). Phase 0: added the
  Python skeleton, CI, placeholder site, created Supabase project `apartment-data` and
  applied the initial schema. Pending: `index_tweaks` migration, Vercel access approval
  and project, `DATABASE_URL` secret, network allow-list. Next: finish Phase 0, then
  Phase 1 (CBS localities).
- **2026-10-30 (4)** — Owner approved Vercel access; Vercel project created and linked.
  The `index_tweaks` migration timed out again on the Supabase confirmation prompt, so
  it was split: the index creation is applied, the index drop is deferred. Merged the
  branch into `main` for a first production deployment on Vercel.
- **2026-10-30 (5)** — Owner switched the environment to Custom network access. Verified
  that nadlan.gov.il, the CBS price-index API and the data.gov.il CKAN API all return
  data, and that the production website is public. Found the data.gov.il datasets
  `citiesandsettelments` and `localities-in-israel` for Phase 1. Next: Phase 3 nadlan API
  investigation or Phase 1 localities, per owner choice.
- **2026-10-30 (6)** — Owner chose Phase 1 then Phase 3, all localities, load now, mixed
  pilot cities, Supabase Storage for raw data. Phase 1 code and tests added; `localities`
  loaded (1,484 rows, 82 cities). Aliases wait for `DATABASE_URL`; `http` extension drop
  is pending (MCP confirmation timed out). Next: Phase 3 nadlan API investigation.
- **2026-10-30 (7)** — Phase 3 investigation: nadlan.gov.il Terms of Use forbid automated
  collection and API use without permission, so the plan changed (owner chose two tracks).
  Documented in `docs/sources/nadlan.md`, drafted a permission letter and an FOI request,
  added the CBS index fetcher with tests. Next: CBS average prices by city, then the
  website on CBS data; load data once `DATABASE_URL` is in the environment.
- **2026-10-30 (8)** — Owner added the `DATABASE_URL` secret. Merged PR #1 (Phases 1–2 code,
  update workflow) and PR #2 (hide URL fragments in DB errors, after a password fragment
  leaked to a public log; log deleted, password reset). The workflow loaded localities,
  aliases and CBS indices. Next: CBS average prices by city, then the website on CBS data.
