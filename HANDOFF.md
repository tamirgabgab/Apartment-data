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
| Scope | Cities only for now (exact definition still open, see section 9) |
| History | As far back as possible, target from 2000 onward |
| Output | Interactive web UI (HTML), public link in `README.md` |
| Storage / hosting | Supabase (Postgres) for data, Vercel for the website |
| Price type | Executed transactions only. Asking prices of active listings are **out of scope** |
| Yad2 / Madlan | Allowed, but only their executed-deal data, not listings |

## 3. Current state

- Repository contains `README.md`, `CLAUDE.md` and this file. No code yet.
- **The cloud dev environment cannot reach the data sources**: the network policy
  blocks `www.nadlan.gov.il`, `api.cbs.gov.il`, `data.gov.il`, `www.yad2.co.il` and
  `www.madlan.co.il` (proxy returns 403 on CONNECT). To develop and test fetchers in
  a session, those hosts must be added under Allowed domains in the environment's
  network settings (https://code.claude.com/docs/en/cloud-environments#network-access).
  Scheduled ingestion in GitHub Actions is not affected by this.

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
- [ ] Answer the remaining open questions (section 9).
- [ ] Allow the source hosts in the environment network settings (section 3).
- [ ] Python project skeleton: `pyproject.toml`, `ruff`, `pytest`, `.gitignore`, src layout.
- [ ] Create / connect the Supabase project and the Vercel project.

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

1. **City definition:** CBS municipal status "עירייה" (about 80 cities), or a
   population threshold (for example 20,000+ residents)?
2. **Network access:** can the source hosts be added to the environment's Allowed
   domains, so fetchers can be developed and tested inside the session?
3. **Supabase / Vercel accounts:** use an existing Supabase project and Vercel team,
   or create new ones dedicated to this project?
4. **Website stack:** plain HTML + charts (simplest), or Next.js (more room to grow)?
5. **Update frequency:** weekly, or monthly is enough?
6. **Public site:** the link in the README will be public. Is that OK? (All data
   comes from public government sources.)

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
