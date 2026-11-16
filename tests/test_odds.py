"""Playoff odds: reading the playoff setup, divisions and future pairings from the pages, and the rest-of-season simulation."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import golden  # noqa: E402
import yahoo_roto as yr  # noqa: E402


def flat_strength(ids, cats=9, mean=None, sd=10.0):
    """Every team equally strong in every category unless `mean` ({team: value}) says otherwise."""
    return {"C%d" % i: {"mean": {t: (mean or {}).get(t, 100.0) for t in ids}, "sd": sd, "lower": False} for i in range(cats)}


class Settings(unittest.TestCase):
    TEXT = ("<html><body>League Name: L League Logo: x Scoring Type: Head-to-Head - Categories Make League Publicly Viewable: Yes Playoffs: 6 teams - Week 19, 20 and 21 (ends Sunday, Mar 28) "
            "Playoff Tie-Breaker: Best regular season record vs opponent wins Divisions: Yes (2 divisions) Playoff Seeding Options: Division winners advance but seeded by overall standings "
            "Lock Benched Players: No Stat Categories: Points (PTS) Roster Positions: PG</body></html>")

    def test_the_playoff_setup_is_read_from_the_settings_page(self):
        st = yr.parse_settings(self.TEXT)
        self.assertEqual((st["playoff_teams"], st["playoff_start"], st["div_winners"]), (6, 19, True))

    def test_a_league_without_that_text_has_no_playoff_setup(self):
        st = yr.parse_settings("<html><body>Scoring Type: Head-to-Head - Categories Make League Publicly Viewable: Yes</body></html>")
        self.assertEqual((st["playoff_teams"], st["playoff_start"], st["div_winners"]), (None, None, False))

    def test_divisions_are_the_headings_above_the_team_rows(self):
        html = ('<table><tr><th>Team</th></tr><tr><td><h4>East</h4></td></tr><tr><td><a href="/nba/9/1">A</a></td></tr><tr><td><a href="/nba/9/2">B</a></td></tr>'
                '<tr><td><h4 class="x">West</h4></td></tr><tr><td><a href="/nba/9/3">C</a></td></tr></table>')
        self.assertEqual(yr.parse_divisions(html, 9), {1: "East", 2: "East", 3: "West"})
        self.assertEqual(yr.parse_divisions("<table><tr><td><a href=\"/nba/9/1\">A</a></td></tr></table>", 9), {})


class Schedule(unittest.TestCase):
    def setUp(self):
        self.n = 18
        self.fx = golden.FakeFetcher(golden.build_pages(self.n, 3, regular=10))
        self.ids = list(range(1, self.n + 1))
        self.base = "https://x/nba/9"

    def test_pairings_are_read_remembered_and_not_fetched_again(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            get = self.fx.get
            self.fx.get = lambda url, ttl=None: (calls.append(url), get(url, ttl))[1]
            got = yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4, 5, 6], d, 1000, budget=100)
            self.assertEqual(sorted(got), [4, 5, 6])
            for w, pairs in got.items():
                self.assertEqual(sorted(t for p in pairs for t in p), self.ids)       # everyone plays exactly once
            self.assertEqual(len(calls), 3 * self.n // 2)                              # one page per matchup, not per team
            again = yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4, 5, 6], d, 2000, budget=100)
            self.assertEqual(again, got)
            self.assertEqual(len(calls), 3 * self.n // 2)                              # remembered
            yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4], d, 1000 + yr.SCHEDULE_REFRESH + 1, budget=100)
            self.assertEqual(len(calls), 3 * self.n // 2 + self.n // 2)                # a day later one week is read again

    def test_the_page_budget_is_spent_on_whole_weeks_and_a_failure_only_means_fewer_weeks(self):
        with tempfile.TemporaryDirectory() as d:
            got = yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4, 5, 6, 7], d, 1000, budget=20)
            self.assertEqual(sorted(got), [4, 5])                                      # 9 pages a week: two weeks fit in 20
            broken = golden.FakeFetcher({"settings": "x"})                             # every page raises
            self.assertEqual(yr.fetch_schedule(broken, "9", self.base, self.ids, [8], d, 1000, budget=100), {})

    def test_known_weeks_are_refreshed_a_couple_at_a_time(self):
        with tempfile.TemporaryDirectory() as d:
            yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4, 5, 6, 7], d, 1000)
            calls = []
            get = self.fx.get
            self.fx.get = lambda url, ttl=None: (calls.append(url), get(url, ttl))[1]
            yr.fetch_schedule(self.fx, "9", self.base, self.ids, [4, 5, 6, 7], d, 1000 + yr.SCHEDULE_REFRESH + 1)
            self.assertEqual(len(calls), 2 * self.n // 2)                                           # two weeks of the four, not all of them

    def test_a_damaged_schedule_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "9-schedule.json"), "w") as f:
                f.write("{not json")
            self.assertEqual(yr.load_schedule(d, "9"), {})


class Simulation(unittest.TestCase):
    ids = list(range(1, 9))

    def run_sim(self, points=None, remaining=None, **kw):
        points = points or {t: 0.0 for t in self.ids}
        remaining = remaining if remaining is not None else [None] * 6
        return yr.simulate(flat_strength(self.ids), self.ids, points, remaining, spots=kw.pop("spots", 4), sims=kw.pop("sims", 3000), **kw)

    def test_places_and_playoff_spots_are_all_handed_out(self):
        res = self.run_sim()
        self.assertAlmostEqual(sum(r["playoff"] for r in res.values()), 4, places=6)
        self.assertAlmostEqual(sum(r["first"] for r in res.values()), 1, places=6)
        for r in res.values():
            self.assertAlmostEqual(sum(r["dist"]), 1, places=6)
        for k in range(len(self.ids)):
            self.assertAlmostEqual(sum(r["dist"][k] for r in res.values()), 1, places=6)   # each place goes to exactly one team

    def test_equally_strong_teams_have_equal_odds_and_the_run_is_repeatable(self):
        res = self.run_sim(sims=6000)
        for r in res.values():
            self.assertAlmostEqual(r["playoff"], 0.5, delta=0.04)
        self.assertEqual(self.run_sim(seed=5), self.run_sim(seed=5))

    def test_a_clinched_lead_and_a_dead_end_are_certain(self):
        points = {t: 50.0 for t in self.ids}
        points[1], points[2] = 500.0, -500.0
        res = yr.simulate(flat_strength(self.ids), self.ids, points, [None], spots=4, sims=500)
        self.assertEqual((res[1]["playoff"], res[1]["first"]), (1.0, 1.0))
        self.assertEqual(res[2]["playoff"], 0.0)

    def test_a_stronger_team_does_better_and_the_remaining_weeks_matter(self):
        st = flat_strength(self.ids, mean={1: 140.0, 2: 60.0})
        res = yr.simulate(st, self.ids, {t: 0.0 for t in self.ids}, [None] * 6, spots=4, sims=3000)
        self.assertGreater(res[1]["playoff"], 0.9)
        self.assertLess(res[2]["playoff"], 0.1)
        none_left = yr.simulate(st, self.ids, {t: float(t) for t in self.ids}, [], spots=4, sims=200)
        self.assertEqual([t for t in self.ids if none_left[t]["playoff"] == 1.0], [5, 6, 7, 8])   # nothing left to play: the standings are the answer

    def test_division_leaders_advance_even_from_a_weaker_record(self):
        divisions = {1: "East", 2: "East", 3: "East", 4: "East", 5: "West", 6: "West", 7: "West", 8: "West"}
        points = {1: 90.0, 2: 80.0, 3: 70.0, 4: 60.0, 5: 20.0, 6: 10.0, 7: 5.0, 8: 0.0}       # West is far behind; its best team (5) still leads the West
        plain = yr.simulate(flat_strength(self.ids), self.ids, points, [], spots=4, sims=200)
        with_divs = yr.simulate(flat_strength(self.ids), self.ids, points, [], divisions=divisions, spots=4, div_winners=True, sims=200)
        self.assertEqual(plain[5]["playoff"], 0.0)
        self.assertEqual(with_divs[5]["playoff"], 1.0)
        self.assertEqual(with_divs[4]["playoff"], 0.0)                                        # the 4th East team is the one left out


class Accuracy(unittest.TestCase):
    def test_the_simulation_agrees_with_an_exact_calculation_on_a_small_league(self):
        ids = [1, 2, 3, 4]
        st = flat_strength(ids, cats=5, mean={1: 112.0, 2: 104.0, 3: 96.0, 4: 90.0}, sd=12.0)
        points = {1: 20.0, 2: 21.0, 3: 22.5, 4: 19.0}
        weeks = [[(1, 2), (3, 4)], [(1, 3), (2, 4)]]
        import itertools
        exact = {t: 0.0 for t in ids}
        dists = {}
        for w in weeks:
            for a, b in w:
                dists[(a, b)] = yr.cat_win_distribution(a, b, st)
        outcomes = [(wk, a, b) for wk in range(2) for a, b in weeks[wk]]
        for ks in itertools.product(range(6), repeat=len(outcomes)):
            pr = 1.0
            pts = dict(points)
            for k, (wk, a, b) in zip(ks, outcomes):
                pr *= dists[(a, b)][k]
                pts[a] += k
                pts[b] += 5 - k
            for t in ids:
                g = sum(1 for o in ids if pts[o] > pts[t])
                e = sum(1 for o in ids if o != t and pts[o] == pts[t])
                exact[t] += pr * (0.0 if g >= 2 else 1.0 if g + e + 1 <= 2 else (2 - g) / (e + 1))
        res = yr.simulate(st, ids, points, weeks, spots=2, sims=60000, seed=3)
        for t in ids:
            self.assertAlmostEqual(res[t]["playoff"], exact[t], delta=0.012, msg="team %d" % t)


class History(unittest.TestCase):
    def test_the_odds_after_each_finished_week_are_kept_and_end_where_the_odds_are_now(self):
        with tempfile.TemporaryDirectory() as d:
            doc = golden.build_report(18, 5, regular=10, cache=d)
            o = doc["odds"]
            self.assertEqual([h["week"] for h in o["history"]], [1, 2, 3, 4])                       # a snapshot after each finished week
            for h in o["history"]:
                self.assertAlmostEqual(sum(h["teams"].values()), 6, places=1)                        # the playoff places are always handed out
            last = o["history"][-1]["teams"]
            for t, v in o["teams"].items():
                self.assertAlmostEqual(last[t], v["playoff"], delta=0.06)                            # the last snapshot is the current odds (fewer seasons)
            self.assertTrue(os.path.exists(os.path.join(d, "9-odds-history.json")))

    def test_each_week_is_simulated_once_and_only_a_changed_week_again(self):
        with tempfile.TemporaryDirectory() as d:
            golden.build_report(18, 4, regular=10, cache=d)
            real, sims = yr.simulate, []
            yr.simulate = lambda *a, **k: (sims.append(k.get("sims", yr.SIMS)), real(*a, **k))[1]
            try:
                golden.build_report(18, 5, regular=10, cache=d)
            finally:
                yr.simulate = real
            self.assertEqual(sims.count(yr.SIMS), 1)                                                  # the current odds, once
            self.assertEqual(sims.count(yr.HIST_SIMS), 1)                                             # only the newly finished week: the earlier snapshots were remembered

    def test_the_history_is_repeatable(self):
        a = golden.build_report(18, 4, regular=10)["odds"]["history"]
        self.assertEqual(a, golden.build_report(18, 4, regular=10)["odds"]["history"])


class InTheReport(unittest.TestCase):
    def test_the_report_carries_odds_when_the_league_states_its_playoffs(self):
        with tempfile.TemporaryDirectory() as d:
            doc = golden.build_report(18, 4, regular=10, divisions=True, cache=d)
            o = doc["odds"]
            self.assertEqual((o["spots"], o["regularWeeks"], o["remaining"]), (6, 10, [4, 5, 6, 7, 8, 9, 10]))
            self.assertTrue(o["divisionWinners"])
            self.assertEqual(sorted(o["divisions"]), ["East", "West"])
            self.assertAlmostEqual(sum(t["playoff"] for t in o["teams"].values()), 6, places=2)
            self.assertEqual(len(o["teams"]), 18)
            self.assertEqual(len(o["teams"]["1"]["dist"]), 18)
            self.assertEqual((o["sims"], o["scheduleWeeks"], o["complete"]), (50000, 7, True))     # the whole schedule is read in the first pass
            self.assertEqual(sorted(map(int, o["schedule"])), [4, 5, 6, 7, 8, 9, 10])                   # the pairings still to come travel with the report
            self.assertAlmostEqual(o["margin"], 0.44, places=2)
            with open(os.path.join(d, "9-schedule.json")) as f:
                self.assertEqual(len(json.load(f)), 6)                                              # the pairings of the six future weeks were remembered

    def test_a_week_that_cannot_be_read_leaves_the_odds_incomplete_not_missing(self):
        doc = golden.build_report(18, 4, regular=10, drop=(9, 10))
        o = doc["odds"]
        self.assertEqual((o["scheduleWeeks"], o["complete"]), (5, False))
        self.assertAlmostEqual(sum(t["playoff"] for t in o["teams"].values()), 6, places=2)

    def test_unchanged_inputs_reuse_the_saved_answer_and_a_change_recomputes(self):
        with tempfile.TemporaryDirectory() as d:
            first = golden.build_report(18, 4, regular=10, cache=d)["odds"]
            real = yr.simulate
            calls = []
            yr.simulate = lambda *a, **k: (calls.append(k.get("sims", yr.SIMS)), real(*a, **k))[1]
            try:
                again = golden.build_report(18, 4, regular=10, cache=d)["odds"]
                self.assertEqual((again, calls), (first, []))                                       # same data: no simulation
                golden.build_report(18, 5, regular=10, cache=d)
                self.assertEqual(calls.count(yr.SIMS), 1)                                           # one more week finished: the odds are simulated again
            finally:
                yr.simulate = real

    def test_a_league_without_playoff_text_has_no_odds(self):
        self.assertIsNone(golden.build_report(18, 4)["odds"])
        self.assertIsNone(golden.build_report(18, 1, regular=10)["odds"])                      # no week has finished yet

    def test_the_same_data_gives_the_same_odds(self):
        a = golden.build_report(18, 4, regular=10)["odds"]
        b = golden.build_report(18, 4, regular=10)["odds"]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
