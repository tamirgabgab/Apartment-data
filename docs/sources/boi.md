# Bank of Israel interest rates

_Investigated: 2026-10-31_

## Access

The Bank of Israel statistics are published through an official public SDMX 2.1 / 3.0 API at
`https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/`. It needs no key. The fetcher asks for
CSV (`?format=csv&startperiod=2010-01`), makes two requests a month, and keeps the raw
responses gzipped under `data/raw/boi/`. The site's terms page (`/website_terms/`) is
rendered in the browser and could not be read from the session; the site credits the Bank of
Israel as the source of the rates.

Useful endpoints:

- Dataflow list: `structure/dataflow/BOI.STATISTICS` (XML).
- Code lists of a dataflow: `structure/dataflow/BOI.STATISTICS/{ID}/1.0?references=descendants`
  (about 13 MB).
- Data: `data/dataflow/BOI.STATISTICS/{ID}/1.0/{SERIES_CODE}?format=csv`.

## Series used

Dataflow `BIR_MRTG_99` ("ריביות וביצועים לדיור"), monthly from 2011-07, reporting entity
99034 (whole banking system including syndications), new loans (`BIR_COVERAGE=N`), housing
loans (`BS_ITEM=A2C`), all LTV / payment-to-income / property-value groups:

| Our code | BOI series | Meaning |
|---|---|---|
| `mortgage_fixed_unindexed` | `BNK_99034_LR_BIR_MRTG_467` | Not indexed, fixed rate |
| `mortgage_fixed_cpi` | `BNK_99034_LR_BIR_MRTG_1492` | CPI-indexed, fixed rate |
| `mortgage_variable_cpi` | `..._1489` + `..._1488` | CPI-indexed, variable: benchmark + margin |

Dataflow `BR`, series `MNT_RIB_BOI_D`: the policy rate, daily. Stored as `boi_rate`, the rate
on the last published day of each month, and `prime` = policy rate + 1.5.

## Gaps

- The **prime track** (not indexed, variable), the largest track by volume, has no published
  average rate for all loans (only for bullet / balloon loans). The site uses the prime rate
  itself instead and says so. Banks usually lend on this track at prime plus or minus a margin.
- No overall weighted average rate is published in this dataflow.
- The same dataflow also has volumes (`DATA_TYPE=B`), number of loans (`N`), average term
  (`T`) and payment-to-income (`PTI`), not used yet.
