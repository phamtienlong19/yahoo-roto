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
`league`, `leagueName`, `champion` (team id or null), `asOf`, `inProgressWeek`, `categories`, `teams`, `weeks`, `views` (`season`, `seasonFinal` when a week is in progress, `w1`...`wN`), `composites` and `compositesFinal` (the season boards), `odds` (playoff odds, or null), `corrections`, `skipped`. Each week view's teams also carry `raw` (made/attempts of the percentage categories), which lets the page re-add any range of weeks (`RotoPure.range`); older reports without it keep only the two fixed ranges. The page ignores fields it does not know and refuses a `schemaVersion` newer than it was written for. `status.json` (data branch root) holds per league `lastOk`, `fails`, `since`, `error`; the page reads it only when a report looks old.

## Page addresses
`?week=3&view=allplay` (views `roto`, `stats`, `allplay`, `matchups`) opens a week; `?season=1&board=<tab>&lens=<view>` opens a season table (tabs `standings`, `allplay`, `luck`, `outlook`, `performance`), with `&basis=cats`, `&cat=PTS`, `&range=3-7`, `&win=5`, `&sort=2.desc` and `&me=<teamId>` where they apply. Older links (`board=roto`, `board=real`, `board=catluck`, `lens=expected`, ...) are mapped to their new tab and view by the alias table in `index.html`. Static mode (`&static=1`) is the layout the PNGs are drawn from, 1680 px wide (2600 px for the matrix); a table wider than the picture shrinks until it fits.

## The live feed
`roto-live.yml` loops about 115 minutes per run, queues its own successor (the cron is only a backstop), and force-pushes `<id>/report.json` and `status.json` to the orphan `data` branch. `cadence.py` sets the pace: about every 3 minutes while Yahoo's totals change, slower the longer nothing moves, hourly in the offseason, never slower than 10 minutes in US game hours. `restart-live.yml` cancels the live runs and starts a new one when the report code changes on `main`. After 5 failed passes in a row one issue is opened. A pass makes about 12 requests per league, 1.5 s apart.

## Playoff odds
Everything is read from the league's own pages: the settings page gives the playoff size and first playoff week, the standings page the divisions, and a future week's matchup page its pairing. Yahoo has no page listing a whole week, so the remaining schedule is read one matchup page at a time and kept in `<league>-schedule.json` (re-read about daily, two weeks a pass). `simulate()` plays the rest of the regular season 50,000 times from each team's shrunk weekly category averages, category by category, and the answer is cached in `<league>-odds.json` until its inputs change. The report carries `odds.sims`, `odds.complete`, `odds.margin`, `odds.history` (the odds after each finished week) and `odds.schedule` (who plays whom in the weeks still to come, which the page uses for the rest-of-season strength of schedule).

## Principles
- Standard library only for the tool; no build step for the page.
- Read-only against Yahoo, one request per 1.5 s, public leagues only.
- Everything shown is derived from the weekly pages and is display-only, not a Yahoo number.
