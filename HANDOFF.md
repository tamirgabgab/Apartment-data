# HANDOFF

Living document that carries project context between work sessions.
Read it at the start of every session and update it at the end.

_Last updated: 2026-10-30_

---

## 1. Project goal

Collect Israeli housing price data from multiple sources (Tax Authority deals via
nadlan.gov.il, CBS / LAMAS, Yad2, Madlan and others) and **track apartment prices
over time, broken down by settlement (locality)**.

The primary signal is **executed transactions** (actual sale prices reported to the
Tax Authority). Listing prices (asking prices) are a secondary, optional signal.

## 2. Current state

- Repository contains only `README.md`, `CLAUDE.md` and this file.
- No code, data, dependencies or CI yet.
- No technology decisions have been locked in yet (see "Open questions").

---

## 3. Data sources (recommendations)

| Source | What it gives | Type | Granularity | Access | Priority |
|---|---|---|---|---|---|
| **nadlan.gov.il** (Tax Authority real-estate deals) | Every reported sale: date, price, address / gush-helka, rooms, area, floor, build year, deal type | Transactions | Single deal, daily | Public website backed by a JSON API (unofficial, undocumented, changes from time to time) | **Core** |
| **CBS / LAMAS – Housing Price Index** (מדד מחירי הדירות) | Official quality-adjusted index, national and by district | Index | Monthly / bi-monthly, district level | Official CBS price-index API + Excel tables | High (baseline / sanity check) |
| **CBS – Average dwelling prices by city** | Average transaction price by city and number of rooms | Aggregates | Quarterly, ~large cities only | Excel tables in CBS publications | High |
| **CBS – Localities file** (קובץ יישובים) | Official locality codes (סמל יישוב), names in Hebrew/English, district, sub-district | Reference | Per locality | data.gov.il (CKAN API) / CBS site | **Required first** |
| **data.gov.il** | Other government datasets (e.g. Dira BeHanacha lotteries, construction starts) | Mixed | Varies | CKAN API, open license | Medium |
| **Bank of Israel** | Mortgage rates and volumes | Context | Monthly | Official series API | Low (context for analysis) |
| **Yad2** | Asking prices of active listings | Listings | Single listing | No public API; scraping is restricted by ToS and anti-bot protection | Optional, legal check first |
| **Madlan** | Asking prices + their own aggregated deal data | Listings / aggregates | Single listing / neighborhood | No public API; ToS restricts scraping | Optional, legal check first |

Notes:
- **Endpoints must be verified at implementation time.** nadlan.gov.il in particular
  has been redesigned more than once; do not trust hard-coded URLs from old blog posts
  or GitHub projects without testing them.
- Prefer official/open sources. For Yad2/Madlan read the Terms of Use first; consider
  contacting them for a data partnership instead of scraping.
- Respect rate limits: throttle requests, cache raw responses, never hammer a site.

---

## 4. Recommended architecture (start simple)

```
sources ──► ingest (per-source fetchers) ──► raw store (immutable, dated)
                                                   │
                                                   ▼
                                       normalize + clean + geocode
                                                   │
                                                   ▼
                                    curated tables (deals, localities)
                                                   │
                                                   ▼
                                  aggregations / price indices per locality
                                                   │
                                                   ▼
                                       dashboard / reports / exports
```

Suggested stack for the MVP (to be confirmed, see "Open questions"):

- **Language:** Python 3.12, `httpx` for HTTP, `pandas` or `polars` for processing,
  `pydantic` for schemas.
- **Storage:** DuckDB / Parquet locally for the MVP; move to Postgres (e.g. Supabase)
  when a web app or multiple users need it.
- **Scheduling:** GitHub Actions cron (free, versioned) for weekly / monthly updates.
- **Visualization:** Streamlit for a quick internal dashboard; Next.js + Vercel later
  if a public site is needed.
- **Quality:** `pytest`, `ruff`, type hints; data validation tests on every ingest.

Proposed repository layout:

```
src/apartment_data/
    sources/          # one module per source: nadlan.py, cbs.py, yad2.py ...
    reference/        # localities, address / gush-helka mapping
    transform/        # cleaning, normalization, deduplication
    analytics/        # medians, rolling windows, price indices
    storage/          # DuckDB / Postgres access layer
data/
    raw/              # raw API responses, partitioned by source and fetch date (gitignored)
    curated/          # cleaned tables (gitignored or published as release assets)
notebooks/            # exploration only
tests/
.github/workflows/    # scheduled ingestion jobs
```

### Core data model (draft)

- `localities` — `locality_code` (CBS code, PK), `name_he`, `name_en`, `district`,
  `sub_district`, `population`.
- `deals` — `deal_id` (source key or hash), `source`, `deal_date`, `price_ils`,
  `locality_code`, `street`, `house_number`, `gush`, `helka`, `sub_helka`, `rooms`,
  `area_sqm`, `floor`, `build_year`, `property_type`, `deal_nature`,
  `fraction_sold`, `is_new_construction`, `fetched_at`.
- `listings` (optional) — same idea for asking prices, plus `first_seen`, `last_seen`.
- `locality_price_stats` — `locality_code`, `period` (month / quarter), `n_deals`,
  `median_price`, `median_price_per_sqm`, `p25`, `p75`, `index_value`.
- `official_indices` — CBS index series stored as-is for comparison.

---

## 5. Methodology for tracking prices per locality

Raw averages are misleading because the mix of sold apartments changes every period
(more new apartments one quarter, more small ones the next). Recommended approach,
from simplest to most robust:

1. **Median price per sqm** per locality per quarter, plus the number of deals.
   Simple, robust to outliers, easy to explain. Good MVP metric.
2. **Segmentation** by rooms (2–3, 4, 5+) and new vs. second-hand, so mix shifts are
   visible instead of hidden.
3. **Rolling windows / pooling for small localities**: a 3–4 quarter rolling median,
   or pool small settlements into their sub-district, and mark results with too few
   deals (e.g. `n_deals < 20`) as unreliable.
4. **Quality-adjusted index** (later): a hedonic regression
   (`log(price) ~ area + rooms + floor + age + locality + period`) or a repeat-sales
   index (same apartment sold twice). Validate it against the CBS index at district
   level.
5. **Nominal vs. real prices**: also show prices deflated by CPI (CBS) so inflation
   is separated from real appreciation.

Cleaning rules to apply on transaction data:

- Drop / flag deals where only a **fraction** of the property was sold
  (`fraction_sold < 1`), or normalize price by the fraction.
- Drop non-market deals (family transfers, extreme low prices, zero price).
- Remove outliers per locality and period (e.g. outside the 1st–99th percentile of
  price per sqm, or IQR rule).
- Deduplicate deals that appear more than once (same gush-helka-sub-helka, date, price).
- Keep only residential property types (apartment, garden apartment, penthouse,
  cottage...) and analyze them separately.
- Map every deal to a CBS `locality_code` — names are inconsistent across sources
  (spelling variants, "תל אביב -יפו" vs. "תל אביב יפו").

---

## 6. Roadmap — step by step

### Phase 0 — Decisions and setup
- [ ] Answer the open questions below (stack, storage, scope).
- [ ] Python project skeleton: `pyproject.toml`, `ruff`, `pytest`, `.gitignore`, src layout.

### Phase 1 — Reference data
- [ ] Ingest the CBS localities file into `localities`.
- [ ] Build a name-normalization / alias table for locality names.

### Phase 2 — Official baseline (CBS)
- [ ] Fetch the CBS Housing Price Index series (national + districts).
- [ ] Fetch CBS average dwelling prices by city (quarterly tables).
- [ ] Store them in `official_indices`; this gives a working time series quickly.

### Phase 3 — Transactions (nadlan.gov.il) — the core
- [ ] Investigate the current site / API (browser dev tools), document endpoints and
      fields in `docs/sources/nadlan.md`.
- [ ] Write a fetcher per locality and date range, with throttling, retries and raw caching.
- [ ] Pilot on 3–5 localities, then backfill history (several years) for all localities.
- [ ] Incremental updates: fetch only recent months, upsert by `deal_id`.

### Phase 4 — Cleaning and normalization
- [ ] Implement the cleaning rules from section 5.
- [ ] Data validation tests (schema, ranges, null rates, duplicate checks).

### Phase 5 — Analytics
- [ ] Median price and price per sqm per locality per quarter, by segment.
- [ ] Rolling windows and reliability flags for small localities.
- [ ] Compare district aggregates against the CBS index.
- [ ] Later: hedonic / repeat-sales index, CPI-deflated prices.

### Phase 6 — Automation
- [ ] GitHub Actions cron: weekly transactions update, monthly CBS update.
- [ ] Alerts when a source fails or returns an unexpected schema.

### Phase 7 — Visualization
- [ ] Streamlit dashboard: pick a locality, see price trend, deal count, segments,
      comparison with other localities and with the CBS index.

### Phase 8 — Listings (optional)
- [ ] Legal / ToS review for Yad2 and Madlan.
- [ ] If allowed: collect asking prices and compare asking vs. executed prices
      (negotiation gap, time on market).

---

## 7. Open questions (for the project owner)

1. **Scope:** all localities in Israel, or a shortlist to start with?
2. **History:** how far back (e.g. from 2015, from 2020)?
3. **Output:** personal analysis / dashboard, or a public website?
4. **Storage:** local DuckDB files for now, or Supabase (Postgres) from day one?
5. **Listings:** are Yad2 / Madlan asking prices needed, given the ToS restrictions?
6. **Granularity:** is locality level enough, or also neighborhoods / streets later?

## 8. Risks

- Unofficial APIs (nadlan.gov.il) can change without notice — isolate each source in
  its own module and keep raw responses so data can be re-parsed.
- Transaction reports arrive with a delay of weeks to months; the latest period is
  always incomplete and should be marked as provisional.
- Small localities have too few deals for a stable monthly number.
- Legal exposure when scraping commercial sites.

## 9. Session log

- **2026-10-30** — Repository reviewed (empty). Wrote this handoff with source
  recommendations, architecture, methodology and roadmap. Added project `CLAUDE.md`.
  Next: answer open questions, then Phase 0.
