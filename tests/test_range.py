"""The page rebuilds the season boards for any range of weeks (RotoPure.range). The Python report is the reference: for the same weeks both must give the same numbers."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import golden  # noqa: E402
import yahoo_roto as yr  # noqa: E402

PAGE = os.path.join(HERE, "..", "index.html")


def js_range(doc, spans):
    with open(PAGE, encoding="utf-8") as f:
        src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "doc.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify(%s.map(function(s){var ws=d.weeks.filter(function(w){return w>=s[0]&&w<=s[1];});return RotoPure.range(d,ws);})))" % (path, json.dumps(spans))
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def python_range(first, last, n=18, weeks=4, seed=7):
    """The reference: the report's own season view and composites over only those weeks (rebuilt with the real pipeline)."""
    fx, orig = golden.FakeFetcher(golden.build_pages(n, weeks, seed)), yr.Fetcher
    yr.Fetcher = lambda **k: fx
    try:
        st, teams, wd, _ = yr.load("9", None, 0, "nba")
    finally:
        yr.Fetcher = orig
    headers = list(next(iter(wd[0]["teams"].values()))["cols"])
    specs, _ = yr.plan(st["categories"] or [h for h in headers if h and not h.endswith("M/A*")], headers)
    wd = [w for w in wd if first <= w["week"] <= last]
    ids = sorted(teams)
    cores = [yr._core(w, specs) for w in wd]
    season = yr._season_view(cores, wd, specs, ids)
    return season, yr.composites(wd, cores, specs, ids, season)


def same(a, b, path=""):
    """Equal up to float noise; dict keys compare as text (JSON turns ids into strings)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and {str(k) for k in a} == {str(k) for k in b}, "%s: keys %s vs %s" % (path, sorted(map(str, a)), sorted(map(str, b)))
        for k in a:
            same(a[k], b[str(k)] if str(k) in b else b[k], path + "/" + str(k))
    elif isinstance(a, (list, tuple)):
        assert isinstance(b, (list, tuple)) and len(a) == len(b), "%s: %r vs %r" % (path, a, b)
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, "%s[%d]" % (path, i))
    elif isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)):
        assert abs(a - b) < 1e-7, "%s: %r vs %r" % (path, a, b)
    else:
        assert a == b, "%s: %r vs %r" % (path, a, b)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RangeParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = golden.build_report(18, 4)

    def check(self, spans):
        for (a, b), got in zip(spans, js_range(self.doc, spans)):
            season, comp = python_range(a, b)
            ref_view = json.loads(json.dumps(season))
            same(ref_view, got["view"], "view %d-%d" % (a, b))
            same(json.loads(json.dumps(comp)), got["comp"], "comp %d-%d" % (a, b))

    def test_the_whole_season_and_the_final_weeks_match_what_the_report_ships(self):
        got = js_range(self.doc, [[1, 4], [1, 3]])
        same(self.doc["views"]["season"], got[0]["view"], "season")
        same(self.doc["composites"], got[0]["comp"], "composites")
        same(self.doc["views"]["seasonFinal"], got[1]["view"], "seasonFinal")
        same(self.doc["compositesFinal"], got[1]["comp"], "compositesFinal")

    def test_other_ranges_match_a_report_built_from_just_those_weeks(self):
        self.check([[2, 3], [3, 4], [2, 4], [4, 4], [1, 2]])

    def test_category_luck_by_week_adds_up_to_the_season_figure_and_is_zero_sum(self):
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(self.doc, f)
            code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify(d.weeks.map(function(w){return RotoPure.catLuckWeek(d,w)})))" % path
            out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        per_week = json.loads(out.stdout)
        cats = [c["cat"] for c in self.doc["categories"]]
        for w, week in zip(self.doc["weeks"], per_week):
            for c in cats:
                self.assertAlmostEqual(sum(t[c][0] - t[c][1] for t in week.values()), 0, places=6, msg="week %d %s" % (w, c))
        for t, ref in self.doc["composites"]["catLuck"].items():
            for c in cats:
                self.assertAlmostEqual(sum(wk[t][c][0] - wk[t][c][1] for wk in per_week), ref["byCat"][c]["diff"], places=6)

    def test_category_luck_skips_a_category_some_team_has_no_value_for(self):
        import copy
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        doc = copy.deepcopy(self.doc)
        cat = doc["categories"][0]["cat"]
        w = doc["weeks"][-1]
        doc["views"]["w%d" % w]["teams"][next(iter(doc["teams"]))]["values"][cat] = None      # e.g. a team with no FT attempts yet
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(doc, f)
            code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify(RotoPure.catLuckWeek(d,%d)))" % (path, w)
            out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        week = json.loads(out.stdout)
        self.assertTrue(all(t[cat] == [0, 0] for t in week.values()))                      # neither the real nor the expected win counts
        other = doc["categories"][1]["cat"]
        self.assertAlmostEqual(sum(t[other][0] - t[other][1] for t in week.values()), 0, places=6)

    def test_strength_of_schedule_is_the_opponents_real_record(self):
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(self.doc, f)
            code = src + ("\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify([RotoPure.sos(d,[1,2,3,4],'matchups'),RotoPure.sos(d,[2,3],'matchups'),"
                          "RotoPure.sos(d,[1,2,3,4],'cats'),RotoPure.sos(d,[2,3],'cats')]))" % path)
            out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        fx, orig = golden.FakeFetcher(golden.build_pages(18, 4, 7)), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            st, teams, wd, _ = yr.load("9", None, 0, "nba")
        finally:
            yr.Fetcher = orig
        headers = list(next(iter(wd[0]["teams"].values()))["cols"])
        specs, _ = yr.plan(st["categories"] or [h for h in headers if h and not h.endswith("M/A*")], headers)

        def ref(weeks, basis):
            """From the raw matchup pages: every team's games (week -> opponent and result as [W, L, T] of matchups or of categories)."""
            games = {t: {} for t in teams}
            for w in wd:
                tot = yr.totals([w], w["teams"])
                for x, y in w["matchups"]:
                    for t, o in ((x, y), (y, x)):
                        if basis == "cats":
                            games[t][w["week"]] = (o, yr.head_to_head(tot[t], tot[o], specs))
                        else:
                            sc, osc = w["teams"][t]["score"], w["teams"][o]["score"]
                            games[t][w["week"]] = (o, [1, 0, 0] if sc > osc else [0, 1, 0] if sc < osc else [0, 0, 1])
            res = {}
            for t in teams:
                rec = [0, 0, 0]
                for wk in weeks:
                    o = games[t][wk][0]
                    for wk2 in weeks:
                        r = games[o][wk2][1]
                        rec = [a + b for a, b in zip(rec, r)]                          # all of the opponent's games count
                res[t] = rec
            return res
        for weeks, basis, res in (([1, 2, 3, 4], "matchups", got[0]), ([2, 3], "matchups", got[1]), ([1, 2, 3, 4], "cats", got[2]), ([2, 3], "cats", got[3])):
            for t, rec in ref(weeks, basis).items():
                r = res[str(t)]
                self.assertEqual(r["record"], rec, "%s %s team %d" % (basis, weeks, t))
                n = sum(rec)
                if n:
                    self.assertAlmostEqual(r["pct"], (2 * rec[0] + rec[2]) / (2 * n), places=9)
                else:
                    self.assertIsNone(r["pct"])
                self.assertEqual(n, len(weeks) * len(weeks) * (9 if basis == "cats" else 1), "%s %s team %d" % (basis, weeks, t))   # n opponents x n weeks of games each
                self.assertEqual(r["faced"], len(weeks))

    def test_rest_of_season_strength_of_schedule_rates_the_opponents_still_to_come(self):
        doc = golden.build_report(18, 4, regular=10)
        schedule = doc["odds"]["schedule"]
        self.assertEqual(sorted(map(int, schedule)), [4, 5, 6, 7, 8, 9, 10])                  # from the week in progress to the end of the regular season
        for pairs in schedule.values():
            self.assertEqual(sorted(t for p in pairs for t in p), list(range(1, 19)))         # everyone plays once a week
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(doc, f)
            code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify([RotoPure.sosRest(d,d.weeks,d.odds.schedule,'matchups'),RotoPure.sosRest(d,d.weeks,d.odds.schedule,'cats')]))" % path
            out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        fx, orig = golden.FakeFetcher(golden.build_pages(18, 4, 7, regular=10)), yr.Fetcher
        yr.Fetcher = lambda **k: fx
        try:
            st, teams, wd, _ = yr.load("9", None, 0, "nba")
        finally:
            yr.Fetcher = orig
        headers = list(next(iter(wd[0]["teams"].values()))["cols"])
        specs, _ = yr.plan(st["categories"] or [h for h in headers if h and not h.endswith("M/A*")], headers)
        record = {"matchups": {}, "cats": {}}
        for w in wd:                                                                       # every week with results, the one in progress included
            tot = yr.totals([w], w["teams"])
            for x, y in w["matchups"]:
                for a, b in ((x, y), (y, x)):
                    sc, osc = w["teams"][a]["score"], w["teams"][b]["score"]
                    record["matchups"].setdefault(a, []).append([1, 0, 0] if sc > osc else [0, 1, 0] if sc < osc else [0, 0, 1])
                    record["cats"].setdefault(a, []).append(yr.head_to_head(tot[a], tot[b], specs))
        for basis, res in (("matchups", got[0]), ("cats", got[1])):
            for t in teams:
                rec = [0, 0, 0]
                for pairs in schedule.values():
                    o = next((p[1] if p[0] == t else p[0] for p in pairs if t in p))
                    for g in record[basis][o]:
                        rec = [a + b for a, b in zip(rec, g)]
                self.assertEqual(res[str(t)]["record"], rec, "%s team %d" % (basis, t))
                self.assertEqual(res[str(t)]["faced"], 7)                                  # seven weeks left

    def test_recent_form_and_the_strong_weak_split_match_a_from_scratch_computation(self):
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        calls = [("form", [1, 2, 3, 4], 3), ("form", [1, 2, 3], 2), ("form", [1, 2], 5), ("split", [1, 2, 3, 4], None), ("split", [2, 3], None)]
        got = {}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(self.doc, f)
            for basis in ("matchups", "cats"):
                js_calls = ",".join("RotoPure.%s(d,%s%s,%r)" % (fn, json.dumps(ws), "" if n is None else ",%d" % n, basis) for fn, ws, n in calls)
                code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify([%s]))" % (path, js_calls)
                out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr)
                got[basis] = json.loads(out.stdout)
        weekly = self.doc["composites"]["weekly"]

        def pct(r):
            n = sum(r)
            return (2 * r[0] + r[2]) / (2 * n) if n else None

        def add(recs):
            return [sum(r[i] for r in recs) for i in range(3)]

        def game(t, w, basis):
            v = weekly[str(t)][str(w)]
            return v["catRecord"] if basis == "cats" else {"W": [1, 0, 0], "L": [0, 1, 0], "T": [0, 0, 1]}[v["result"]]
        teams = [int(t) for t in self.doc["teams"]]
        for basis in ("matchups", "cats"):
            for (fn, ws, n), res in zip(calls[:3], got[basis][:3]):
                tail = ws[-n:]
                for t in teams:
                    last, season = add([game(t, w, basis) for w in tail]), add([game(t, w, basis) for w in ws])
                    r = res[str(t)]
                    self.assertEqual((r["last"]["record"], r["season"]["record"]), (last, season), (basis, t))
                    self.assertAlmostEqual(r["change"], pct(last) - pct(season), places=9)
                    self.assertAlmostEqual(r["earned"], pct(add([weekly[str(t)][str(w)]["allPlay"] for w in tail])), places=9)    # the all-play Win% of the same weeks
            for (fn, ws, n), res in zip(calls[3:], got[basis][3:]):
                pc = {t: pct(add([weekly[str(t)][str(w)]["allPlay"] for w in ws])) for t in teams}
                pts = {t: sum(weekly[str(t)][str(w)]["total"] for w in ws) for t in teams}
                order = sorted(teams, key=lambda t: (-pc[t], -pts[t], t))
                k = len(order) // 2
                self.assertEqual(res["order"], order)
                for t in teams:
                    for key, group in (("strong", order[:k]), ("weak", order[len(order) - k:])):
                        played = [w for w in ws if weekly[str(t)][str(w)]["opp"] in group and weekly[str(t)][str(w)]["opp"] != t]       # the real matchups against that half
                        r = res[str(t)][key]
                        self.assertEqual(r["record"], add([game(t, w, basis) for w in played]), "%s %s %s %s" % (basis, ws, t, key))
                        self.assertEqual(r["games"], len(played))
        self.assertTrue(any(r["strong"]["games"] + r["weak"]["games"] > 0 for k, r in got["matchups"][3].items() if k != "order"))     # the golden league has real games to count

    def test_opponent_squares_rate_every_weeks_opponent_by_its_real_record(self):
        doc = golden.build_report(18, 4, regular=10)
        weekly = doc["composites"]["weekly"]
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(doc, f)
            calls = ["RotoPure.oppByWeek(d,[1,2,3],'matchups')", "RotoPure.oppByWeek(d,[2,3],'cats')", "RotoPure.oppByWeek(d,d.weeks,'matchups',d.odds.schedule)"]
            code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify([%s]))" % (path, ",".join(calls))
            out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        teams = [int(t) for t in doc["teams"]]

        def pct(t, ws, basis):
            rec = [0, 0, 0]
            for w in ws:
                v = weekly[str(t)][str(w)]
                if v["opp"] is None or v["result"] is None:
                    continue
                g = v["catRecord"] if basis == "cats" else {"W": [1, 0, 0], "L": [0, 1, 0], "T": [0, 0, 1]}[v["result"]]
                rec = [a + b for a, b in zip(rec, g)]
            n = sum(rec)
            return (2 * rec[0] + rec[2]) / (2 * n) if n else None

        def rank_of(ws, basis):
            pc = {t: pct(t, ws, basis) for t in teams}
            return {t: 1 + sum(1 for j in teams if pc[j] is not None and pc[j] > pc[t]) for t in teams}
        for ws, basis, res in (([1, 2, 3], "matchups", got[0]), ([2, 3], "cats", got[1])):
            rk = rank_of(ws, basis)
            for t in teams:
                want = [{"week": w, "opp": weekly[str(t)][str(w)]["opp"], "rank": rk[weekly[str(t)][str(w)]["opp"]]} for w in ws if weekly[str(t)][str(w)]["result"]]
                self.assertEqual([{k: x[k] for k in ("week", "opp", "rank")} for x in res[str(t)]], want, (basis, t))
                for x in res[str(t)]:
                    tied = sum(1 for j in teams if rk[j] == x["rank"])
                    self.assertAlmostEqual(x["place"], x["rank"] + (tied - 1) / 2, places=9)                # level opponents share their average place
        rk = rank_of([1, 2, 3, 4], "matchups")                                              # the weeks still to come: from the pairings, the opponent's record through week 4
        sched = doc["odds"]["schedule"]
        for t in teams:
            want = []
            for w in sorted(map(int, sched)):
                opp = next((b if a == t else a for a, b in sched[str(w)] if t in (a, b)), None)
                want.append({"week": w, "opp": opp, "rank": rk[opp] if opp is not None else None})
            self.assertEqual([{k: x[k] for k in ("week", "opp", "rank")} for x in got[2][str(t)]], want, t)
        self.assertEqual(sorted(x["rank"] for t in teams for x in got[0][str(t)]), sorted(rank_of([1, 2, 3], "matchups")[x["opp"]] for t in teams for x in got[0][str(t)]))

    def test_a_report_without_made_attempts_is_refused_not_misread(self):
        old = json.loads(json.dumps(self.doc))
        for k, v in old["views"].items():
            for t in v["teams"].values():
                t.pop("raw", None)
        self.assertEqual(js_range(old, [[1, 3]]), [None])


if __name__ == "__main__":
    unittest.main()
