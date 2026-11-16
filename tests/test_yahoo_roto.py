"""Offline tests for yahoo_roto.py (no network): the page readers, the category plan, and the roto math."""
import os
import sys
import unittest
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import yahoo_roto as yr  # noqa: E402

SETTINGS = ("<html><body>Scoring Type: Head-to-Head - Categories Max Acquisitions for Entire Season: No maximum "
            "Make League Publicly Viewable: Yes Stat Categories: Field Goal Percentage (FG%), Free Throw Percentage (FT%), "
            "3-point Shots Made (3PTM), Points Scored (PTS), Turnovers (TO) Stat Modifiers: none Roster Positions: PG</body></html>")


def matchup(week, rows, weeks=(1, 2, 3)):
    opts = "".join('<option value="x?module=matchup&week=%d"%s>%d</option>' % (w, " selected" if w == week else "", w) for w in weeks)
    body = "".join('<tr><td><a href="/nba/9/%d">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td></td></tr>' % ((t, n) + tuple(v))
                   for t, n, v in rows)
    return ("<select>%s</select><table><tr><th>Team</th><th>FGM/A*</th><th>FG%%</th><th>FTM/A*</th><th>FT%%</th><th>3PTM</th><th>PTS</th><th>TO</th><th></th></tr>%s</table>" % (opts, body))


class Settings(unittest.TestCase):
    def test_scoring_type_categories_and_public_flag(self):
        s = yr.parse_settings(SETTINGS)
        self.assertEqual(s["scoring"], "Head-to-Head - Categories")
        self.assertEqual(s["categories"], ["FG%", "FT%", "3PTM", "PTS", "TO"])
        self.assertTrue(s["public"])

    def test_teams_come_from_the_standings_rows(self):
        html = '<table><tr><th>Rank</th><th>Team</th></tr><tr><td>1</td><td><a href="/nba/9/4">Alpha</a></td></tr><tr><td>2</td><td><a href="/nba/9/7">Beta</a></td></tr></table>'
        self.assertEqual(yr.parse_teams(html, 9), {4: "Alpha", 7: "Beta"})


class Weekly(unittest.TestCase):
    def test_a_matchup_page_keeps_made_attempted_pairs_and_none_for_dashes(self):
        w = yr.parse_week(matchup(2, [(1, "A", ["5/10", ".500", "3/4", ".750", "4", "30", "2"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])]), 9)
        self.assertEqual(w["week"], 2)
        self.assertEqual(w["weeks"], [1, 2, 3])
        self.assertEqual(w["teams"][1]["cols"]["FGM/A*"], (5, 10))
        self.assertEqual(w["teams"][1]["cols"]["PTS"], 30)
        self.assertIsNone(w["teams"][2]["cols"]["PTS"])
        self.assertIsNone(w["teams"][2]["cols"]["FGM/A*"])

    def test_a_page_without_a_matchup_table_is_refused(self):
        with self.assertRaises(yr.RotoError):
            yr.parse_week("<html><table><tr><th>Player</th></tr></table></html>", 9)


class Math(unittest.TestCase):
    HEADS = ["Team", "FGM/A*", "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "TO"]

    def test_plan_pairs_a_percentage_with_the_makes_before_it_and_skips_what_it_cannot_compute(self):
        specs, skipped = yr.plan(["FG%", "PTS", "TO", "ERA", "XYZ"], self.HEADS)
        self.assertEqual([(s["cat"], s["kind"], s["col"], s["lower"]) for s in specs],
                         [("FG%", "pct", "FGM/A*", False), ("PTS", "count", "PTS", False), ("TO", "count", "TO", True)])
        self.assertEqual(skipped, ["ERA", "XYZ"])

    def test_places_average_ties_and_fewer_is_better(self):
        self.assertEqual(yr.places([Fraction(5), Fraction(5), Fraction(9)], False), {0: 1.5, 1: 1.5, 2: 3})
        self.assertEqual(yr.places([Fraction(10), Fraction(2), Fraction(5)], True), {0: 1, 2: 2, 1: 3})            # most turnovers = 1 point

    def test_season_totals_sum_makes_and_attempts_not_percentages(self):
        wk = [{"week": 1, "teams": {1: {"cols": {"FGM/A*": (1, 2), "PTS": 10}}}}, {"week": 2, "teams": {1: {"cols": {"FGM/A*": (9, 10), "PTS": 5}}}}]
        t = yr.totals(wk, [1])
        self.assertEqual(t[1]["FGM/A*"], (10, 12))
        self.assertEqual(yr.cat_value(t[1], {"kind": "pct", "col": "FGM/A*"}), Fraction(10, 12))                    # not (50% + 90%) / 2
        self.assertEqual(t[1]["PTS"], 15)

    def test_roto_ranks_with_ties_and_a_competition_rank(self):
        specs, _ = yr.plan(["PTS", "TO"], self.HEADS)
        stats = {1: {"PTS": Fraction(30), "TO": Fraction(5)}, 2: {"PTS": Fraction(20), "TO": Fraction(9)}, 3: {"PTS": Fraction(20), "TO": Fraction(1)}}
        res, ranked = yr.roto(stats, specs)
        self.assertEqual(res[1]["points"], {"PTS": 3, "TO": 2})
        self.assertEqual(res[2]["points"], {"PTS": 1.5, "TO": 1})
        self.assertEqual(res[3]["points"], {"PTS": 1.5, "TO": 3})
        self.assertEqual([res[t]["rank"] for t in (1, 2, 3)], [1, 3, 2])                                            # 5.0, 2.5, 4.5
        self.assertEqual(ranked, [1, 3, 2])

    def test_a_category_with_a_missing_value_scores_nobody(self):
        specs, _ = yr.plan(["PTS"], self.HEADS)
        res, _ = yr.roto({1: {"PTS": Fraction(3)}, 2: {}}, specs)
        self.assertIsNone(res[1]["points"]["PTS"])
        self.assertEqual(res[1]["total"], 0)


class Fake(yr.Fetcher):
    def __init__(self, pages):
        super().__init__(delay=0)
        self.pages, self.urls = pages, []

    def get(self, url, ttl=None):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        raise yr.RotoError("unexpected " + url)


class AllPlayAndReport(unittest.TestCase):
    SPECS = [{"cat": "PTS", "kind": "count", "col": "PTS", "lower": False}, {"cat": "TO", "kind": "count", "col": "TO", "lower": True}]

    def test_all_play_counts_category_wins_and_records(self):
        stats = {1: {"PTS": Fraction(30), "TO": Fraction(5)}, 2: {"PTS": Fraction(20), "TO": Fraction(9)}, 3: {"PTS": Fraction(30), "TO": Fraction(9)}}
        cells, rec = yr.all_play(stats, self.SPECS)
        self.assertEqual(cells[1][2], [2, 0, 0])
        self.assertEqual(cells[1][3], [1, 0, 1])                                     # level on PTS, fewer TO
        self.assertEqual(cells[2][3], [0, 1, 1])
        self.assertEqual(rec, {1: [2, 0, 0], 2: [0, 2, 0], 3: [1, 1, 0]})
        self.assertNotIn(1, cells[1])

    def test_a_teams_all_play_record_is_one_game_per_opponent(self):
        # the README's by-hand example: 16 teams give 15 games a week (e.g. 10-4-1), not one per category
        stats = {i: {"PTS": Fraction(i * 3 % 7), "TO": Fraction(i * 5 % 11)} for i in range(1, 17)}
        cells, rec = yr.all_play(stats, self.SPECS)
        self.assertTrue(all(sum(r) == 15 for r in rec.values()))
        self.assertEqual(yr.win_pct([10, 4, 1]), Fraction(7, 10))

    def test_a_league_with_one_week_has_no_final_snapshot(self):
        pages = self._league("30")
        dash = ["-/-", "-", "-/-", "-", "-", "-", "-"]
        pages["week=2"] = matchup(2, [(1, "A", dash), (2, "B", dash)])               # only week 1 has stats, and it is the one in progress
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            doc = yr.report("9")
        finally:
            yr.Fetcher = orig
        self.assertEqual(sorted(doc["views"]), ["season", "w1"])
        self.assertIsNone(doc["compositesFinal"])

    def test_the_defending_champion_is_found_by_name_or_id_and_never_raises(self):
        names = {4: "Sup  Fam", 7: "Master Chef", 9: "Twin", 10: "twin"}
        self.assertEqual(yr.resolve_champion("sup fam", names), 4)
        self.assertEqual(yr.resolve_champion(" MASTER chef ", names), 7)
        self.assertEqual(yr.resolve_champion("7", names), 7)                         # a team id
        self.assertEqual(yr.resolve_champion(7, names), 7)
        for bad in (None, "", "nobody", "twin", "99"):                               # unknown, empty, ambiguous, id not in the league: no crown, no error
            self.assertIsNone(yr.resolve_champion(bad, names), bad)

    def test_a_name_with_a_tagline_or_punctuation_still_matches(self):
        names = {1: "M. Jordat | The Silver Seekers", 2: "sup fam | Crashed for Caleb", 3: "Master Chef", 4: "Other"}
        self.assertEqual(yr.resolve_champion("m jordat", names), 1)                  # punctuation and the tagline are ignored
        self.assertEqual(yr.resolve_champion("M. JORDAT", names), 1)
        self.assertEqual(yr.resolve_champion("sup fam", names), 2)
        self.assertEqual(yr.resolve_champion("master  chef", names), 3)
        # a whole-name match beats a tagline match; two tagline matches are ambiguous: no crown
        self.assertEqual(yr.resolve_champion("sup fam", {1: "sup fam", 2: "sup fam | x"}), 1)
        self.assertIsNone(yr.resolve_champion("sup fam", {1: "sup fam | a", 2: "sup fam | b"}))
        self.assertIsNone(yr.resolve_champion("the silver seekers", names))           # only the part before the bar counts

    def test_the_report_carries_the_champion_team_id(self):
        pages = {"settings": SETTINGS, "lhst=stand": '<table><tr><th>Team</th></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr></table>',
                 "week=1": matchup(1, [(1, "A", ["5/10", ".5", "3/4", ".75", "4", "30", "2"]), (2, "B", ["4/10", ".4", "2/4", ".5", "6", "25", "5"])]),
                 "week=2": matchup(2, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])]),
                 "week=3": matchup(3, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])])}
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            self.assertEqual(yr.report("9", champion="b")["champion"], 2)
            self.assertIsNone(yr.report("9", champion="zzz")["champion"])
        finally:
            yr.Fetcher = orig

    def _league(self, w1_pts_a):
        both = lambda w, pa, pb: matchup(w, [(1, "A", ["5/10", ".5", "3/4", ".75", "4", pa, "2"]), (2, "B", ["4/10", ".4", "2/4", ".5", "6", pb, "5"])])
        empty = matchup(3, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])])
        return {"settings": SETTINGS, "lhst=stand": '<table><tr><th>Team</th></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr></table>',
                "week=1": both(1, w1_pts_a, "29"), "week=2": both(2, "10", "40"), "week=3": empty}

    def test_a_finished_week_is_checked_again_and_a_changed_total_is_recorded_and_replaces_the_cache(self):
        import tempfile
        pages = self._league("30")
        fx = Fake(pages)
        orig = yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            with tempfile.TemporaryDirectory() as d:
                T0 = 1_000_000
                fixes = []
                _, _, wd, _ = yr.load("9", d, 0, now=T0, fixes=fixes)             # week 1 becomes final and is stored
                self.assertEqual((fixes, wd[0]["teams"][1]["cols"]["PTS"]), ([], 30))
                pages["week=1"] = self._league("27")["week=1"]                       # Yahoo corrects Team A's points: 30 -> 27 (A now trails B's 29)
                _, _, wd, _ = yr.load("9", d, 0, now=T0 + 1800, fixes=fixes)         # too early to look again: no request for week 1, old total kept
                self.assertEqual((fixes, wd[0]["teams"][1]["cols"]["PTS"]), ([], 30))
                _, _, wd, _ = yr.load("9", d, 0, now=T0 + 3700, fixes=fixes)         # one hour on: re-read, the change is noticed
                self.assertEqual(len(fixes), 1)
                self.assertEqual((fixes[0]["week"], wd[0]["teams"][1]["cols"]["PTS"]), (1, 27))
                specs, _ = yr.plan(["PTS", "TO"], ["Team", "FGM/A*", "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "TO"])
                ev = yr.correction_event(fixes[0], specs)
                self.assertEqual(ev["changes"], [{"team": 1, "cat": "PTS", "old": 30, "new": 27}])
                self.assertEqual(ev["week"], 1)
                _, _, wd, _ = yr.load("9", d, 0, now=T0 + 3800, fixes=fixes)         # the next look is 6 hours after the week was stored
                self.assertEqual(len(fixes), 1)
                self.assertEqual(wd[0]["teams"][1]["cols"]["PTS"], 27)
        finally:
            yr.Fetcher = orig

    def test_an_unchanged_recheck_records_nothing_and_old_cache_files_are_not_rechecked(self):
        import tempfile
        pages = self._league("30")
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            with tempfile.TemporaryDirectory() as d:
                fixes = []
                yr.load("9", d, 0, now=0, fixes=fixes)
                yr.load("9", d, 0, now=4000, fixes=fixes)
                self.assertEqual(fixes, [])
                p = yr._cache_path(d, "9", 1)
                data = __import__("json").load(open(p))
                self.assertEqual(data["checks"], 1)
                data.update({"v": 2}); data.pop("finalized"); data.pop("checks")
                __import__("json").dump(data, open(p, "w"))                              # a v2 file predates re-checking
                pages["week=1"] = self._league("1")["week=1"]
                _, _, wd, _ = yr.load("9", d, 0, now=10 ** 9, fixes=fixes)
                self.assertEqual((fixes, wd[0]["teams"][1]["cols"]["PTS"]), ([], 30))
        finally:
            yr.Fetcher = orig

    def test_corrections_are_kept_for_14_days_and_not_duplicated(self):
        import tempfile
        ev = {"week": 1, "at": 1000, "changes": [{"team": 1, "cat": "PTS", "old": 30, "new": 27}], "rank": [], "flips": []}
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(yr.update_corrections(d, "9", [ev], 2000)), 1)
            self.assertEqual(len(yr.update_corrections(d, "9", [ev], 3000)), 1)                 # the same event again: still one
            self.assertEqual(yr.update_corrections(d, "9", [], 1000 + 15 * 86400), [])         # older than 14 days: dropped

    def test_the_inlined_report_never_contains_a_raw_less_than(self):
        import tempfile
        doc = {"teams": {"1": "<!--<script>alert(1)</script>"}, "views": {}}
        with tempfile.TemporaryDirectory() as d:
            path = yr.write_html(doc, d)
            page = open(path, encoding="utf-8").read()
        blob = page.split("window.__REPORT__=", 1)[1].split(";</script>", 1)[0]
        self.assertNotIn("<", blob)
        self.assertEqual(__import__("json").loads(blob)["teams"]["1"], "<!--<script>alert(1)</script>")

    def test_finished_weeks_are_cached_and_the_newest_week_is_not(self):
        import tempfile
        wk = {"week": 1, "teams": {1: {"name": "A", "cols": {"FGM/A*": (5, 10), "PTS": Fraction(30)}}}}
        with tempfile.TemporaryDirectory() as d:
            yr._cache_put(d, "9", wk)
            back = yr._cache_get(d, "9", 1)
            self.assertEqual(back["teams"][1]["cols"], {"FGM/A*": (5, 10), "PTS": Fraction(30)})
            self.assertIsNone(yr._cache_get(d, "9", 2))

    def test_the_report_has_a_view_per_week_and_one_for_the_season_and_the_html_is_self_contained(self):
        import tempfile
        pages = {"settings": SETTINGS.replace("Scoring Type", "League Name: My League League Logo: x Scoring Type"),
                 "lhst=stand": '<table><tr><th>Team</th></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr></table>',
                 "week=1": matchup(1, [(1, "A", ["5/10", ".5", "3/4", ".75", "4", "30", "2"]), (2, "B", ["4/10", ".4", "2/4", ".5", "6", "25", "5"])]),
                 "week=2": matchup(2, [(1, "A", ["6/10", ".6", "1/4", ".25", "2", "10", "9"]), (2, "B", ["5/10", ".5", "4/4", "1", "1", "40", "1"])]),
                 "week=3": matchup(3, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])])}
        fx = Fake(pages)
        orig = yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            doc = yr.report("9")
        finally:
            yr.Fetcher = orig
        self.assertEqual(sorted(doc["views"]), ["season", "seasonFinal", "w1", "w2"])
        self.assertEqual(doc["views"]["seasonFinal"]["weeks"], [1])               # the newest week (2) is in progress: the final snapshot stops at week 1
        self.assertEqual(doc["compositesFinal"]["weeks"], [1])
        self.assertEqual(doc["views"]["season"]["weeks"], [1, 2])
        self.assertEqual(doc["inProgressWeek"], 2)
        self.assertEqual(doc["leagueName"], "My League")
        self.assertEqual([c["cat"] for c in doc["categories"]], ["FG%", "FT%", "3PTM", "PTS", "TO"])
        v = doc["views"]["season"]
        self.assertEqual(v["teams"]["1"]["values"]["PTS"], 40)
        self.assertEqual(v["teams"]["1"]["values"]["FG%"], 0.55)                      # 11/20, not the mean of two percentages
        self.assertEqual(len(v["matrix"]["1"]), 1)
        with tempfile.TemporaryDirectory() as d:
            path = yr.write_html(doc, d)
            html = open(path, encoding="utf-8").read()
            self.assertIn("window.__REPORT__=", html)
            self.assertIn('"leagueName": "My League"', html)
            self.assertTrue(os.path.exists(os.path.join(d, "report.json")))


class Private(unittest.TestCase):
    def test_a_private_or_missing_league_gets_a_plain_message(self):
        fx = Fake({"settings": "<html><title>There was a problem | Fantasy Basketball</title><body>Sign in</body></html>"})
        orig = yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            with self.assertRaises(yr.RotoError) as cm:
                yr.run("1234")
        finally:
            yr.Fetcher = orig
        self.assertIn("not publicly viewable", str(cm.exception))


class EndToEnd(unittest.TestCase):
    def test_one_page_covers_two_teams_and_a_week_without_stats_is_left_out(self):
        pages = {"settings": SETTINGS.replace("(PTS), Turnovers (TO)", "(PTS), Turnovers (TO)"),
                 "lhst=stand": '<table><tr><th>Team</th></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr></table>',
                 "week=1": matchup(1, [(1, "A", ["5/10", ".5", "3/4", ".75", "4", "30", "2"]), (2, "B", ["4/10", ".4", "2/4", ".5", "6", "25", "5"])]),
                 "week=2": matchup(2, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])]),
                 "week=3": matchup(3, [(1, "A", ["-/-", "-", "-/-", "-", "-", "-", "-"]), (2, "B", ["-/-", "-", "-/-", "-", "-", "-", "-"])])}
        fx = Fake(pages)
        orig = yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            doc = yr.run("9")
        finally:
            yr.Fetcher = orig
        self.assertEqual(doc["weeks"], [1])
        self.assertEqual([t["teamId"] for t in doc["teams"]], [1, 2])                                               # A wins 4 categories, B has more 3PM
        self.assertEqual(doc["categories"], ["FG%", "FT%", "3PTM", "PTS", "TO"])
        self.assertEqual(sum(1 for u in fx.urls if "week=2" in u and "matchup" in u), 1)                          # an empty week costs one page, not one per pair
        self.assertEqual(sum(1 for u in fx.urls if "week=1" in u and "matchup" in u), 2)                          # once for the weeks list, once for week 1 (page covers both teams)


if __name__ == "__main__":
    unittest.main()


class FetcherBehaviour(unittest.TestCase):
    """The HTTP layer, with a fake opener: retries, Retry-After, blocks, redirects to a sign-in, and the time-limited page copy."""

    class Resp:
        def __init__(self, body, url):
            self.body, self.url = body, url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body.encode()

        def geturl(self):
            return self.url

    def opener(self, *script):
        calls = []

        def open_(req, timeout=None):
            calls.append(req.full_url)
            step = script[min(len(calls) - 1, len(script) - 1)]
            if isinstance(step, Exception):
                raise step
            return self.Resp(step, req.full_url)
        return open_, calls

    def http(self, code, retry_after=None):
        import email.message
        import urllib.error
        h = email.message.Message()
        if retry_after is not None:
            h["Retry-After"] = str(retry_after)
        return urllib.error.HTTPError("http://x", code, "err", h, None)

    def fetcher(self, *script, cache=None):
        op, calls = self.opener(*script)
        sleeps = []
        return yr.Fetcher(delay=0, cache=cache, opener=op, sleep=sleeps.append), calls, sleeps

    def test_a_server_error_is_retried_and_then_succeeds(self):
        fx, calls, sleeps = self.fetcher(self.http(503), "<html>ok</html>")
        self.assertEqual(fx.get("http://x/a"), "<html>ok</html>")
        self.assertEqual(len(calls), 2)
        self.assertIn(yr.BACKOFF[0], sleeps)

    def test_a_rate_limit_waits_as_long_as_the_server_says_and_gives_up_after_the_retries(self):
        fx, calls, sleeps = self.fetcher(self.http(429, 3))
        with self.assertRaises(yr.RotoError) as cm:
            fx.get("http://x/a")
        self.assertEqual(len(calls), yr.RETRIES + 1)
        self.assertIn(3, sleeps)
        self.assertIn("rate limiting", str(cm.exception))

    def test_a_block_or_a_missing_page_is_not_retried(self):
        for code in (403, 404):
            fx, calls, _ = self.fetcher(self.http(code))
            with self.assertRaises(yr.RotoError):
                fx.get("http://x/a")
            self.assertEqual(len(calls), 1, code)

    def test_a_dropped_connection_is_retried_then_reported(self):
        import urllib.error
        fx, calls, _ = self.fetcher(urllib.error.URLError("timed out"))
        with self.assertRaises(yr.RotoError) as cm:
            fx.get("http://x/a")
        self.assertEqual(len(calls), yr.RETRIES + 1)
        self.assertIn("could not reach", str(cm.exception))

    def test_a_redirect_to_the_sign_in_page_is_a_clear_error(self):
        op, _ = self.opener("x")
        def to_login(req, timeout=None):
            return self.Resp("<html></html>", "https://login.yahoo.com/?.src=fantasy")
        fx = yr.Fetcher(delay=0, opener=to_login, sleep=lambda s: None)
        with self.assertRaises(yr.RotoError) as cm:
            fx.get("http://x/a")
        self.assertIn("not publicly viewable", str(cm.exception))

    def test_slow_changing_pages_are_copied_to_disk_for_a_limited_time(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fx, calls, _ = self.fetcher("one", "two", cache=d)
            self.assertEqual(fx.get("http://x/s", ttl=3600), "one")
            self.assertEqual(fx.get("http://x/s", ttl=3600), "one")               # served from disk
            self.assertEqual(len(calls), 1)
            p = fx._path("http://x/s")
            os.utime(p, (1, 1))                                                    # the copy is now ancient
            self.assertEqual(fx.get("http://x/s", ttl=3600), "two")
            self.assertEqual(fx.get("http://x/n"), "two")                          # no ttl: never copied, never read from disk
            self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Resilience(unittest.TestCase):
    def test_a_truncated_cache_file_is_a_miss_not_a_permanent_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wk = {"week": 1, "teams": {1: {"name": "A", "score": None, "cols": {"PTS": Fraction(30)}}}, "matchups": []}
            yr._cache_put(d, "9", wk)
            p = yr._cache_path(d, "9", 1)
            text = open(p).read()
            for broken in (text[:len(text) // 2], "", "[]", '{"v": 3}', '{"v": 3, "matchups": [], "teams": {"1": {"name": "A"}}}'):
                open(p, "w").write(broken)
                self.assertIsNone(yr._cache_get(d, "9", 1), broken[:20])
            yr._cache_put(d, "9", wk)
            self.assertEqual(yr._cache_get(d, "9", 1)["teams"][1]["cols"], {"PTS": Fraction(30)})

    def test_writes_are_atomic_and_leave_no_temp_files(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "f.json")
            yr.write_atomic(p, "one")
            yr.write_atomic(p, "two")
            with open(p) as f:
                self.assertEqual((f.read(), os.listdir(os.path.dirname(p))), ("two", ["f.json"]))

    def test_a_failing_recheck_does_not_stop_the_report_and_is_tried_again(self):
        import tempfile
        pages = AllPlayAndReport()._league("30")
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            with tempfile.TemporaryDirectory() as d:
                yr.load("9", d, 0, now=0, fixes=[])
                real_get = fx.get
                seen = []

                def boom(url, ttl=None):
                    if "week=1" in url:
                        seen.append(url)
                        if len(seen) > 1:                                          # the first look (the week list) works, the re-read of week 1 fails
                            raise yr.RotoError("HTTP 503")
                    return real_get(url, ttl)
                fx.get = boom
                fixes = []
                _, _, wd, _ = yr.load("9", d, 0, now=4000, fixes=fixes)            # the re-read of week 1 fails: the report still comes back
                self.assertEqual((fixes, wd[0]["teams"][1]["cols"]["PTS"]), ([], 30))
                self.assertEqual(yr._cache_get(d, "9", 1)["_meta"]["checks"], 0)   # and it does not count as a check
                fx.get = real_get
                yr.load("9", d, 0, now=4100, fixes=fixes)
                self.assertEqual(yr._cache_get(d, "9", 1)["_meta"]["checks"], 1)
        finally:
            yr.Fetcher = orig

    def test_the_league_id_must_be_digits(self):
        for bad in ("../x", "12 34", "", "1;rm", "abc"):
            with self.assertRaises(yr.RotoError):
                yr.check_league(bad)
        self.assertEqual(yr.check_league(85092), "85092")
        self.assertEqual(yr.main(["../etc"]), 2)

    def test_the_report_names_its_format_version(self):
        pages = AllPlayAndReport()._league("30")
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            doc = yr.report("9")
        finally:
            yr.Fetcher = orig
        self.assertEqual(doc["schemaVersion"], yr.SCHEMA_VERSION)


class CommandLine(unittest.TestCase):
    def run_main(self, argv):
        import contextlib
        import io
        pages = AllPlayAndReport()._league("30")
        fx, orig = Fake(pages), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = yr.main(argv)
        finally:
            yr.Fetcher = orig
        return code, out.getvalue(), err.getvalue()

    def test_json_output_lists_the_teams_with_their_roto(self):
        code, out, _ = self.run_main(["9", "--json"])
        doc = __import__("json").loads(out)
        self.assertEqual(code, 0)
        self.assertEqual([t["name"] for t in doc["teams"]][:1] and sorted(t["name"] for t in doc["teams"]), ["A", "B"])

    def test_the_text_table_is_the_default(self):
        code, out, _ = self.run_main(["9"])
        self.assertEqual(code, 0)
        self.assertIn("ROTO", out)

    def test_report_writes_a_self_contained_page_and_the_json(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self.run_main(["9", "--report", d])
            self.assertEqual(code, 0)
            self.assertEqual(sorted(os.listdir(d)), ["index.html", "report.json"])
            self.assertIn("window.__REPORT__=", open(os.path.join(d, "index.html"), encoding="utf-8").read())

    def test_a_bad_league_id_exits_with_status_2_and_a_message(self):
        code, _, err = self.run_main(["abc"])
        self.assertEqual(code, 2)
        self.assertIn("digits only", err)
