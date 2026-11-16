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

    def test_strength_of_schedule_matches_a_from_scratch_computation_and_splits_luck(self):
        with open(PAGE, encoding="utf-8") as f:
            src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.json")
            with open(path, "w") as f:
                json.dump(self.doc, f)
            code = src + "\nvar d=JSON.parse(require('fs').readFileSync(%r,'utf8'));console.log(JSON.stringify([RotoPure.schedule(d,[1,2,3,4]),RotoPure.schedule(d,[2,3])]))" % path
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

        def ref(weeks):
            acc = {t: [0, 0.0, 0.0, 0.0, 0.0] for t in teams}                    # games, sum b, sum a, sum p, real
            for w in wd:
                if w["week"] not in weeks:
                    continue
                tot = yr.totals([w], w["teams"])
                cells, rec = yr.all_play(tot, specs)
                for x, y in w["matchups"]:
                    for t, o in ((x, y), (y, x)):
                        c = cells[o][t]
                        ro = list(rec[o])
                        ro[0 if c[0] > c[1] else 1 if c[0] < c[1] else 2] -= 1
                        b = (2 * ro[0] + ro[2]) / (2 * sum(ro))
                        a = (2 * rec[t][0] + rec[t][2]) / (2 * sum(rec[t]))
                        dn = a * (1 - b) + (1 - a) * b
                        sc, osc = w["teams"][t]["score"], w["teams"][o]["score"]
                        acc[t][0] += 1
                        acc[t][1] += b
                        acc[t][2] += a
                        acc[t][3] += a * (1 - b) / dn if dn else a
                        acc[t][4] += 1 if sc > osc else 0.5 if sc == osc else 0
            return acc
        for weeks, res in (([1, 2, 3, 4], got[0]), ([2, 3], got[1])):
            for t, (g, sb, sa, sp, real) in ref(weeks).items():
                r = res[str(t)]
                self.assertEqual(r["games"], g)
                self.assertAlmostEqual(r["sos"], sb / g, places=9)
                self.assertAlmostEqual(r["schedule"], sp - sa, places=9)
                self.assertAlmostEqual(r["result"], real - sp, places=9)
                self.assertAlmostEqual(r["schedule"] + r["result"], r["luck"], places=9)      # the two parts make up Luck
                self.assertAlmostEqual(r["luck"], real - sa, places=9)

    def test_a_report_without_made_attempts_is_refused_not_misread(self):
        old = json.loads(json.dumps(self.doc))
        for k, v in old["views"].items():
            for t in v["teams"].values():
                t.pop("raw", None)
        self.assertEqual(js_range(old, [[1, 3]]), [None])


if __name__ == "__main__":
    unittest.main()
