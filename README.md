# yahoo-roto

Roto points, raw category totals and an all-play matrix for any **publicly viewable, head-to-head** Yahoo fantasy league, from its league id. Python 3
standard library only, read-only, no sign-in. 

## Quick use
```bash
python3 yahoo_roto.py 85092                          # text table: season roto (every week with stats)
python3 yahoo_roto.py 85092 --week 3                 # one week; --through 3 = weeks 1-3; --json for machine-readable
python3 yahoo_roto.py 85092 --report out/            # out/index.html (self-contained, opens anywhere) + out/report.json
python3 yahoo_roto.py 85092 --report out/ --png      # + out/roto.png, stats.png, allplay.png of the current week (needs Google Chrome / Chromium)
python3 yahoo_roto.py 85092 --report out/ --png --week 3   # the same three images for week 3
python3 yahoo_roto.py 85092 --report out/ --png --season   # out/season-<board>.png for the seven season boards
python3 yahoo_roto.py 85092 --report out/ --cache .cache   # reruns only fetch the newest week
```
`index.html` (the page template; the report writes a self-contained copy with the JSON inlined) opens on the latest week with stats ("Week N (in progress)").
A week strip (`W1 ... WN`, `<` `>` buttons, left/right keys) switches weeks; the **Season** tab holds the composite boards (Season Roto, Raw Totals, All-Play
Matrix, Weekly Roto Points, Season All-Play, Real Record & Luck, Category Luck, Category Kings, Boom / Bust, Power Rank). Roto Points / Raw Stats / All-Play Matrix keep the
chosen week. The choice lives in the URL: `?week=3&view=allplay` (views `roto`, `stats`, `allplay`) or `?season=1&board=power`. It is built for phones too:
the team column sticks and wide tables scroll inside their own box, never the page. The look follows `reference/serie_a_week3.html`.

The PNGs are drawn from the same page in static mode at device scale 1.5 (1680 px wide for roto, stats and the season boards, 2600 px for the all-play matrix), cropped to
the sheet. Set `$CHROME` if Chrome is not found. Fonts (Inter) come from Google Fonts; offline, system fonts are used.

## A public link that refreshes itself on game days
This repo is the setup: GitHub Pages serves `index.html` from `main`, and the `Roto live` workflow (`.github/workflows/roto-live.yml`) keeps
`<league>/report.json` fresh on an orphan `data` branch.
1. Settings > Pages: deploy from branch `main`, folder `/`. Settings > Actions > General: workflow permissions "Read and write".
2. Put your league ids in `leagues.json`. Run the "Roto live" workflow once (Actions tab, optional league id). It loops about 115 minutes per run (every
   ~4 min on game hours, 15 min otherwise), queues its own successor (GitHub drops many cron triggers), and force-pushes `<league>/report.json` to `data`.
3. Share `https://<owner>.github.io/yahoo-roto/` (opens the first league in `leagues.json`, with a league switcher when there are several), or `?league=<id>`; `&repo=<owner>/yahoo-roto` is only needed off github.io. `?board=catluck` (or any season board) opens the Season tab directly. The page re-fetches the JSON every 2 minutes while visible and
   says "data is N min old" if the feed stalls. Add `&me=<teamId>` to mark your team, `&week=3&view=allplay` to deep-link.

About 12 Yahoo requests per league per refresh (settings, standings, one page for the week list, the 8 pages of the in-progress week for 16 teams, one probe of the next week; finished weeks are cached), 1.5 s apart (~20 s). Keep `leagues.json` small.

## How roto is computed
Per category, teams are ranked (worst = 1 point, best = number of teams, level teams share the average place, fewer is better for TO/PF). Season roto adds
the weekly totals first; percentages come from summed makes and attempts. All-play: every team against every other, category by category. All of it is
derived here and display-only: not a Yahoo number. A week is final once a later week has stats; the newest week is "in progress".

### Expected wins, by hand
Each week, every team plays every other team in every category (all-play). Win% = (W + T/2) / (W + L + T) over those category battles; with 16 teams and 9
categories that is 135 battles, so 90-40-5 is (90 + 2.5) / 135 = 0.685. Expected wins = the sum of those weekly Win% values (0.685 + 0.500 + 0.400 = 1.59 after
three weeks). Luck = real matchup wins (a tie counts half) minus expected wins, so 3 real wins would be +1.41. It reads "how many matchups your stats should have won".

### Category luck, by hand
The same idea per category, on the **Category Luck** season board (`?season=1&board=catluck`). For one team, one category, one week: expected = the share of the
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
