"""Fixture-based check: roto and all-play from yahoo_roto equal an independent, deliberately naive computation on a real stored week (16 teams)."""
import json
import os
import sys
import unittest
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import yahoo_roto as yr  # noqa: E402

CATS = [("fgPct", False), ("ftPct", False), ("tpm", False), ("pts", False), ("reb", False), ("ast", False), ("st", False), ("blk", False), ("to", True)]


def val(s, k):
    if k == "fgPct":
        return Fraction(s["fg"][0], s["fg"][1])
    if k == "ftPct":
        return Fraction(s["ft"][0], s["ft"][1])
    return Fraction(s[k])


def ref_roto(stats):
    """Points by counting: 1 + (teams strictly worse) + (teams level, excluding itself) / 2."""
    pts = {t: 0.0 for t in stats}
    for k, lower in CATS:
        for t in stats:
            worse = sum(1 for u in stats if (val(stats[u], k) > val(stats[t], k) if lower else val(stats[u], k) < val(stats[t], k)))
            level = sum(1 for u in stats if u != t and val(stats[u], k) == val(stats[t], k))
            pts[t] += 1 + worse + level / 2
    return pts


def ref_cell(a, b):
    w = l = t = 0
    for k, lower in CATS:
        x, y = val(a, k), val(b, k)
        if x == y:
            t += 1
        elif (x > y) != lower:
            w += 1
        else:
            l += 1
    return [w, l, t]


class Parity(unittest.TestCase):
    def test_week_1_roto_and_all_play_for_all_16_teams(self):
        with open(os.path.join(HERE, "fixtures", "week-01.json"), encoding="utf-8") as f:
            wk = json.load(f)
        stats = {t["teamId"]: t["stats"] for m in wk["matchups"] for t in m["teams"]}
        self.assertEqual(len(stats), 16)
        cols = {tid: {"FGM/A*": tuple(s["fg"]), "FTM/A*": tuple(s["ft"]), "3PTM": Fraction(s["tpm"]), "PTS": Fraction(s["pts"]), "REB": Fraction(s["reb"]),
                      "AST": Fraction(s["ast"]), "ST": Fraction(s["st"]), "BLK": Fraction(s["blk"]), "TO": Fraction(s["to"])} for tid, s in stats.items()}
        specs, skipped = yr.plan(["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"],
                                 ["Team", "FGM/A*", "FG%", "FTM/A*", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"])
        self.assertEqual(skipped, [])
        res, _ = yr.roto(cols, specs)
        want = ref_roto(stats)
        for t in stats:
            self.assertAlmostEqual(res[t]["total"], want[t], places=9)
        cells, rec = yr.all_play(cols, specs)
        for a in stats:
            r = [0, 0, 0]
            for b in stats:
                if a != b:
                    c = ref_cell(stats[a], stats[b])
                    self.assertEqual(cells[a][b], c)
                    r[0 if c[0] > c[1] else 1 if c[0] < c[1] else 2] += 1
            self.assertEqual(rec[a], r)


if __name__ == "__main__":
    unittest.main()
