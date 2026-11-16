# yahoo-roto

Roto points, raw category totals and an all-play matrix for any **publicly viewable, head-to-head** Yahoo fantasy league, from its league id. Python 3
standard library only, read-only, no sign-in. 

## Quick use
```bash
python3 yahoo_roto.py 85092                          # text table: season roto (every week with stats)
python3 yahoo_roto.py 85092 --week 3                 # one week; --through 3 = weeks 1-3; --json for machine-readable
python3 yahoo_roto.py 85092 --report out/            # out/index.html (self-contained, opens anywhere) + out/report.json
python3 yahoo_roto.py 85092 --report out/ --png      # + out/roto.png, stats.png, allplay.png, matchups.png of the current week (needs Google Chrome / Chromium)
python3 yahoo_roto.py 85092 --report out/ --png --week 3   # the same three images for week 3
python3 yahoo_roto.py 85092 --report out/ --png --season   # out/season-<board>.png for the seven season boards
python3 yahoo_roto.py 85092 --report out/ --cache .cache   # reruns only fetch the newest week
```
The page has a **Save image** button (download icon, top right): one tap saves the board you are looking at as a PNG (the phone share sheet on a phone), drawn the same way as the `--png` files and following your current sort. `index.html` (the page template; the report writes a self-contained copy with the JSON inlined) opens on the latest week with stats ("Week N (in progress)").
A week strip (`W1 ... WN`, `<` `>` buttons, left/right keys) switches weeks; the **Season** tab holds the composite boards in four tabs, each with its views underneath: **Standings** (Season Roto, Raw Totals, Weekly Roto Points, Power Rank, Playoff odds), **All-Play** (Matrix, Season All-Play), **Luck** (Summary = real record and luck with category luck, Expected standings, Schedule, By week, By week · categories, By category, Matchup Log) and **Records** (Category Kings, Boom / Bust). The address is `?season=1&board=<tab>&lens=<view>`; every older link (`board=roto`, `board=real`, `board=catluck` ...) still opens the same table. Roto Points / Raw Stats / All-Play Matrix / Matchups keep the
chosen week. **Matchups** lists each matchup as a pair of rows with the category-by-category result, score, margin, the week's all-play record and Win%, and luck (plain numbers, no labels); **Expected standings** ranks teams by what their stats earned next to their real rank; **Schedule** shows strength of schedule (each opponent's Win% without the game against that team) and splits Luck into schedule luck and result luck (log5 estimate). **Matchup Log** (Season tab) is the same per team and week over the chosen range, sortable by any column. The Season tab has a **week range** under the board buttons that applies to every season board: chips for **Weeks 1-N final** (the default for the derived boards, so a half-played week cannot skew Boom / Bust, Luck or Power Rank), **incl. live week** (the default for Season Roto and Raw Totals, which are the current standings) and **Last 3 / 5 / 8**, plus From / to week selects for any stretch (the page rebuilds the boards for those weeks from each week's data; `tests/test_range.py` checks it agrees with the Python numbers). The range is in the link (`range=3-7`) and in saved images; `--png --season` images use the default weeks. **Luck** has three views (the toggle above the table): by week (each team's matchup luck every week: result minus the all-play Win%), by week with categories (the same for categories won against what the stats earned, optionally just one category) and by category (a column per category); matchup luck and category luck totals sit side by side on all three. Old `board=luckweeks` / `board=catluck` links still open the right view. "Copy link" in the status line copies the exact view, including sort and your team. The choice lives in the URL: `?week=3&view=allplay` (views `roto`, `stats`, `allplay`) or `?season=1&board=power`. It is built for phones too:
the team column sticks and wide tables scroll inside their own box, never the page. The look follows `reference/serie_a_week3.html`.

The PNGs are drawn from the same page in static mode at device scale 1.5 (1680 px wide for roto, stats and the season boards, 2600 px for the all-play matrix), cropped to
the sheet. Set `$CHROME` if Chrome is not found. Fonts (Inter) come from Google Fonts; offline, system fonts are used.

## A public link that refreshes itself on game days
This repo is the setup: GitHub Pages serves `index.html` from `main`, and the `Roto live` workflow (`.github/workflows/roto-live.yml`) keeps
`<league>/report.json` fresh on an orphan `data` branch.
1. Settings > Pages: deploy from branch `main`, folder `/`. Settings > Actions > General: workflow permissions "Read and write".
2. Put your league ids in `leagues.json`. Run the "Roto live" workflow once (Actions tab, optional league id). It loops about 115 minutes per run (the pace follows
   the data, see `cadence.py`: about every 3 min while the totals are changing, slower the longer nothing moves, hourly in the offseason, never slower than 10 min in US game hours), queues its own successor (GitHub drops many cron triggers), and force-pushes `<league>/report.json` to `data`.
3. Each league has its own address: `https://<owner>.github.io/yahoo-roto/<id>/` (e.g. `/207464/`). Adding a league = add the id to `leagues.json`, run `python3 pages.py` (writes `<id>/index.html`; a test fails if the copies are stale) and commit. The bare site address opens the first league. `?board=catluck` (or any season board) opens the Season tab directly, `&week=3&view=allplay` deep-links a week, `&me=<teamId>` marks your team.
   says "data is N min old" if the feed stalls. Add `&me=<teamId>` to mark your team, `&week=3&view=allplay` to deep-link.

About 12 Yahoo requests per league per refresh (settings, standings, one page for the week list, the 8 pages of the in-progress week for 16 teams, one probe of the next week; finished weeks are cached), 1.5 s apart (~20 s). Keep `leagues.json` small.

`leagues.json` can also name each league's defending champion, which gets a crown next to its name everywhere: `"champions": {"<league id>": "<team name or team id>"}` (names match ignoring case and extra spaces; no match means no crown). `--champion` on the command line overrides it.

### Stat corrections
Yahoo and the NBA correct box scores for a day or two after a game. A finished week stays in the cache but is read again about 1 h, 6 h, 24 h and 48 h after it was first stored; if any
total moved, the new numbers replace the old ones (every board recomputes) and the change is kept on the report for 14 days: the page shows a dismissible banner (category totals that
moved, roto-rank moves for that week, matchup results that flipped) and a dot on that week's button. Old cache files (no timestamp) are left alone.

### Operations
- **Alerts:** each pass records failures per league; after 5 in a row the workflow opens one GitHub issue ("Roto feed failing: league ID"), and `status.json` on the `data` branch lets the page say why a report looks old. Network failures, 5xx and 429 are retried before a pass counts as failed.
- **Restart on code changes:** a live run keeps the code it started with for about two hours, so `restart-live.yml` cancels the live runs and starts a new one whenever `yahoo_roto.py`, `cadence.py`, `index.html`, `leagues.json` or the live workflow change on `main`. New report fields reach the published reports within minutes of a merge instead of hours.
- **Playoff odds (Monte Carlo):** read from the league itself, no setup: the settings page says how many teams make the playoffs and from which week ("Playoffs: 6 teams - Week 19, 20 and 21", so the regular season ends the week before), the standings page lists the divisions, and Yahoo shows a future week's pairing on its matchup page. The report simulates the rest of the regular season 50,000 times (`odds` in the report; see `yahoo_roto.py`, "playoff odds"; every figure is within about 0.4 percentage points, 95%): a team's strength in each category is its weekly average pulled toward the league average, each matchup is played category by category, the standing is category points, and with "division winners advance" every division leader qualifies first. Yahoo has no page listing a whole week's matchups, so the **whole remaining schedule** is read one matchup page at a time in the first pass (about 3 minutes per league) and remembered in `<league>-schedule.json`; afterwards only two weeks a pass are re-read (each about daily). `odds.complete` says whether every remaining week uses the real schedule. The answer is remembered in `<league>-odds.json` and only recomputed when its inputs change. A league whose settings page does not show a playoff line simply has no odds.
- **Canary:** `canary.yml` runs `canary.py` daily against one real league; a red run means Yahoo's pages changed shape (or blocked the runner).
- See `ARCHITECTURE.md` for how the pieces fit and `CONTRIBUTING.md` for running and extending the tests.

## How roto is computed
Per category, teams are ranked (worst = 1 point, best = number of teams, level teams share the average place, fewer is better for TO/PF). Season roto adds
the weekly totals first; percentages come from summed makes and attempts. All-play: every team against every other, category by category. All of it is
derived here and display-only: not a Yahoo number. A week is final once a later week has stats; the newest week is "in progress".

### Expected wins, by hand
Each week, every team plays every other team once (all-play). Each of those games is won by taking more of the categories than the opponent; level on categories is a tied game. With 16 teams that is 15 games a week, so the record is W-L-T out of 15, e.g. 10-4-1.
Win% = (W + T/2) / (W + L + T) = (10 + 0.5) / 15 = 0.700. Expected wins = the sum of those weekly Win% values (0.700 + 0.500 + 0.400 = 1.60 after three weeks).
Luck = real matchup wins (a tie counts half) minus expected wins, so 3 real wins would be +1.40. It reads "how many matchups your stats should have won".
The matrix cell for two teams shows the category score of that game (6-3: six categories to three; 4-4-1: four each and one level).

### Category luck, by hand
The same idea per category, on the **Category Luck** season board (Luck › By category). For one team, one category, one week: expected = the share of the
other teams it would have beaten in that category (level counts half); real = 1 if it beat its actual opponent in it (0.5 level, 0 lost). Each category
column is real minus expected, added over the weeks. Example: 12th of 16 in PTS beats 4 of 15 teams, expected 0.27; winning the category anyway is +0.73.
Real cats are the Score column's category wins; Luck is the sum of the category columns (zero across the league).

## Limits (stated, not hidden)
- The league must be viewable without a login. A private or unknown id gets a plain message; the tool never signs in and cannot read it.
- Head-to-head leagues only (weekly matchup pages). A roto-scoring league has no weekly pages and is refused, not guessed.
- Counting categories and made/attempted percentages are computed; ratio categories (ERA, WHIP ...) are listed and skipped.
- Verified on one league (NBA, 9 categories): week-1 roto and all-play equal an independent naive computation for all 16 teams (`tests/test_parity.py`,
  fixture `tests/fixtures/week-01.json`). Other leagues and sports are untested.

Tests (no network): `python3 -m unittest discover -s tests`.
