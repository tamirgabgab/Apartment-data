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
  - Migration `index_tweaks` (`supabase/migrations/20261030000100_index_tweaks.sql`)
    is **not applied yet**: the Supabase server asked for a confirmation (it contains a
    `drop index`) and it timed out. Apply it in the next session.
- **Vercel:** project not created yet. The Vercel MCP connection lacks access to the
  `tamirgabgab` scope (team id `team_ZhDyYoJQ7ch1tCHoRn41zIrH`, Hobby plan); the owner
  needs to approve a consent link (`authorize_team_access`), then create the project
  with `create_git_project` (repo `tamirgabgab/Apartment-data`, root directory `web`).
  Production deploys from `main`, so the public link exists only after merging to `main`.
- **Network:** the session network still blocks `www.nadlan.gov.il`, `api.cbs.gov.il`,
  `data.gov.il`, `www.cbs.gov.il`, `www.yad2.co.il`, `www.madlan.co.il` (proxy 403 on
  CONNECT). The owner chose to add them under Allowed domains
  (https://code.claude.com/docs/en/cloud-environments#network-access); a new session
  may be needed for the change to take effect. GitHub Actions is not affected.
- **Secrets still needed** (GitHub repository secrets): `DATABASE_URL` (Supabase
  session pooler connection string) for the scheduled jobs.

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
- [ ] Allow the source hosts in the environment network settings (section 3).
- [x] Python project skeleton: `pyproject.toml`, `ruff`, `pytest`, `.gitignore`, src layout.
- [x] CI workflow (lint + tests).
- [x] Create the Supabase project and apply the initial schema.
- [ ] Apply the `index_tweaks` migration.
- [ ] Create the Vercel project (after the owner approves Vercel access).
- [ ] Add `DATABASE_URL` as a GitHub repository secret.
- [ ] Merge to `main`, get the production URL, put it in `README.md`.

### Phase 1 — Reference data
- [ ] Ingest the CBS localities file into `localities`, mark `is_city`.
- [ ] Build `locality_aliases`.

### Phase 2 — CBS series
- [ ] Housing price index (national + districts) and CPI into `official_indices`.
- [ ] CBS average prices by city for validation.

### Phase 3 — Transactions (nadlan.gov.il)
- [ ] Investigate the current API, document it in `docs/sources/nadlan.md`.
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

All Phase 0 questions are answered (see section 2). New questions go here.

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
