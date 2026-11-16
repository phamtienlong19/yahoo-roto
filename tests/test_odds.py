"""Playoff odds: reading the playoff setup, divisions and future pairings from the pages, and the rest-of-season simulation."""
import json
import math
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


def weeks_of(values_by_week, col="PTS", pairs=None):
    """Matchup-page style weeks for a one-category league: values_by_week = [{team: value}] per week; pairs = [[(a, b), ...]] per week (default: none)."""
    out = []
    for i, vals in enumerate(values_by_week, 1):
        out.append({"week": i, "teams": {t: {"name": str(t), "cols": {col: yr.Fraction(v)}, "score": None} for t, v in vals.items()}, "matchups": [list(p) for p in (pairs[i - 1] if pairs else [])]})
    return out


def rotation(ids, week):
    """A different pairing every week (everyone plays once)."""
    order = ids[:]
    order = order[week % len(order):] + order[:week % len(order)]
    return [(order[i], order[-1 - i]) for i in range(len(order) // 2)]


class StrengthUncertainty(unittest.TestCase):
    SPEC = [{"cat": "PTS", "kind": "count", "col": "PTS", "lower": False}]

    def test_shrinkage_and_standard_error_follow_the_leagues_own_spread(self):
        ids = [1, 2, 3, 4]
        weeks = weeks_of([{1: 110, 2: 100, 3: 90, 4: 100}, {1: 120, 2: 96, 3: 94, 4: 98}, {1: 100, 2: 104, 3: 86, 4: 102}])
        st = yr.strengths(weeks, self.SPEC, ids)["PTS"]
        avg = {1: 110.0, 2: 100.0, 3: 90.0, 4: 100.0}
        mu = sum(avg.values()) / 4
        sd2 = sum((x - avg[t]) ** 2 for wk in weeks for t, x in ((t, float(wk["teams"][t]["cols"]["PTS"])) for t in ids)) / (12 - 4)
        within = 0
        for t in ids:
            within += sum((float(wk["teams"][t]["cols"]["PTS"]) - avg[t]) ** 2 for wk in weeks)
        sd2 = within / (12 - 4)
        between = sum((avg[t] - mu) ** 2 for t in ids) / 3
        tau2 = max(between - sd2 / 3, 0.1 * between)
        w = tau2 / (tau2 + sd2 / 3)
        for t in ids:
            self.assertAlmostEqual(st["mean"][t], mu + w * (avg[t] - mu), places=9)
            self.assertAlmostEqual(st["se"][t], math.sqrt(w * sd2 / 3), places=9)
        self.assertAlmostEqual(st["sd"], math.sqrt(sd2), places=9)
        self.assertLess(abs(st["mean"][1] - mu), abs(avg[1] - mu))                                 # pulled toward the league average

    def test_with_many_weeks_the_estimates_stand_on_their_own(self):
        ids = [1, 2, 3, 4]
        base = {1: 120, 2: 105, 3: 95, 4: 80}
        weeks = weeks_of([{t: v + (-1) ** (i + t) * 3 for t, v in base.items()} for i in range(60)])
        st = yr.strengths(weeks, self.SPEC, ids)["PTS"]
        for t in ids:
            self.assertAlmostEqual(st["mean"][t], base[t], delta=1.0)                               # hardly shrunk after 60 weeks
            self.assertLess(st["se"][t], 1.0)                                                       # and sure of itself

    def test_no_se_means_no_uncertainty_and_the_old_fixed_pull_is_still_available(self):
        ids = [1, 2, 3, 4]
        weeks = weeks_of([{1: 110, 2: 100, 3: 90, 4: 100}, {1: 120, 2: 96, 3: 94, 4: 98}])
        old = yr.strengths(weeks, self.SPEC, ids, eb=False)["PTS"]
        self.assertEqual(set(old["se"].values()), {0.0})
        mu = sum(float(wk["teams"][t]["cols"]["PTS"]) for wk in weeks for t in ids) / 8
        self.assertAlmostEqual(old["mean"][1], (230 + yr.PRIOR_WEEKS * mu) / (2 + yr.PRIOR_WEEKS), places=9)

    def test_a_few_weeks_of_a_clear_leader_no_longer_look_certain(self):
        ids = list(range(1, 9))
        st = flat_strength(ids, mean={1: 106.0, 2: 94.0}, sd=10.0)
        sure = yr.simulate(st, ids, {t: 0.0 for t in ids}, [None] * 6, spots=3, sims=6000)
        for c in st.values():
            c["se"] = {t: 8.0 for t in ids}                                                          # the same strengths, but only a few weeks behind them
        unsure = yr.simulate(st, ids, {t: 0.0 for t in ids}, [None] * 6, spots=3, sims=6000)
        self.assertGreater(unsure[1]["playoff"], 0.7)                                               # still the favourite
        self.assertLess(unsure[1]["playoff"], sure[1]["playoff"] - 0.03)                            # but less sure
        self.assertGreater(unsure[2]["playoff"], sure[2]["playoff"])                                # and the weakest team gets a chance
        self.assertGreater(unsure[1]["first"], unsure[3]["first"])                                  # the order by strength is kept

    def test_the_run_is_repeatable_reports_its_noise_and_is_fast_enough(self):
        import time
        ids = list(range(1, 19))
        st = flat_strength(ids, mean={t: 100.0 + 2 * (t % 7) for t in ids}, cats=9, sd=10.0)
        for c in st.values():
            c["se"] = {t: 3.0 for t in ids}
        stats = {}
        t0 = time.time()
        a = yr.simulate(st, ids, {t: 0.0 for t in ids}, [None] * 15, spots=6, sims=50000, seed=4, stats=stats)
        self.assertLess(time.time() - t0, 12)                                                       # fifteen weeks left, fifty thousand seasons
        self.assertTrue(0 < stats["margin"] < 3, stats)
        self.assertEqual(a, yr.simulate(st, ids, {t: 0.0 for t in ids}, [None] * 15, spots=6, sims=50000, seed=4))
        self.assertAlmostEqual(sum(r["playoff"] for r in a.values()), 6, places=6)


class Backtest(unittest.TestCase):
    def test_counts_and_scores_match_an_independent_computation_on_the_golden_league(self):
        import itertools
        fx, orig = golden.FakeFetcher(golden.build_pages(18, 5, 7)), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            st0, teams, wd, _ = yr.load("9", None, 0, "nba")
        finally:
            yr.Fetcher = orig
        headers = list(next(iter(wd[0]["teams"].values()))["cols"])
        specs, _ = yr.plan(st0["categories"] or [h for h in headers if h and not h.endswith("M/A*")], headers)
        done = wd[:4]
        bt = yr.backtest(done, specs, sorted(teams))
        self.assertEqual(bt["games"], 3 * 9)                                                     # weeks 2-4, nine matchups each
        self.assertEqual([w["week"] for w in bt["weeks"]], [2, 3, 4])
        self.assertEqual(sum(b["games"] for b in bt["bins"]), bt["games"])
        self.assertTrue(0 < bt["brier"] < 1 and 0 <= bt["favouriteWon"] <= 1 and bt["baseline"] == 0.25)
        # independent: forecast week 3 from weeks 1-2 with the 512 win/loss patterns of nine categories
        ids = sorted(teams)
        st = yr.strengths(done[:2], specs, ids)
        wk = done[2]
        tot = yr.totals([wk], wk["teams"])
        brier = []
        for a, b in wk["matchups"]:
            ps = []
            for sp in specs:
                c = st[sp["cat"]]
                z = (c["mean"][a] - c["mean"][b]) / math.sqrt(2 * c["sd"] ** 2 + c["se"][a] ** 2 + c["se"][b] ** 2)
                ps.append(yr._phi(-z if c["lower"] else z))
            p = 0.0
            for pattern in itertools.product((0, 1), repeat=len(ps)):
                if sum(pattern) > len(ps) / 2:
                    q = 1.0
                    for won, pc in zip(pattern, ps):
                        q *= pc if won else 1 - pc
                    p += q
            res = yr.head_to_head(tot[a], tot[b], specs)
            y = 1.0 if res[0] > res[1] else 0.0 if res[0] < res[1] else 0.5
            if p < 0.5:
                p, y = 1 - p, 1 - y
            brier.append((p - y) ** 2)
        week3 = next(w for w in bt["weeks"] if w["week"] == 3)
        self.assertAlmostEqual(week3["brier"], sum(brier) / len(brier), places=3)

    def test_no_forecast_is_possible_from_a_single_week(self):
        weeks = weeks_of([{1: 100, 2: 90, 3: 80, 4: 70}], pairs=[[(1, 2), (3, 4)]])
        self.assertIsNone(yr.backtest(weeks, StrengthUncertainty.SPEC, [1, 2, 3, 4]))

    def test_when_strength_decides_matchups_the_favourites_win(self):
        ids = list(range(1, 9))
        weeks = weeks_of([{t: 100 + 15 * t + (3 if (t + w) % 2 else -3) for t in ids} for w in range(8)], pairs=[rotation(ids, w) for w in range(8)])
        bt = yr.backtest(weeks, StrengthUncertainty.SPEC, ids)
        self.assertEqual(bt["games"], 7 * 4)
        self.assertGreaterEqual(bt["favouriteWon"], 0.9)
        self.assertLess(bt["brier"], 0.25)                                                       # better than a coin flip

    def test_recent_weeks_count_more_only_when_that_forecasts_better(self):
        ids = list(range(1, 9))
        pairs = [rotation(ids, w) for w in range(14)]
        stable = weeks_of([{t: 100 + 8 * t + ((t * 7 + w * 3) % 5 - 2) * 4 for t in ids} for w in range(14)], pairs=pairs)
        flipped = weeks_of([{t: 100 + 8 * (t if w < 7 else 9 - t) + ((t * 7 + w * 3) % 5 - 2) * 4 for t in ids} for w in range(14)], pairs=pairs)
        self.assertEqual(yr.choose_half_life(stable[:4], StrengthUncertainty.SPEC, ids), (None, {}))      # too few weeks to tell
        hl, tested = yr.choose_half_life(flipped, StrengthUncertainty.SPEC, ids)
        self.assertIsNotNone(hl)                                                                  # teams changed: the recent weeks win
        self.assertLess(tested[str(int(hl))], tested["equal"])
        self.assertIsNone(yr.choose_half_life(stable, StrengthUncertainty.SPEC, ids)[0])           # steady teams: equal weights stay

    def test_equal_weights_are_the_default_and_a_half_life_favours_recent_weeks(self):
        ids = [1, 2]
        weeks = weeks_of([{1: 100, 2: 100}, {1: 100, 2: 100}, {1: 100, 2: 120}])
        eq = yr.strengths(weeks, StrengthUncertainty.SPEC, ids, eb=False)["PTS"]["mean"]
        recent = yr.strengths(weeks, StrengthUncertainty.SPEC, ids, half_life=1, eb=False)["PTS"]["mean"]
        self.assertGreater(recent[2], eq[2])                                                      # the latest week counts more

    def test_the_report_carries_accuracy_and_the_model_used(self):
        doc = golden.build_report(18, 5, regular=10)
        o = doc["odds"]
        self.assertEqual(o["accuracy"]["games"], 3 * 9)
        self.assertEqual(o["model"]["version"], 2)
        self.assertIsNone(o["model"]["halfLife"])                                                 # four finished weeks: equal weights
        self.assertIsNone(golden.build_report(18, 2, regular=10)["odds"]["accuracy"])             # a single finished week: nothing to forecast yet


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
            yr.simulate = lambda *a, **k: (sims.append("current" if "stats" in k else "history"), real(*a, **k))[1]
            try:
                golden.build_report(18, 5, regular=10, cache=d)
            finally:
                yr.simulate = real
            self.assertEqual(sims.count("current"), 1)                                                # the current odds, once
            self.assertEqual(sims.count("history"), 1)                                             # only the newly finished week: the earlier snapshots were remembered

    def test_the_history_is_repeatable(self):
        a = golden.build_report(18, 4, regular=10)["odds"]["history"]
        self.assertEqual(a, golden.build_report(18, 4, regular=10)["odds"]["history"])


class InTheReport(unittest.TestCase):
    def test_the_report_carries_odds_when_the_league_states_its_playoffs(self):
        with tempfile.TemporaryDirectory() as d:
            doc = golden.build_report(18, 4, regular=10, divisions=True, cache=d, fast=False)
            o = doc["odds"]
            self.assertEqual((o["spots"], o["regularWeeks"], o["remaining"]), (6, 10, [4, 5, 6, 7, 8, 9, 10]))
            self.assertTrue(o["divisionWinners"])
            self.assertEqual(sorted(o["divisions"]), ["East", "West"])
            self.assertAlmostEqual(sum(t["playoff"] for t in o["teams"].values()), 6, places=2)
            self.assertEqual(len(o["teams"]), 18)
            self.assertEqual(len(o["teams"]["1"]["dist"]), 18)
            self.assertEqual((o["sims"], o["scheduleWeeks"], o["complete"]), (50000, 7, True))     # the whole schedule is read in the first pass
            self.assertEqual(sorted(map(int, o["schedule"])), [4, 5, 6, 7, 8, 9, 10])                   # the pairings still to come travel with the report
            self.assertTrue(0 < o["margin"] < 3, o["margin"])                                         # the simulation noise, measured between batches (percentage points)
            self.assertEqual(o["model"]["version"], 2)
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
            yr.simulate = lambda *a, **k: (calls.append("current" if "stats" in k else "history"), real(*a, **k))[1]
            try:
                again = golden.build_report(18, 4, regular=10, cache=d)["odds"]
                self.assertEqual((again, calls), (first, []))                                       # same data: no simulation
                golden.build_report(18, 5, regular=10, cache=d)
                self.assertEqual(calls.count("current"), 1)                                           # one more week finished: the odds are simulated again
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
