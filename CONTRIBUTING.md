# Working on yahoo-roto

```bash
python3 -m unittest discover -s tests        # everything; the browser tests use Chrome if it is installed (ROTO_NO_BROWSER=1 skips them)
python3 -m unittest tests.test_cadence       # one module
python3 pages.py                             # after editing index.html or leagues.json: refreshes <id>/index.html (a test fails if you forget)
python3 yahoo_roto.py 85092 --report out/ --png    # build a report and the images from a real public league
```

- **Tests need no network.** `tests/golden.py` builds a generated 18-team league through the real pipeline; use it for anything that needs realistic multi-week data (`golden.build_report(teams, weeks)`).
- **Page changes:** check them in static mode too (`?static=1`, and Save image): saved images must keep looking right. `test_page` fails if a CSS rule targets `html`/`body` in a way the image export cannot move. Check phone width (about 360-400 px).
- **Pull requests** run `Tests` (Python 3.10 and 3.12, pyflakes, headless Chrome) and `workflows` (actionlint). Keep changes in themed PRs with their tests.
- **Yahoo markup changes** are the main risk: the daily `Canary` run goes red when the parsers start returning less. To add a parser fix, extend the generated pages in `tests/golden.py` or the `matchup()` helper in `tests/test_yahoo_roto.py` to cover the new shape.
- No dependencies are added to the tool or the page. CI installs pyflakes only for linting.
