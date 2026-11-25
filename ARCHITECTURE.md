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
| `data_guard.py` | Safe publishing of the `data` branch: restore with a manifest check, policies for what may never be lost (finished weeks, reports, append-only hash chains), a compare-and-swap push (`--force-with-lease`), and the "Roto publish blocked" alert. |
| `canary.py` | Daily end-to-end health check against real Yahoo (used by `canary.yml`). |
| `leagues.json` | League ids, display names, defending champions, and `cups` (origin league and finish per team, playoff places; `report.json` gets a `cup` key only for those leagues, and the page shows origin chips, a playoff band and a cup header). |
| `.github/workflows/roto-live.yml` | Keeps `<id>/report.json`, `status.json` and the weekly cache fresh on the orphan `data` branch. |
| `.github/workflows/test.yml`, `canary.yml` | Tests (Python 3.10 and 3.12, lint, headless-Chrome page tests, workflow lint) and the daily canary. |

## The weekly cache and corrections
Yahoo's own calendar decides what is live: the default matchup page shows the current week, and when it is a later week than the newest one with stats, that newest week is over (`inProgressWeek` is null and the report has no `seasonFinal`). Without the calendar, a week is final once a later week has stats. A finished week is stored once in `<cache>/<league>-week-N.json`. Yahoo's Stat Corrections page for the week (`/statcorrections?week=N`) gives the day corrections are applied and how many rows are pending or "received too late"; the week is read again every 3 hours until that day, once more after it, then left alone (`report.settling` feeds the page's note). When the page cannot be read, the older schedule applies (1 h, 6 h, 24 h, 48 h). A changed total replaces the stored week and is kept 14 days in `<league>-corrections.json`. Cache files are written atomically and a damaged one counts as a miss. Settings, standings and the week list are copied to disk for a few hours (`TTL`).

## Report format (`report.json`, `schemaVersion` 3)
`league`, `leagueName`, `champion` (team id or null), `asOf`, `inProgressWeek`, `categories`, `teams`, `weeks`, `views` (`season`, `seasonFinal` when a week is in progress, `w1`...`wN`), `composites` and `compositesFinal` (the season boards), `odds` (playoff odds, or null), `corrections`, `skipped`. Each week view's teams also carry `raw` (made/attempts of the percentage categories), which lets the page re-add any range of weeks (`RotoPure.range`); older reports without it keep only the two fixed ranges. The page ignores fields it does not know and refuses a `schemaVersion` newer than it was written for. `status.json` (data branch root) holds per league `lastOk`, `fails`, `since`, `error`; the page reads it only when a report looks old.

## Standings, and what is still to come
Live standings and rest-of-season strength of schedule count the records through one week X: the week being played (default) or, with `thru=final`, the last finished one. What is "still to come" always starts at X+1 (`weeksAfter`). On the final view `RotoPure.yahooCheck` compares the records with `report.yahooStandings` (Yahoo's own standings table, which counts finished weeks only, read from the page already fetched and cached 6 h).

## Page addresses
`?week=3&view=allplay` (views `roto`, `stats`, `allplay`, `matchups`) opens a week; `?season=1&board=<tab>&lens=<view>` opens a season table (tabs `standings`, `allplay`, `luck`, `outlook`, `performance`), with `&basis=cats` (the default) or `&basis=matchups`, `&thru=final`, `&cat=PTS`, `&range=3-7`, `&win=5`, `&sort=2.desc` and `&me=<teamId>` where they apply. Older links (`board=roto`, `board=real`, `board=catluck`, `lens=expected`, ...) are mapped to their new tab and view by the alias table in `index.html`. Static mode (`&static=1`) is the layout the PNGs are drawn from, 1680 px wide (2600 px for the matrix); a table wider than the picture shrinks until it fits.

## The live feed
`roto-live.yml` loops about 115 minutes per run, queues its own successor (the cron is only a backstop), and publishes `<id>/report.json` and `status.json` to the orphan `data` branch through `data_guard.py`: it restores the branch and verifies it first, refuses a publish that would lose protected history (reports go stale instead, with an issue, an error annotation and a red run), and pushes with a lease so a branch that moved meanwhile is never overwritten. A corrupt protected file is repaired by hand: run the workflow with `quarantine=_cache/<file>`, which keeps its bytes under `_quarantine/` and starts the file afresh. `cadence.py` sets the pace: about every 3 minutes while Yahoo's totals change, slower the longer nothing moves, hourly in the offseason, never slower than 10 minutes in US game hours. `restart-live.yml` cancels the live runs and starts a new one when the report code changes on `main`. After 5 failed passes in a row one issue is opened. A pass makes about 12 requests per league, 1.5 s apart.

## Playoff odds
Everything is read from the league's own pages: the settings page gives the playoff size and first playoff week, the standings page the divisions, and a future week's matchup page its pairing. Yahoo has no page listing a whole week, so the remaining schedule is read one matchup page at a time and kept in `<league>-schedule.json` (re-read about daily, two weeks a pass). `strengths()` estimates each team's weekly category strength with data-driven shrinkage and a standard error, and `simulate()` plays the rest of the regular season 50,000 times in groups, each group drawing every team's true strength afresh from that uncertainty, category by category, and the answer is cached in `<league>-odds.json` until its inputs change. `backtest()` forecasts each finished week from the weeks before it (`odds.accuracy`: favourite-won rate, Brier score, calibration bins, spread check) and `choose_half_life()` uses recency weighting only if it forecasts better (from 10 finished weeks; each history week chooses from its own past) (`odds.model`). The report carries `odds.sims`, `odds.complete`, `odds.margin`, `odds.history` (the odds after each finished week) and `odds.schedule` (who plays whom in the weeks still to come, which the page uses for the rest-of-season strength of schedule).

## Principles
- Standard library only for the tool; no build step for the page.
- Read-only against Yahoo, one request per 1.5 s, public leagues only.
- Everything shown is derived from the weekly pages and is display-only, not a Yahoo number.
