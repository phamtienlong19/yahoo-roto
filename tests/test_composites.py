"""Score / matchup parsing, Win%, ordering, and the season composites, checked against a 4-team, 2-category, 2-week league worked out by hand."""
import os
import sys
import unittest
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import yahoo_roto as yr  # noqa: E402
from test_yahoo_roto import SETTINGS, Fake  # noqa: E402

SPECS = [{"cat": "PTS", "kind": "count", "col": "PTS", "lower": False}, {"cat": "TO", "kind": "count", "col": "TO", "lower": True}]
IDS = [1, 2, 3, 4]


def wk(n, vals, scores, pairs):
    return {"week": n, "matchups": pairs, "teams": {t: {"name": "T%d" % t, "score": F(scores[t]), "cols": {"PTS": F(v[0]), "TO": F(v[1])}} for t, v in vals.items()}}


W1 = wk(1, {1: (30, 5), 2: (20, 9), 3: (30, 9), 4: (10, 1)}, {1: 2, 2: 0, 3: 1, 4: 1}, [[1, 2], [3, 4]])
W2 = wk(2, {1: (10, 9), 2: (40, 1), 3: (20, 5), 4: (15, 5)}, {1: 0, 2: 2, 3: 2, 4: 0}, [[1, 3], [2, 4]])


def build():
    weeks = [W1, W2]
    cores = [yr._core(w, SPECS) for w in weeks]
    season = yr._season_view(cores, weeks, SPECS, IDS)
    return weeks, cores, season, yr.composites(weeks, cores, SPECS, IDS, season)


class Parsing(unittest.TestCase):
    def page(self, week=1):
        opts = '<select><option value="x?module=matchup&week=1" selected>1</option></select>'
        row = '<tr><td><a href="/nba/9/%d">%s</a></td><td>5/10</td><td>.500</td><td>3/4</td><td>.750</td><td>4</td><td>30</td><td>2</td><td>%s</td></tr>'
        return (opts + "<table><tr><th>Team</th><th>FGM/A*</th><th>FG%</th><th>FTM/A*</th><th>FT%</th><th>3PTM</th><th>PTS</th><th>TO</th><th></th></tr>"
                + row % (7, "Seven", "6") + row % (3, "Three", "-") + "</table>")

    def test_score_is_the_last_unnamed_column_and_the_pair_is_who_played(self):
        w = yr.parse_week(self.page(), 9)
        self.assertEqual(w["teams"][7]["score"], 6)
        self.assertIsNone(w["teams"][3]["score"])                     # '-' = nothing yet
        self.assertEqual(w["pair"], [7, 3])
        self.assertNotIn("", w["teams"][7]["cols"])                   # Score is not a category column

    def test_cache_keeps_score_and_matchups_and_drops_old_files(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            yr._cache_put(d, "9", W1)
            back = yr._cache_get(d, "9", 1)
            self.assertEqual(back["matchups"], [[1, 2], [3, 4]])
            self.assertEqual(back["teams"][3]["score"], 1)
            with open(os.path.join(d, "9-week-2.json"), "w") as f:     # a file written before Score existed
                json.dump({"1": {"name": "A", "cols": {}}}, f)
            self.assertIsNone(yr._cache_get(d, "9", 2))


class WeekViews(unittest.TestCase):
    def test_win_pct_counts_a_tie_as_half(self):
        self.assertEqual(yr.win_pct([2, 0, 1]), F(5, 6))
        self.assertEqual(yr.win_pct([0, 0, 3]), F(1, 2))
        self.assertIsNone(yr.win_pct([0, 0, 0]))

    def test_competition_rank_shares_and_skips(self):
        self.assertEqual(yr.comp_rank({"a": 5, "b": 3, "c": 3, "d": 1}), {"a": 1, "b": 2, "c": 2, "d": 4})
        self.assertEqual(yr.comp_rank({"a": 5, "b": 3, "c": 3}, high=False), {"a": 3, "b": 1, "c": 1})

    def test_week_one_roto_allplay_score_and_matchups(self):
        _, cores, _, _ = build()
        v = yr._week_view(cores[0], W1, SPECS, IDS)
        self.assertEqual([v["teams"][str(t)]["total"] for t in IDS], [6.5, 3.5, 5.0, 5.0])
        self.assertEqual([v["teams"][str(t)]["rank"] for t in IDS], [1, 4, 2, 2])           # ties share a rank
        self.assertEqual([v["teams"][str(t)]["allPlay"] for t in IDS], [[2, 0, 1], [0, 2, 1], [1, 1, 1], [0, 0, 3]])
        self.assertAlmostEqual(v["teams"]["1"]["winPct"], 5 / 6)
        self.assertEqual([v["teams"][str(t)]["score"] for t in IDS], [2, 0, 1, 1])
        self.assertEqual(v["matchups"], [[1, 2], [3, 4]])
        self.assertNotIn("catDiff", str(v))

    def test_ordering_roto_by_total_allplay_by_winpct_then_total(self):
        _, cores, _, _ = build()
        v = yr._week_view(cores[0], W1, SPECS, IDS)
        self.assertEqual(v["order"], [1, 3, 4, 2])                      # 6.5, 5.0, 5.0 (id order), 3.5
        self.assertEqual(v["allPlayOrder"], [1, 3, 4, 2])               # Win% .833, .5, .5 (same roto total, id order), .167
        w2 = yr._week_view(cores[1], W2, SPECS, IDS)
        self.assertEqual(w2["order"], [2, 3, 4, 1])
        self.assertEqual(w2["allPlayOrder"], [2, 3, 4, 1])
        # a team with a better roto total but a lower Win% sorts below in all-play
        res = {1: {"total": 9.0}, 2: {"total": 5.0}}
        ro, ap = yr._orders([1, 2], res, {1: [1, 1, 0], 2: [2, 0, 0]})
        self.assertEqual((ro, ap), ([1, 2], [2, 1]))


class Season(unittest.TestCase):
    def test_season_view_sums_weekly_records_and_has_no_score_or_matchups(self):
        _, _, season, _ = build()
        self.assertEqual({t: season["teams"][str(t)]["total"] for t in IDS}, {1: 3.5, 2: 7.0, 3: 4.5, 4: 5.0})      # roto of the summed totals
        self.assertEqual([season["teams"][str(t)]["rank"] for t in IDS], [4, 1, 3, 2])
        self.assertEqual([season["teams"][str(t)]["allPlay"] for t in IDS], [[2, 3, 1], [3, 2, 1], [3, 2, 1], [1, 2, 3]])
        self.assertEqual(season["matrix"]["1"]["2"], [2, 2, 0])         # cell = category records added over both weeks
        self.assertNotIn("score", season["teams"]["1"])
        self.assertNotIn("matchups", season)

    def test_per_team_per_week_facts(self):
        _, _, _, c = build()
        w = c["weekly"]["3"]["1"]
        self.assertEqual((w["total"], w["rank"], w["allPlay"], w["score"], w["opp"], w["result"]), (5.0, 2, [1, 1, 1], 1, 4, "T"))
        self.assertEqual(w["points"], {"PTS": 3.5, "TO": 1.5})
        self.assertEqual(c["weekly"]["1"]["2"]["result"], "L")

    def test_weekly_roto_points_sum_average_and_rank_strip(self):
        _, _, _, c = build()
        r = c["weeklyRoto"]
        self.assertEqual([r[str(t)]["sum"] for t in IDS], [8.5, 11.5, 10.5, 9.5])
        self.assertEqual(r["2"]["avg"], 5.75)
        self.assertEqual([r[str(t)]["rank"] for t in IDS], [4, 1, 2, 3])
        self.assertEqual(r["1"]["weekRanks"], [1, 4])

    def test_season_all_play_ranks_with_ties(self):
        _, _, _, c = build()
        a = c["seasonAllPlay"]
        self.assertEqual([a[str(t)]["rank"] for t in IDS], [3, 1, 1, 3])
        self.assertAlmostEqual(a["2"]["winPct"], 3.5 / 6)

    def test_real_record_expected_wins_and_luck(self):
        _, _, _, c = build()
        r = c["realRecord"]
        self.assertEqual([r[str(t)]["record"] for t in IDS], [[1, 1, 0], [1, 1, 0], [1, 0, 1], [0, 1, 1]])
        self.assertAlmostEqual(r["1"]["expectedWins"], 5 / 6)
        self.assertAlmostEqual(r["1"]["luck"], 1 / 6)                   # 1 real win - 5/6 expected
        self.assertAlmostEqual(r["2"]["luck"], -1 / 6)
        self.assertAlmostEqual(r["3"]["luck"], 1 / 3)                   # 1 win + a tied matchup (half) = 1.5, expected 7/6
        self.assertAlmostEqual(r["4"]["luck"], -1 / 3)
        self.assertEqual([r[str(t)]["rank"] for t in IDS], [2, 2, 1, 4])
        self.assertAlmostEqual(sum(r[str(t)]["luck"] for t in IDS), 0)  # luck is zero-sum here

    def test_category_kings_season_and_best_week(self):
        _, _, _, c = build()
        k = c["categoryKings"]
        self.assertEqual((k["PTS"]["season"]["team"], k["PTS"]["season"]["value"]), (2, 60))
        self.assertEqual((k["PTS"]["week"]["team"], k["PTS"]["week"]["week"], k["PTS"]["week"]["value"]), (2, 2, 40))
        self.assertEqual((k["TO"]["season"]["team"], k["TO"]["season"]["value"]), (4, 6))      # fewer is better
        self.assertEqual((k["TO"]["week"]["team"], k["TO"]["week"]["week"]), (4, 1))
        self.assertEqual(k["TO"]["week"]["also"], [[2, 2]])                                    # team 2 also had 1 TO, in week 2

    def test_boom_bust_and_consistency(self):
        _, _, _, c = build()
        b = c["boomBust"]
        self.assertEqual((b["1"]["best"], b["1"]["worst"]), ({"week": 1, "total": 6.5}, {"week": 2, "total": 2.0}))
        self.assertAlmostEqual(b["1"]["stdev"], 2.25)
        self.assertAlmostEqual(b["3"]["stdev"], 0.25)
        self.assertEqual([b[str(t)]["rank"] for t in IDS], [3, 3, 1, 1])                       # steadier = better, ties share

    def test_power_rank_is_the_plain_average_of_the_component_ranks(self):
        _, _, _, c = build()
        p = c["power"]
        self.assertEqual(p["1"]["ranks"], {"seasonRoto": 4, "weeklyRoto": 4, "seasonAllPlay": 3, "realRecord": 2})
        self.assertEqual([p[str(t)]["avg"] for t in IDS], [3.25, 1.25, 1.75, 3.0])
        self.assertEqual([p[str(t)]["rank"] for t in IDS], [4, 1, 2, 3])

    def test_a_single_week_has_zero_spread(self):
        weeks = [W1]
        cores = [yr._core(W1, SPECS)]
        season = yr._season_view(cores, weeks, SPECS, IDS)
        c = yr.composites(weeks, cores, SPECS, IDS, season)
        self.assertEqual(c["boomBust"]["1"]["stdev"], 0)


class Shape(unittest.TestCase):
    def test_report_json_shape_and_the_season_has_no_score(self):
        row = '<tr><td><a href="/nba/9/%d">%s</a></td><td>5/10</td><td>.5</td><td>3/4</td><td>.75</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        def page(w, a, b):
            opts = "".join('<option value="x?module=matchup&week=%d"%s>%d</option>' % (n, " selected" if n == w else "", n) for n in (1, 2, 3))
            if w == 3:
                row_ = row.replace("5/10", "-/-").replace("3/4", "-/-").replace(".5<", "-<").replace(".75<", "-<")
            else:
                row_ = row
            return ("<select>" + opts + "</select><table><tr><th>Team</th><th>FGM/A*</th><th>FG%</th><th>FTM/A*</th><th>FT%</th><th>3PTM</th><th>PTS</th><th>TO</th><th></th></tr>"
                    + row_ % ((1, "A") + a) + row_ % ((2, "B") + b) + "</table>")
        pages = {"settings": SETTINGS, "lhst=stand": '<table><tr><th>Team</th></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr></table>',
                 "week=1": page(1, ("4", "30", "2", "1"), ("6", "25", "5", "0")), "week=2": page(2, ("1", "10", "2", "0"), ("2", "40", "1", "2")),
                 "week=3": page(3, ("-", "-", "-", "-"), ("-", "-", "-", "-"))}
        fx = Fake(pages)
        orig = yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            doc = yr.report("9")
        finally:
            yr.Fetcher = orig
        self.assertEqual(doc["schema"], "yahoo-roto-report/2")
        self.assertEqual(sorted(doc["views"]), ["season", "w1", "w2"])
        self.assertEqual(sorted(doc["composites"]), ["boomBust", "categoryKings", "power", "realRecord", "seasonAllPlay", "seasonRoto", "weekly", "weeklyRoto", "weeks"])
        w1 = doc["views"]["w1"]
        self.assertEqual(w1["matchups"], [[1, 2]])
        self.assertEqual((w1["teams"]["1"]["score"], w1["teams"]["2"]["score"]), (1, 0))
        self.assertEqual(sorted(w1["teams"]["1"]), ["allPlay", "points", "rank", "score", "total", "values", "winPct"])
        self.assertEqual(sorted(doc["views"]["season"]["teams"]["1"]), ["allPlay", "points", "rank", "total", "values", "winPct"])
        self.assertEqual(doc["composites"]["realRecord"]["1"]["record"], [1, 1, 0])
        import json
        json.dumps(doc)                                              # serialisable


if __name__ == "__main__":
    unittest.main()
