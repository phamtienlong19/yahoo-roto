# yahoo-roto: the complete handoff

Everything a new chat needs to understand this project deeply: what it is, why it looks and behaves the way it does, how every part works, how it is tested and shipped, what the owner cares about, what is unfinished, and the traps to avoid. Written from a full read of every file, every commit, every workflow and the planning documents. Facts here were checked against the code at the time of writing (16 Nov 2026, updated the same evening after PR #41); when this document and the code disagree, the code wins, and please fix the document.

Contents: 1 What it is · 2 Working with the owner · 3 Repo map · 4 Data flow · 5 Reading Yahoo · 6 The cache, corrections and "current week" · 7 The report (`report.json`) · 8 The statistics · 9 Playoff odds · 10 The page · 11 Image export · 12 The live feed and CI/CD · 13 Tests · 14 Design principles, with the history behind them · 15 Timeline · 16 State of play, backlog, open choices · 17 Gotchas · 18 Glossary

---

## 1. What it is

**yahoo-roto** turns any **public, head-to-head, category** Yahoo fantasy league (built and verified on NBA) into a web page of roto standings, luck metrics, strength of schedule and Monte Carlo playoff odds. It reads Yahoo's public pages only (never signs in), uses only the Python standard library, and ships a single-file, dependency-free web page. Nothing it shows is a Yahoo number: everything is derived and display-only.

Origin: it began as `tools/yahoo-roto/` inside the owner's `nba-talk-vn-dynasty` repo (PR #170 there) and was spawned into this standalone repo (`phamtienlong19/yahoo-roto`, public) by a planning session whose prompt is saved in `~/.claude/plans/giggly-hugging-cookie.md`. The audience is the members of the owner's Vietnamese NBA fantasy community ("NBA Talk VN"). People in the leagues read the tables on phones, share them as images in group chats, and argue about luck: the owner reports the Luck table is "earning rave reviews" and that people already quote the playoff odds. That social use drives most design decisions below (phone first, shareable images, no insulting labels, plain English).

**Live leagues** (`leagues.json`):

| id | name | notes |
| --- | --- | --- |
| 85092 | NBA Talk VN - Dynasty | defending champion "m jordat" (Yahoo name "M. Jordat \| The Silver Seekers"), 18 teams |
| 207464 | NBA Talk VN - Serie A | champion "sup fam"; has divisions |
| 212003 | Super Cup 26-27 | champion "master chef" |
| 49486 | NBA Champions League 23rd 2026 | added 16 Nov 2026; 16 teams, 9 categories, 6 playoff teams, division winners |

Site: GitHub Pages from `main` `/`, per-league addresses `https://phamtienlong19.github.io/yahoo-roto/<id>/`. Data: orphan `data` branch, read via raw.githubusercontent.com.

## 2. Working with the owner (read this first)

The owner is Long Pham (GitHub `phamtienlong19`). They are product-minded and give short, sharp design feedback. Learned preferences, each with the incident that taught it:

- **They merge PRs themselves.** Never push to `main`. Target PRs at `main`, not at another feature branch. Work on a feature branch, open a PR, report the URL. Commit/PR attribution: commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. **Stacked PRs bite:** #37, #38, #39 were merged into their stacked base branches after #36 had already merged to `main`, so their changes never reached `main`; PR #40 re-carries them. When stacking, say plainly "merge in this order, retarget after" and check `git merge-base --is-ancestor <commit> origin/main` after merges. Also note: the owner's "pr 72 / pr 73" messages referred to CI **run** numbers, not PR numbers (the PRs were #35 and #36).
- **Plain stats, no verdict labels.** They rejected "Robbed"/"Stolen" ("rather just plain old stats to tell the stories"). Never label people; show numbers.
- **A table says one or two things.** "The reason why they have been effective so far is because they are communicating one or two things only at a time." Colour only the key columns; use group headers/dividers; prefer several tabs/views over one dense table.
- **One colour rule.** "Ranking scheme everywhere" (dark green best, dark red worst, white middle). Colour in a column means rank within that column and nothing else.
- **Percentages for rates, decimals for luck-type numbers.** All-play Win%, SOS, form are percentages; luck, expected wins, and box-score FG%/FT% stay decimals.
- **"Wk 4", never "W4"** ("can easily be misunderstood as winning 4 in a row").
- **Plain English, short.** Every note, tooltip, subtitle and README line is length-linted by tests. No formulas in copy; internals go in `ARCHITECTURE.md`.
- **Always mobile friendly and image-export safe.** Saved images must look right; tables wider than the image must shrink, not clip.
- **Small coloured squares beat numbers and lines.** A row of tiny squares, one per week or opponent, each shaded in the one green / white / red family, is the owner's favourite way to show "by week" data (the original Weekly Roto Points board). Replacing it with a grid of roto-point numbers drew an angry reply. **Always look at a rendered screenshot of any table you change** (headless Chrome `--screenshot`, light and dark, desktop and 390 px) before opening the PR; DOM-only tests missed this.
- **Sceptical of decorative charts.** They disliked small trend lines in tables ("the graph itself doesn't convey much info if you can't inspect it closely and there's little baseline comparison") and chose numbers-and-shades instead. Tiny sparklines were removed in PR #40 (originally #39); the replacement is the squares below.
- **Verify against reality.** They caught SOS totals of 108 vs 144 by hand, a "week 4 still in progress" after Yahoo had moved on, and recent form still being all-play. Check numbers with from-scratch computations and compare against Yahoo's own pages.
- **Plan mode and approvals:** substantial work was planned (plan file(s) under `~/.claude/plans/`) and approved before execution; the owner often answers questions via the question tool. Keep the final summary short and lead with what changed.
- **Privacy:** do not put the owner's email or personal details in requests to external services.

Environment gotchas for the agent: bash commands time out at 120 s (run the browser test suite with `run_in_background`); `sleep N` chains are blocked (use `until` loops); `sed -i` with BSD sed misbehaves on this machine (use the Edit tool or python); `timeout` is not installed on macOS.

## 3. Repo map

| Path | Role |
| --- | --- |
| `yahoo_roto.py` (~1500 lines) | The whole backend: fetcher, HTML parsers, roto/all-play math, composites, cache + corrections, current-week logic, playoff-odds engine, report builder, CLI, headless-Chrome image export |
| `index.html` (~1000 lines) | The page: one file, ES5-style JavaScript (`var`, `function`), CSS, no build step, no dependencies. Contains `<script id="pure">` (`RotoPure`, pure helpers also tested through node) and the app script |
| `<id>/index.html` | Generated per-league copies of `index.html` with their own `<title>`/og tags (`pages.py`); a test fails when stale (`python3 pages.py`) |
| `pages.py` | Writes those copies |
| `cadence.py` | Live-feed pacing, change fingerprints, failure counting, public `status.json`, one-issue-per-outage alert list |
| `canary.py` | Daily end-to-end health check against real Yahoo |
| `leagues.json` | league ids, display names, defending champions |
| `.github/workflows/` | `roto-live.yml` (the feed), `restart-live.yml`, `test.yml` (CI), `canary.yml`; `dependabot.yml` bumps Actions weekly |
| `tests/` | ~180 tests, no network: `golden.py` (generated 18-team league through the real pipeline), unit/integration/browser tests, `fixtures/week-01.json` |
| `reference/serie_a_week3.html` | The original "reference sheet" the page's look was modelled on |
| `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md` | User docs (README is lint-tested to stay short), internals, how to work on it |
| `.gitignore` | `__pycache__/`, `out/`, `.cache/` |

## 4. Data flow

```
Yahoo public pages ──► yahoo_roto.py ──► report.json ──► index.html draws it in the browser
 settings, standings,     fetch + parse    one file per      ▲ also: `--png` / in-page "Save image"
 one matchup page per     + math           league            │  renders the same page in static mode
 matchup per week,        │                                  │
 stat-corrections page    └─ on-disk cache (finished weeks, schedule, odds, history, corrections)

Live: GitHub Actions loops ~115 min per run → publishes <id>/report.json + status.json + _cache to the orphan `data` branch
Page (Pages site) fetches https://raw.githubusercontent.com/<owner>/<repo>/data/<id>/report.json every ~2 minutes.
```

Everything the page shows is computed in the backend report **or** re-derived in the browser from the report's per-week data (week ranges, SOS, form, split, category luck by week) by pure functions that are parity-tested against Python.

## 5. Reading Yahoo

Base: `https://basketball.fantasysports.yahoo.com/nba/<league>` (`SPORTS` also lists NFL/MLB hosts but only NBA is verified).

| Page | What is read |
| --- | --- |
| `/settings` | scoring type ("Head-to-Head - Categories"), category list, public flag, league name, playoff setup text "Playoffs: N teams - Week X, ..." (regular season ends week X-1), whether "Division winners advance" |
| `?lhst=stand` | teams (names + ids), divisions (h4 headings above team rows) |
| `/matchup?date=totals&week=W&mid1=<team>` | one page per **matchup** (two teams): each team's totals per category (made/attempted pairs for FG/FT as `FGM/A*` columns), and the last unnamed column = category "Score" so far. The week dropdown lists weeks; the `selected` option is the page's week |
| `/matchup?date=totals&mid1=<team>` (no week) | Yahoo's **current week** (the `selected` option) |
| `/statcorrections?week=N` | table `Tst-table`: rows of corrections; rows whose date cell has class `F-negative` were "received too late to apply to the scoring"; footer sentence "...are applied on Monday, Nov 16." |

`Fetcher`: one GET per 1.5 s (`--delay`), User-Agent `yahoo-roto/1.0 (read-only; public pages)`, 2 retries with 2 s/6 s backoff, honours `Retry-After` (capped 60 s), clear messages for 403/429/999, no retry on 403 or other 4xx, detects a redirect to login ("not publicly viewable"), optional on-disk copy of slow pages (`TTL`: settings 12 h, standings 6 h, week list 6 h). A parser fails soft: a missing or odd page usually returns less rather than crashing, which is why the **canary** exists.

Parsing uses a tiny hand-written element tree (`parse_tree`, class `El`) instead of a library (stdlib only). `parse_week` returns `{"week","weeks","pair","teams":{id:{"name","cols","score"}}}`; `_num` turns "-" into `None`; `_made_att` keeps "made/attempted". `plan(categories, headers)` decides per category how to compute it: counting stats from their column, percentages from summed makes and attempts (**never average percentages**); ratio categories (ERA, WHIP) are listed and skipped; `LOWER_IS_BETTER = {TO, PF, DQ, GA, GAA, ERA, WHIP, BB}`. Category names normally come from the settings page; league 49486's settings regex returned `[]`, and the fallback uses the matchup headers.

A week with no stats yet: the walk stops at the first empty week (the first page says so, so only ~12 requests per league per pass).

## 6. The cache, corrections and "current week"

### Cache (`--cache DIR`, in CI `cache/_cache`, carried on the `data` branch as `_cache/`)
- `<league>-week-N.json` (v3): a finished week's totals, matchups, plus meta `finalized`, `checks`, and (new) `applies`, `checked`, `pending`, `late`. Written atomically (`write_atomic`); a damaged file counts as a miss; v2 files predate re-checking and are never re-checked.
- `<league>-schedule.json`: future pairings (`{week: {"at", "pairs"}}`).
- `<league>-odds.json` (fingerprint + odds block), `<league>-odds-history.json` (per-week snapshots), `<league>-corrections.json` (kept 14 days).
- Page copies of settings/standings by URL hash.

### "Current week" (added Nov 2026, PR #38 content; the live bug that motivated it)
Old rule: the newest week with stats is "in progress"; a week is final only once a later week has stats. Problem: Yahoo moves to the next week on Monday, but the new week has no stats until games are played, so the tool called week 4 "in progress" for most of a day after it ended.
New rule (`load()`): read Yahoo's default matchup page → `current_week`. If it is later than the newest week with stats, that week is **settled** (over): `inProgressWeek` is `null`, no `seasonFinal` view, odds continue from the next week (`odds_block(..., live=False)`). If the calendar cannot be read, fall back to the old rule. `st["settled"]` also becomes true when the newest week is already in the cache.

### Stat corrections
Yahoo and the NBA fix box scores for days; Yahoo applies queued corrections on a stated Monday ("W1 Oct 26, W2 Nov 2, W3 Nov 9, W4 Nov 16, W5 Nov 23" in this league's calendar). Weeks 2-4 had roughly 75-85% "too late" rows (they never change the score). Behaviour now:
- When a week is first finalised (and `cache` is set) read `/statcorrections?week=N` → `{rows, late, pending, applies}` (`parse_stat_corrections`, best effort, year-boundary aware) and store in the cache meta.
- `recheck_due(meta, now)`: with a known apply day, re-read the week every `RECHECK_EVERY` = 3 h until `applies + SETTLE` (36 h), then once more and freeze (`checks = len(CHECK_AGES)`); without it, the old fixed schedule `CHECK_AGES = (1h, 6h, 24h, 48h)` after finalising.
- A changed total replaces the stored week, is turned into a **correction event** (`correction_event`: changed categories, teams whose weekly roto rank changed, matchups that flipped), kept 14 days, and shown on the page as a dismissible banner (`drawFixes`, tracked per league in `localStorage["roto.fix.<league>"]`; week strip marks weeks with a "stat correction").
- Report field `settling = {week, applies: "YYYY-MM-DD", pending, late}` for the closed week whose corrections are not yet applied (null after apply day + 24 h or when unknown). The page says "Wk 4 is complete; Yahoo may still correct box scores until Mon 16 Nov (4 pending, 22 arrived too late to count)" (`settleNote`).
Real check on league 49486: week 4 → 26 rows, 22 late, 4 pending, applies Mon 16 Nov.

## 7. The report (`report.json`, `SCHEMA_VERSION` 3, additive changes only)

`report()` returns (key fields):
- identity: `league`, `leagueName`, `sport`, `scoring`, `champion` (team id or null; resolved from `leagues.json` by name or id, punctuation/tagline tolerant, ambiguous = no crown), `asOf` (UTC string), `schemaVersion`, `schema` ("yahoo-roto-report/2").
- time: `inProgressWeek` (week number or **null** when Yahoo has turned the page), `currentWeek`, `settling`, `weeks` (weeks with stats), `corrections`.
- shape: `categories` `[{cat, lower, pct}]`, `skipped`, `teams` `{id: name}`.
- `views`: `season`, `seasonFinal` (only when a week is in progress and there are ≥2 weeks: the season without the live week), `w1..wN`. A view has per team `values`, `points`, `total`, `rank`, `allPlay`, `winPct`, `score`, a `matrix` (all-play margins), `order`/`allPlayOrder`, and (week views) `matchups` and **`raw`** (made/attempted for percentage categories — this is what lets the browser re-add any week range; older reports without `raw` only support fixed ranges).
- `composites` (and `compositesFinal`): `weekly[team][week]` = `{points{cat}, total, rank, allPlay[W,L,T], winPct, score, opp, result W/L/T, catRecord[W,L,T] vs the real opponent}`; `weeklyRoto`, `seasonRoto`, `seasonAllPlay`, `realRecord` (record, realWins, expectedWins, luck, catRecord, rank by category record), `catLuck` (real vs expected per category), `categoryKings`, `power`.
- `odds`: see §9.
`cadence.fingerprint` hashes the report minus `asOf` to decide whether "numbers moved". The page refuses a `schemaVersion` newer than it knows (`SCHEMA=3`) and ignores unknown fields.

## 8. The statistics (definitions, and why)

- **Roto points** (per category): best team gets N points, worst 1, ties share the average; lower-is-better for TO etc. Percentages come from summed makes/attempts. Season roto = ranking of the summed totals (not the sum of weekly points). Weekly roto points = sum of each week's roto totals (a separate board, "Weekly Roto Points").
- **All-play**: each week, every team vs every other: a game is won by taking more categories (ties: equal). One game per opponent per week. `winPct = (W + T/2)/games`. The matrix cell = category margin; season matrix = weekly margin average.
- **Expected wins** = sum of weekly all-play Win% (what the stats "earned" in matchups). **Luck** = real wins − expected wins (a tied matchup = half a win). **Category luck** = real category wins vs the all-play share per category; **Places vs expected** = expected rank − rank.
- **Real rank** uses the *category* W-L-T against actual opponents (what Yahoo's category standings use), because the 4-game matchup record leaves many-way ties (fix in commit 8c3e8dc).
- **Strength of schedule (SOS)** (current definition after the "108 vs 144" bug report): for each opponent a team faced, take that opponent's **full record over the same weeks (all of its games)**, add up; SOS = (W + T/2)/games of the combined record. Totals therefore equal 9·n² on a 9-category, n-week league (matches the NFL-style convention of not excluding the opponent's game against you). Two bases via the **Matchups | Categories** switch. **Rest-of-season SOS**: the same for opponents still to come, using their record through the latest week with results (the live week counts, shown "(live)"), from `odds.schedule`.
- **Power rank** = plain average of the ranks on season roto, weekly roto, season all-play and real record. No weights.
- **Through week X** (Nov 2026): Live standings (first view of the Standings tab, and where the Season tab opens) and rest-of-season SOS count records through X = the week being played (default) or the last finished one (`?thru=final`); opponents to come always start at X+1. Live standings show one record column (shaded by win share), games behind first place (`RotoPure.gamesBehind`, owner chose first place over Yahoo's per-division GB), this week's opponent and score, the next opponent, and tiers (bye / playoffs / consolation / no bracket / no keepers) from `report.tiers`; house rules live in `leagues.json` `tiers` (Serie A only: consolation to 12th, bottom 2 get no keepers). The table does not sort. On the final view it is checked against Yahoo's own table (`report.yahooStandings`, `RotoPure.yahooCheck`) and shows Yahoo's ranks; Yahoo's rank numbers follow Win%, not division leaders first.
- **Super Cup skin** (commissioner's rules, 25 Nov 2026): every element is set in Manrope (one CSS rule on `.cup` and the wrapper's siblings; a browser test walks all elements). Origin tags follow the league sheet; team 12 shows CL 2 (not PL 4), so three teams show PL; Champions League chips are black, the colour of the sheet's "C1 + Dynasty + SC" ranking row.
- **Categories first** (Nov 2026, owner's choice): every Matchups | Categories switch opens on Categories (`?basis=matchups` for the other), Trends opens on category luck, and the Matchup Log is ordered by category luck.
- **Category Kings**: season leader and best single week per category (TO excluded: `KINGS_SKIP`).
- **Recent form** (Performance): real record over the last 3/5/8 finished weeks (matchups: W-L-T; categories: categories won) vs the season, change in percentage points, plus a plain "Stats said" column = all-play Win% of the same window, plus week-by-week results. **Vs strong / weak**: record against the strong half and weak half; *who is strong* is measured from stats (all-play Win% over the weeks, then roto points, then id), the *record* is real; shows games played, leaves Win% uncoloured under 3 matchups (2 on categories). Old Boom/Bust labels were removed in favour of these. (History: form/split were all-play until PR #37.)
- Rates are shown as percentages; luck-type numbers, expected wins and box-score FG%/FT% stay decimals.

## 9. Playoff odds (Outlook > Playoff odds)

**Inputs, all from the league's own pages:** playoff size and first playoff week (settings), divisions (standings headings), future pairings (a future week's matchup page shows its pairing; there is no page listing a whole week so it is one page per matchup, `fetch_schedule`: all unknown weeks read in the first pass, `SCHEDULE_PAGES_PER_PASS` = 400 cap; known weeks refreshed after 24 h, 2 weeks per pass; failures only mean fewer weeks, and the page says when the schedule is incomplete). Unknown pairings are drawn at random.

**Model (`strengths`, `simulate`, `cat_win_distribution`):**
1. Per category, each team's weekly strength = its average over finished weeks, **shrunk toward the league mean by empirical Bayes**: the real spread between teams is estimated from the between-team variance minus noise (floor 10% of the observed spread so a small sample cannot declare every team identical; with a single finished week assume a quarter is real). Each team also gets a standard error (`se`). `half_life` (optional) weights recent weeks by `0.5 ** (age/half_life)`.
2. A matchup is played **category by category**: for each category the probability team a beats b is the normal-difference chance Φ(z) with variance 2·sd²; the nine categories combine exactly into P(a wins exactly k) (a Poisson-binomial). Category independence is an assumption; the accuracy check measures whether real scores swing more.
3. `simulate`: plays the rest of the regular season `SIMS` = 50,000 times **in 2,000 groups** (`STRENGTH_DRAWS`); each group first **draws every team's true strength from its posterior** (stratified normal draws) and keeps it for all remaining weeks so a truly good/bad team stays so (the "hot" effect, as in Basketball-Reference/538-style models). Standing = total category points (won 1, level 0.5), ties broken at random; division winners advance first when the league says so, then best remaining by overall standing. Output per team: playoff chance, first-place chance, expected rank, full finishing distribution; `margin` = 95% simulation noise in points measured across 10 batches (~±1.65 early, ~0.4 with full strengths).
4. **Cache:** the answer is stored by a fingerprint (version, live flag, sims, hl, spots, points so far, schedule, division map, strengths); an unchanged input reuses the saved result.
5. **History** (`odds_history`): the odds after each finished week (8,000 sims, each week simulated once and remembered), which the page uses for "Since Wk N" and the movers strip.
6. **Backtest / accuracy** (`backtest`): walk-forward — each finished week from the second on is forecast from earlier weeks only; reports games, favourite-won rate, Brier score vs the 0.25 coin flip, calibration bins (50-60/60-70/70+ %), and `spreadRatio` (observed vs modelled category-score variance; the page warns above ~1.25). Example on Serie A after 3 weeks: favourite won 69.4% of 18 matchups, Brier 0.2195, spread ratio 1.18.
7. **Recency choice** (`choose_half_life`): needs ≥10 finished weeks (raised from 6: the choice is graded on the weeks it was made from); half-lives 8/5/3 compared with equal weights by walk-forward Brier and adopted only if it wins by 2%. Each week of the odds history chooses from its own past only.
**Effect of the uncertainty upgrade on a real league:** top team 95.5% → 89.2%, second 85.9% → 75.0%, weakest 0.1% → 1.1%.
**Honest limits, stated on the page:** it is "a snapshot, not a forecast" ("if the rest of the season were played from today, 50,000 times (± margin)"); rosters, injuries, add/drops, streaming and trades are **not modelled**; tiebreakers beyond random are unknown. Comparisons used while designing it (Opta/FiveThirtyEight/Basketball-Reference/FanGraphs/MoneyPuck) and what each informed are in the plan file `the-tool-is-working-adaptive-gizmo.md` (an earlier version of it).

## 10. The page (`index.html`)

**Constraints:** one file, no dependencies, ES5 style, no build step. Inline fonts via Google Fonts link (Inter; Geist Mono for numbers); an inline-SVG favicon; a tiny inline theme script runs first to avoid a flash. CSS uses container-query units (`cqw`) so a sheet scales to its container (and the exported image); a fallback exists for browsers without them.

**Two scripts:** `<script id="pure">` defines `RotoPure` (no DOM): `places, cls, rankCls, matrixCls, fmtVal, fmtPts, pct, pts, signed, sortKey, tl, catLuckWeek, range, sos, sosRest, oppByWeek, form, split, realGame, movers`. They are unit-tested through node (`tests/test_page.py`) and parity-tested against Python (`tests/test_range.py`). The app script does state, rendering and events.

**Navigation model:**
- Week strip (Wk 1…N + Season; arrows and ←/→ keys, except inside tables). Week views: Roto Points, Raw Stats, All-Play Matrix, Matchups.
- **Season tabs** (`TABS`): Standings (Live standings, Season Roto, Raw Totals, Weekly Roto Points, Power Rank), All-Play (Matrix, Season All-Play), Luck (Summary, By week, By category, Matchup Log), Outlook (Playoff odds, Strength of schedule), Performance (Recent form, Vs strong/weak, Trends, Category Kings). Each tab has views underneath ("lens").
- `ALIAS` and `LENSFIX` map every older link (`?board=roto`, `?board=real`, `?board=catluck`, `lens=expected`...) to its current table: **never break an old link**.
- URL state: `?week=3&view=allplay`; `?season=1&board=<tab>&lens=<view>` plus `&basis=cats`, `&cat=PTS`, `&range=3-7`, `&win=5`, `&per=rest`, `&meas=luck&tbl=1`, `&sort=2.desc`, `&me=<teamId>`; `&static=1` (image layout), `&league=`, `&repo=`, `&data=` (custom source, shows a warning). League id from the path `/<id>/` too.
- Controls: week range bar (From/To selects + chips: "Weeks 1-N · final", "incl. live week", Last 3/5/8) applies to every season table except Odds/Form; **Matchups | Categories** switch on Luck, SOS, Form, Vs strong/weak; period toggle (Played | Rest of season) on SOS; Last 3/5/8 chips on Form; sorting by clicking any header (first desc, then asc, then default; numeric keys via `sortKey`); a **pin** ("tap your team") highlights your team everywhere and is remembered per league in `localStorage`; light/dark/auto theme toggle (saved locally, off in static mode).
- Robustness: refresh every 2 min re-renders only on change and keeps scroll and each table's sideways scroll; stale feed warning ("data is N min old", using server-clock skew so a wrong phone clock cannot hide it) plus `status.json` reasons ("refresh failing since 14:05 (5 tries: ...)"); friendly message for a league not yet published (404) with auto-retry; sticky floating header copy; arrow keys do not hijack tables; focus rings, Escape and focus-trap in the image overlay, contrast fixes; print hides the floating header.

**Design language:** blue header (#1667ac), white rounded sheet on grey, striped rows, green/red heat cells, mono numerals, pill tabs. **Colour rules** (all tested):
- `cls(p, n)`: roto points relative to n teams → strong/soft shades per side, with the **middle four places white** (7-10 of 16, 8-11 of 18); symmetric for any league size.
- `shadeCol(ids, vals, lower)`: the one colour rule applied to any column (green = best of the league in that column, red = worst).
- `matrixCls(margin)`: category margin buckets for matrix, score and margin cells (≥5 dark green, ≥3 green, >0 light green, 0 white, then mirror).
- `luckCls`: one week's luck scaled by √(number of weeks) so ranges and single weeks agree.
- Odds: Playoffs % coloured by probability band (≥90, ≥65, 35-65 white, ≤35, ≤10).
- **Small squares (`chips`)**: one per week or opponent, same green / white / red family. Ranked squares use `rankCls`; result squares (recent form) use the margin shades (`matrixCls`); an unplayed/unknown slot is a dashed empty square (class `none`). Boards with squares: Weekly Roto Points (that week's roto rank), Season All-Play (that week's all-play rank), Recent form (result `W/L/T`, or the score `5-4` on the Categories basis, shaded by margin), Strength of schedule (rank of that week's opponent, 1 = strongest, red = strong; ties are coloured by their average place; in Rest of season the weeks to come, from `odds.schedule`). `RotoPure.oppByWeek` computes the SOS squares (parity-tested). Chip cells carry `data-sort` (their average) so header sorting still works.
- Only key columns are coloured; the tests keep two lists, `COLOURS` (must contain both green and red) and `PLAIN` (must have no shading).
**Copy limits (tested):** note ≤ 60 words, subtitle ≤ 16, tooltip ≤ 16; banned jargon (`log5`, `shrunk`, `competition rank`, `basis`, `Exp.`, `Diff`, `Cat luck`...). README lines ≤ 80 words, ≤ 900 words total, no internals. No `"W" +` week labels.
**Trends view** (the only chart; small per-row lines were removed): an SVG line per team for cumulative luck / category luck / all-play Win% / roto rank / expected wins, with a dashed baseline (0 = as lucky as deserved, 50%, the middle rank), end labels for the top and bottom three plus your team, your real results as marks, a caption, a "show as table" toggle. The tiny in-table sparklines (and `RotoPure.sparkGeom`) were deleted: weekly roto and all-play show per-week rank squares, odds show "Since Wk N" points, form shows result squares, SOS shows opponent squares.

## 11. Image export

Two paths, one layout (static mode, `?static=1`, 1680 px wide, 2600 px for the matrix):
- **CLI** (`--report DIR --png [--season] [--week N]`): `write_images` runs headless Chrome (`--virtual-time-budget=20000`, device scale 1.5), measuring the sheet's height first via a `<meta name="report-height">` the page writes, then screenshotting at exactly that height. Files: `roto.png`, `stats.png`, `allplay.png`, `matchups.png`, or `season-<board>.png` for the 12 `SEASON_BOARDS`.
- **In page ("Save image")**: `renderStatic` re-renders the sheet in static mode, serialises it, wraps it in an SVG `foreignObject` with the page's CSS (rewriting `:root{`, `html{`, `body{`, `body.static` for the wrapper) and embedded font faces for the characters actually used (Vietnamese names), draws it to a canvas (scale ≤1.5, ≤14 megapixels for phones), then downloads, or opens the share sheet on touch devices (long-press overlay fallback). A test asserts the saved image has exactly the CLI image's size.
- **`fitStatic`**: a table wider than the image shrinks its font (down to 70%) until it fits, so no category or Rank column is ever cut off. The Luck by week grid and other wide tables rely on `td.cat` (min-width 0) for narrow cells.
- A CSS test forbids rules targeting `html`/`body` in ways the export rewrite cannot move.

## 12. The live feed and CI/CD

**`roto-live.yml` ("Roto live")**: cron every 15 min is only a backstop; each run's first step queues its own successor (`gh workflow run`), concurrency group `roto-live` keeps one waiting. Each run loops ~115 minutes (`end = now + 6900 s`, timeout 125 min): fetch the `data` branch (carries `_cache` and the other leagues' reports so a one-league run or a failed league cannot wipe them), then repeat: for each league run `python3 yahoo_roto.py <id> --report out/<id> --cache cache/_cache`; on success `cadence.py record` (prints `changed`/`same`), on failure `cadence.py fail` (previous report stays); write `status.json`; open **one** GitHub issue per outage after 5 consecutive failed passes (`cadence.py alerts`, issue title "Roto feed failing: league <id>"); commit the whole output into a fresh git repo and **force-push the orphan `data` branch** (never grows); sleep per `cadence.py delay` (fallback: 240 s at night/weekends, 900 s otherwise). `workflow_dispatch` input `league` runs once for one league. About 12 Yahoo requests per league per pass.

**`cadence.py`**: sleeps FAST = 180 s while the report fingerprint changed in the last 20 min, then 300/600/1800/3600 s as quiet time grows (≥3 days quiet = hourly, offseason); clock only sets a ceiling (≤600 s in US game hours 22:00-07:00 UTC and weekend afternoons from 16:00 UTC, ≤1800 s otherwise) so a tip-off is noticed within ~10 minutes; an optional game feed (`games=`) can force fast. State in `_state.json`; atomic writes; public status has no internal fields.

**`restart-live.yml`**: on push to `main` touching `yahoo_roto.py`, `cadence.py`, `index.html`, `leagues.json` or `roto-live.yml`, cancel in-progress/queued live runs and start one on the new commit (a run keeps its commit for ~2 h and its queued successor is pinned too, so merges would otherwise take hours to reach the data).

**`test.yml`**: on PRs and pushes to main: Python 3.10 and 3.12 matrix → `pip install pyflakes` → `pyflakes yahoo_roto.py cadence.py canary.py pages.py tests` → `unittest discover -s tests -v` (includes headless-Chrome page tests on the runner's Chrome; node 20 installed). A second job lints workflows with actionlint (docker). **`canary.yml`**: daily 13:17 UTC runs `canary.py` on the first league in `leagues.json` (needs ≥3 categories, ≥4 teams, a week with stats, every team has a value in every category, nothing skipped); a red run emails the owner. **Dependabot** bumps Actions weekly (checkout/setup-python/setup-node are at v7).

**Publishing a new league:** add id (and name) to `leagues.json`, run `python3 pages.py`, commit, merge, run "Roto live" once. Pages from `main` `/`; Actions permission "Read and write".

## 13. Tests (~180, no network)

- `golden.py`: `build_pages(n, weeks, seed, regular, divisions, spots)` generates Yahoo-shaped pages for a league (the last week with stats counts as the live one; with `regular` the settings page states playoffs; `divisions` splits East/West) and `build_report(...)` runs it through the real pipeline (`fast=True` shrinks the simulation).
- `test_golden` (invariants: every weekly category hands out the points, all-play is one game per opponent, luck and category luck sum to zero, roto totals follow from points, re-running is identical, the "final" snapshot equals the report without the live week), `test_composites`, `test_yahoo_roto` (HTTP layer, parsers, math, cache/corrections, CLI, resilience, privacy), `test_parity` (against an independent computation on a saved real week, fixtures/week-01.json), `test_range` (JS `range`, `catLuckWeek`, `sos`, `sosRest`, `form`, `split` vs from-scratch Python, both bases), `test_odds` (settings parsing, schedule cache, simulation vs an **exact enumeration** on a small league, strength uncertainty, backtest vs independent computation, history, accuracy in the report), `test_current_week` (corrections parser, recheck schedule, settled-week report, fallbacks), `test_cadence`, `test_canary`, `test_pages`, `test_page` (node-driven pure helpers, README/CSS lints), `test_browser` (headless Chrome via a generated harness page, including checks that every small square belongs to the rank-or-margin shade family and that each board has the right number of squares; sites `old/`, `pre/`, `none/`, `early/`, `long/`, `settled/`; checks tabs, views, colours, plain columns, copy lint, export size, fitting on a full-length season, week labels, odds reliability line and movers, the settled-week banner).
- The odds speed test uses a loose 90 s ceiling (CI runners are 2-4× a laptop). The browser test file takes ~80 s: run it in the background locally. Set `ROTO_NO_BROWSER=1` to skip it.

## 14. Design principles, with the history behind them

1. **Explain the numbers, never judge people** (no "robbed/stolen"; "Luck" is "result minus what your stats earned").
2. **One idea per table; calm colour.** Evolved through: raw colours everywhere → consistent luck colours (commit 1127d58) → "one rank-shade rule, Wk labels, plain copy" (d7eedb1) → "one or two coloured columns per table" (cb6121d).
3. **Few tabs, views underneath.** Season boards began as a flat menu of ~12 boards that wrapped to 4 rows on phones; grouped into tabs (3093656) and again into five (73335e6, cb6121d).
4. **Honest about uncertainty.** Odds show simulations, margin, incomplete-schedule warnings, accuracy and calibration; the page never says "forecast".
5. **Phone and image first.** Sticky headers, scroll-safe refresh, one-row phone menu, share sheet, fitted images.
6. **No dependencies; pure helpers shared and parity-tested.** Browser and Python implement the same maths for ranges; tests prove they agree.
7. **Never break a link.** Alias tables for every board ever shipped.
8. **Fail soft, say why.** Retries, atomic cache, damaged-file tolerance, best-effort rechecks, stale-feed explanations, one alert per outage, daily canary.
9. **Real over proxy.** Form and split show real results; all-play is kept for the luck story and as the strength rating.
10. **Charts only where they can be inspected.** Replace tiny lines with numbers and shades.

## 15. Timeline (all dates 2026)

- **13 Nov:** seed (standalone roto tool, page, live workflow, tests) → score/matchups/composites in the report → restyle after the reference sheet, week browsing and season boards → PNG export → CI → Category Luck → 15-min cron backstop → modern styling, per-league addresses → league 212003, Category Kings redesign → real rank by category record → sticky headers → UX audit work (scroll-safe refresh, phone menu, my-team pin, click-to-sort, link previews, dark theme).
- **16 Nov (one very long day):** "big update" (in-page image export, live-week snapshot, adaptive polling, corrections tracking, resilience, canary; 102 tests) → Dependabot bumps → champion name matching → week range for every season board → Matchups view/Matchup Log → restart-live workflow → luck colour consistency → browser-test flake fix → season tabs → expected standings and SOS → playoff odds v1 (8,000 sims) → odds full schedule + 50,000 sims + cache → simpler Luck/real SOS/Outlook → clarity pass → Performance tab (Boom/Bust removed) → trend lines → SOS counts every opponent game + rest-of-season → league 49486 + live ROS → odds uncertainty/accuracy/recency (#35) → odds page (#36) → real-record form, Yahoo current week + corrections, no sparklines (#37-#39, re-opened as #40).

## 16. State of play, backlog, open choices

- **Merged to `main`:** everything through PR #40 (odds model, real-record form/split, Yahoo's current week + corrections tracking, sparklines removed). Verified live on 16 Nov 2026 (16:04 UTC): all four leagues publish `inProgressWeek: null`, `currentWeek: 5`, `settling` for week 4; the live pages say "Wk 4 is complete; Yahoo may still correct box scores until Mon 16 Nov (4 pending, 22 arrived too late to count)".
- **Open: PR #41** (`feat/chips`): the small coloured squares described in §10 (weekly roto restored, all-play, recent form, SOS). After the owner merges it: `git merge-base --is-ancestor <commit> origin/main`, wait for the feed restart, dump the live page to confirm.
- `HANDOFF.md` (this file) is committed with PR #41; keep it updated when behaviour changes.
- **Backlog the owner logged:**
  - **B1** Trends chart line colour/styling so lines are easy to tell apart (colour by division, hover/tap isolate with values, end labels, clickable legend, dash styles as a second channel; must stay readable in static mode; keep green/red for ranks).
  - **B2** (done in PR #40) real records for form and strong/weak; all-play only for luck and as odds input.
  - **B3** broad strokes: make the stats layers foolproof and honest about what has happened vs what might happen despite injuries/add-drops/schedule (two clearly separated voices; uncertainty shown; what the model does not know stated once; guard rails for odd data: partial live weeks, byes, odd team counts, no divisions, other category sets, ties, very short seasons; per-league validation; an adversarial review of every view).
- Ideas not selected: championship odds (bracket simulation); GitHub issues/BACKLOG.md for the backlog; showing per-stat correction lines beyond the banner.
- **Open product choice noted:** Vs strong/weak has few games early in the season; currently it greys thin samples and shows game counts rather than defaulting to the Categories basis.
- **Known model limits:** category independence assumption (spread ratio can exceed 1.25), no rosters/injuries, tiebreaker unknown, sample-size sensitivity early; Yahoo markup changes are the main operational risk (the canary exists for this); only NBA verified; ratio categories (ERA/WHIP) skipped.

## 17. Gotchas

- After editing `index.html` or `leagues.json`, run `python3 pages.py`; a test fails otherwise (this bit several PRs). A merge of `main` can also leave a league page copy stale.
- ES5 only in `index.html` (no arrow functions/`let`) and no CSS selectors on `html`/`body` beyond the supported forms.
- The page re-derives week ranges in the browser, so a new per-week field must be in both the report and `RotoPure.range`'s expectations, with a parity test.
- `inProgressWeek` can be **null** now: every consumer (`cur()`, `weekNo()`, status line, static stamp, strip "live" dot) must tolerate it. `weekNo()` falls back to the last week.
- `odds_block`'s `live` flag changes which week starts the remaining schedule and the cache fingerprint; `odds_history` takes the same flag.
- `_cache_put(..., extra=...)` meta fields (`applies`, `checked`, `pending`, `late`) are optional; old cache files lack them.
- Golden test pages treat the last stats week as live; the `settled` test fake (`tests/test_current_week.py::Fake`) answers the default matchup URL with week 5.
- Do not sleep-poll; do not run `discover` for everything in one 120 s shell call (browser tests alone take ~80 s).
- Stacked PR merges can strand commits (see §2): this happened with #37-#39, which is why the live pages kept showing week 4 as in progress for hours.
- Never ship a visual change without looking at screenshots (see §2).

## 18. Glossary

**All-play:** your week against every other team, each a game won with more categories. **Basis:** Matchups (weekly W/L/T) or Categories (categories won). **Brier score:** mean squared forecast miss, 0.25 = a coin flip. **Canary:** the daily real-Yahoo health check. **Composite:** a season board derived from the weekly data. **Correction:** a Yahoo/NBA fix to an old box score; "late" corrections never change scoring. **Current week:** the week Yahoo's default matchup page shows. **Data branch:** the orphan branch holding published reports and the cache. **Empirical Bayes:** shrinking each team's average toward the league mean by an amount estimated from the league's own spread. **Expected wins:** sum of weekly all-play Win%. **Fingerprint:** hash of a report (or of odds inputs) to detect change. **Golden league:** the generated 18-team test league. **Half-life:** weeks after which a week's weight halves in the recency option. **Luck:** real wins minus expected wins. **Margin (odds):** 95% simulation noise in percentage points. **Settling / settled:** a week Yahoo has closed whose corrections may still land / is over. **SOS:** strength of schedule (opponents' real winning percentage over all their games). **Static mode:** the `?static=1` layout the images are drawn from.
