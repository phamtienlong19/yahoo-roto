# How it fits together

```
Yahoo public pages ──► yahoo_roto.py ──► report.json ──► index.html (the page)
 (settings, standings,   fetch + parse     one file per      draws every board in the
  one matchup page        + roto math       league            browser; saves images
  per team per week)
```

## Files
| File | What it does |
| --- | --- |
| `yahoo_roto.py` | The tool. `Fetcher` (polite GETs, retries, small on-disk copy of slow pages), the HTML parsers, roto / all-play / luck math, `report()` (everything the page shows), the weekly cache and stat-correction tracking, the CLI, and the headless-Chrome image export. |
| `index.html` | The page: one file, no build step, no dependencies. Reads `report.json` (inlined in `--report` output, fetched by the hosted site). Static mode (`?static=1`) is the layout the PNGs are drawn from. |
| `pages.py` | Writes `<league id>/index.html` copies (own title and link preview). A test fails when they are stale: run `python3 pages.py`. |
| `cadence.py` | How long the live workflow sleeps (fast while totals change, slow when nothing moves), and its failure counting: status file and one-issue-per-outage alerts. |
| `canary.py` | Daily end-to-end health check against real Yahoo (used by `canary.yml`). |
| `leagues.json` | League ids, display names, and defending champions. |
| `.github/workflows/roto-live.yml` | Keeps `<id>/report.json`, `status.json` and the weekly cache fresh on the orphan `data` branch. |
| `.github/workflows/test.yml`, `canary.yml` | Tests (Python 3.10 and 3.12, lint, headless-Chrome page tests, workflow lint) and the daily canary. |

## The weekly cache and corrections
A finished week (a later week already has stats) is stored once in `<cache>/<league>-week-N.json` and re-read at 1 h, 6 h, 24 h and 48 h to catch stat corrections; a changed total replaces the stored week and is kept 14 days in `<league>-corrections.json`. Cache files are written atomically and a damaged one counts as a miss. Settings, standings and the week list are copied to disk for a few hours (`TTL`).

## Report format (`report.json`, `schemaVersion` 3)
`league`, `leagueName`, `champion` (team id or null), `asOf`, `inProgressWeek`, `categories`, `teams`, `weeks`, `views` (`season`, `seasonFinal` when a week is in progress, `w1`...`wN`), `composites` and `compositesFinal` (the season boards), `corrections`, `skipped`. The page ignores fields it does not know and refuses a `schemaVersion` newer than it was written for. `status.json` (data branch root) holds per league `lastOk`, `fails`, `since`, `error`; the page reads it only when a report looks old.

## Principles
- Standard library only for the tool; no build step for the page.
- Read-only against Yahoo, one request per 1.5 s, public leagues only.
- Everything shown is derived from the weekly pages and is display-only, not a Yahoo number.
