# yahoo-roto

Turns any **public, head-to-head** Yahoo fantasy league into a page with roto standings, luck, strength of schedule and playoff odds. Give it the league id. It reads Yahoo's public pages, never signs in, and uses only the Python standard library.

## What you get
Each week has its own view (Wk 1, Wk 2, ...), and the **Season** tab has five tabs:

| Tab | The question it answers |
| --- | --- |
| **Standings** | Who is ahead? Roto points by category, raw totals, weekly roto points, power rank, live standings. |
| **All-Play** | How good are your stats, whoever you faced? |
| **Luck** | Did you win more or less than your stats deserved? Summary, by week, by category, every matchup. |
| **Outlook** | Who will make the playoffs, and how hard was each schedule? |
| **Performance** | Who is hot (last 3, 5 or 8 weeks)? Who beats strong teams? How did everyone's numbers move over time? Who led each category? |

Each table colours only its one or two key columns, so a colour always means one thing.

Luck and schedule tables open on **Categories**; a switch shows matchups instead. The week range (Weeks 1-N, Last 3 / 5 / 8, or any From / to) applies to most season tables.

The Trends view charts luck, rank and Win% by week. Tap your team's name to highlight it everywhere, **Copy link** shares the exact view, and **Save image** (top right) saves the table as a PNG. It works on phones.

## The numbers in plain words
- **Roto points:** in each category the best team gets the most points and the worst gets 1. Ties share.
- **All-play:** each week, how you would have done against every team. A game is won by taking more categories.
- **Expected wins:** each week's all-play Win% added up. It is how many matchups your stats should have won.
- **Luck:** real wins minus expected wins. **Category luck** is the same in categories won.
- **Strength of schedule (SOS):** how often your opponents have won, counting every game they played, for those faced and those still to come.
- **Playoff odds:** the rest of the season is played out 50,000 times from each team's strength. Standing is category points, and division winners qualify first if the league says so.
- **Honest odds:** strength is treated as uncertain, so early odds stay cautious. The page grades itself on the weeks already played and shows who moved since last week. Rosters and injuries are not modelled.

None of this is a Yahoo number.

## Use it from the command line
```bash
python3 yahoo_roto.py 85092                          # text table: season roto
python3 yahoo_roto.py 85092 --week 3                 # one week (--through 3 = weeks 1-3, --json for JSON)
python3 yahoo_roto.py 85092 --report out/            # out/index.html (opens anywhere) + out/report.json
python3 yahoo_roto.py 85092 --report out/ --png      # also PNGs of the current week (needs Chrome or Chromium)
python3 yahoo_roto.py 85092 --report out/ --png --season   # PNGs of the season tables
python3 yahoo_roto.py 85092 --report out/ --cache .cache   # later runs fetch only the newest week
```
Set `$CHROME` if Chrome is not found. Tests, with no network: `python3 -m unittest discover -s tests`.

## Publish your league
This repo is the setup: GitHub Pages serves the page, and the `Roto live` workflow keeps each league's data fresh.
1. Settings > Pages: deploy from branch `main`, folder `/`. Settings > Actions > General: workflow permissions "Read and write".
2. Put your league ids in `leagues.json`.
3. Run `python3 pages.py`, commit, and push. Each league gets its own address: `https://<owner>.github.io/yahoo-roto/<id>/`.
4. Run the "Roto live" workflow once (Actions tab). It keeps itself running.

To show a defending champion's crown, add `"champions": {"<league id>": "<team name or team id>"}` to `leagues.json`.
Cup leagues (teams qualified from elsewhere) take a `cups` entry: see ARCHITECTURE.md.

## Keeping it fresh
- The feed refreshes about every 3 minutes while games are being played, and slows down when nothing changes.
- A week counts as over when Yahoo itself moves to the next one. Yahoo and the NBA fix box scores until a set Monday: closed weeks are re-read until then, the page says what may still change, and it shows what did.
- If a league fails to refresh several times in a row, the workflow opens one GitHub issue, and the page says why its data looks old.
- Changing the code on `main` restarts the feed, so new features reach the data within minutes.
- A daily check runs against a real league and fails if Yahoo's pages change shape.

How the pieces fit, page addresses, the cache and the odds internals are in `ARCHITECTURE.md`. Running and extending the tests is in `CONTRIBUTING.md`.

## Limits
- The league must be viewable without signing in. A private or unknown id gets a plain message.
- Head-to-head leagues only. A pure roto league has no weekly pages and is refused.
- Counting categories and made/attempted percentages work. Ratio categories such as ERA and WHIP are listed and skipped.
- Checked against an independent calculation on one NBA league with 9 categories. Other leagues and sports are untested.
