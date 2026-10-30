# nadlan.gov.il (Government Real Estate Site)

_Investigated: 2026-10-30_

## Summary

**Not usable for automated collection without written permission.** The Terms of Use
forbid scraping and API use without explicit permission, and the deals API is protected
by reCAPTCHA Enterprise. No code in this project fetches from nadlan.gov.il.

## Terms of Use (section "איסורים ומגבלות")

The site's Terms of Use (footer link "תנאי שימוש", text shipped in the site bundle) state,
among other things:

- Using the site for data mining / scraping, or any action meant to accumulate data taken
  from the site, is forbidden. Using the site for machine learning is forbidden.
- Automated scraping, including with software or scripts, is forbidden. This includes bots,
  extracting data from the HTML, and **using APIs without explicit permission**.
- "Deep scraping" (automated navigation across many pages) and "dynamic scraping" that tries
  to bypass the site's protection mechanisms are forbidden.
- Downloads are allowed for personal, non-commercial use only; no large or repeated downloads.
- The information is owned by the site operator ("המרכז", Survey of Israel / מפ"י) and other
  bodies. Any commercial use, or use that is not personal or private, requires the
  operator's prior written approval.

`robots.txt` allows all paths with `Crawl-delay: 5`, but the Terms of Use are the binding
document and they are stricter.

## Technical notes

- The site is a Vue SPA. Runtime config is `https://www.nadlan.gov.il/config.json`.
- Deals are served by `POST https://api.nadlan.gov.il/deal-data`. Each request carries a
  reCAPTCHA Enterprise token and signed tokens, and the response is base64 gzip JSON.
  Anonymous users get a limited number of deals (`statusCode: 403` → "deals limited").
- The site also reads static JSON from `https://data.nadlan.gov.il/api/...` (per-settlement
  trend pages and deal lists). The Terms of Use apply to these files as well.
- `api.nadlan.gov.il` and `data.nadlan.gov.il` are not in the environment's allowed
  domains, and were deliberately not added.

## Possible legitimate routes

1. Ask the operator (Survey of Israel / Israel Tax Authority) for written permission or an
   official data feed for a public, non-commercial project.
2. A Freedom of Information request (חוק חופש המידע) to the Israel Tax Authority for bulk
   deal records.
3. Use official aggregated statistics instead (CBS average dwelling prices by city and
   housing price index).
