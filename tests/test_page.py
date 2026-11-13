"""The page's pure helpers (colour buckets, places, number formats) run through node; skipped when node is not installed."""
import json
import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "..", "index.html")


def js(expr):
    with open(PAGE, encoding="utf-8") as f:
        src = re.search(r'<script id="pure">(.*?)</script>', f.read(), re.S).group(1)
    out = subprocess.run(["node", "-e", src + "\nconsole.log(JSON.stringify(" + expr + "))"], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Page(unittest.TestCase):
    def test_roto_point_buckets_for_16_teams(self):
        got = js("[1,3,3.5,4,6,6.5,7,10,10.5,11,13.5,14,16].map(p=>RotoPure.cls(p,16))")
        self.assertEqual(got, ["red-strong", "red-strong", "red-soft", "red-soft", "red-soft", "mid", "mid", "mid", "mid", "green-soft", "green-soft", "green-strong", "green-strong"])

    def test_bucket_edges_follow_the_team_count(self):
        # n=18: strong green >= 16, soft green >= 13 (the reference sheet)
        self.assertEqual(js("[15.5,16,12.5,13].map(p=>RotoPure.cls(p,18))"), ["green-soft", "green-strong", "mid", "green-soft"])
        self.assertEqual(js("RotoPure.cls(null,16)"), "mid")
        self.assertEqual(js("[1,2,16].map(r=>RotoPure.rankCls(r,16))"), ["green-strong", "green-strong", "red-strong"])

    def test_places_share_the_average_and_skip_missing(self):
        self.assertEqual(js("RotoPure.places([5,9,5,null,20])"), [1.5, 3, 1.5, None, 4])

    def test_matrix_margin_buckets(self):
        got = js("[9,5,4,3,2,1,0,-1,-2,-3,-4,-5,-9,0.4,-0.4].map(RotoPure.matrixCls)")
        self.assertEqual(got, ["dark-green", "dark-green", "green", "green", "light-green", "light-green", "white", "light-red", "light-red", "red", "red", "dark-red", "dark-red",
                               "light-green", "light-red"])

    def test_number_formats(self):
        self.assertEqual(js("[RotoPure.fmtVal(true,0.4817),RotoPure.fmtVal(false,68),RotoPure.fmtVal(false,571),RotoPure.fmtVal(true,1),RotoPure.fmtVal(false,null)]"), [".482", "68", "571", "1.000", "–"])
        self.assertEqual(js("[RotoPure.fmtPts(6.5),RotoPure.fmtPts(9),RotoPure.pct3(0.88235),RotoPure.pct3(0),RotoPure.signed(0.1667,2),RotoPure.signed(-1/3,2)]"),
                         ["6.5", "9", "0.882", "0.000", "+0.17", "−0.33"])


if __name__ == "__main__":
    unittest.main()
