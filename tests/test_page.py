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
    def test_every_inline_script_is_valid_javascript(self):
        import tempfile
        with open(PAGE, encoding="utf-8") as f:
            scripts = re.findall(r"<script(?![^>]*\ssrc)[^>]*>(.*?)</script>", f.read(), re.S)
        self.assertGreaterEqual(len(scripts), 3)
        for i, src in enumerate(scripts):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "s%d.js" % i)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(src)
                out = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=30)
                self.assertEqual(out.returncode, 0, "script %d: %s" % (i, out.stderr))

    def test_movers_are_the_biggest_rises_and_falls_of_at_least_the_threshold(self):
        got = js("RotoPure.movers({1:0.50,2:0.40,3:0.30,4:0.20,5:0.10,6:0.5},{1:0.70,2:0.55,3:0.29,4:0.05,5:0.31,7:0.9},0.02,2)")
        self.assertEqual([m["id"] for m in got["up"]], ["5", "1"])                                  # +21 and +20; team 2 (+15) would be third
        self.assertEqual([m["id"] for m in got["down"]], ["4"])                                     # -15; team 3 moved by -1 point only
        self.assertAlmostEqual(got["up"][0]["delta"], 0.21)
        self.assertEqual(js("RotoPure.movers({1:0.5},{2:0.9},0.02,3)"), {"up": [], "down": []})        # a team without an earlier snapshot is skipped

    def test_sparkline_geometry(self):
        g = js("RotoPure.sparkGeom([1,3,2,null,4],100,20,{})")
        self.assertEqual(len(g["pts"]), 4)                                                      # the missing value is skipped
        self.assertIsNone(g["baseY"])
        self.assertEqual(g["pts"][0][0], 3)                                                      # padding on the left
        self.assertLess(g["pts"][3][1], g["pts"][0][1])                                         # a higher value is drawn higher
        inv = js("RotoPure.sparkGeom([1,3],100,20,{invert:true})")
        self.assertGreater(inv["pts"][1][1], inv["pts"][0][1])                                  # inverted (ranks): lower is drawn higher
        self.assertIsNotNone(js("RotoPure.sparkGeom([-1,2],100,20,{base:0})")["baseY"])                    # a baseline (zero luck, an average week) is drawn when given
        shared = js("[RotoPure.sparkGeom([0,1],100,20,{lo:-10,hi:10,base:0}),RotoPure.sparkGeom([0,1],100,20,{})]")
        self.assertGreater(shared[0]["pts"][1][1], shared[1]["pts"][1][1])                      # rows of one column share a scale: a small move stays small
        flat = js("RotoPure.sparkGeom([5,5,5],100,20,{})")
        self.assertEqual(len({p[1] for p in flat["pts"]}), 1)                                   # a flat series is a flat line
        self.assertIsNone(js("RotoPure.sparkGeom([5,null],100,20,{})"))                         # fewer than two values: nothing to draw

    def test_the_readme_stays_short_and_plain(self):
        with open(os.path.join(HERE, "..", "README.md"), encoding="utf-8") as f:
            text = f.read()
        in_code = False
        for line in text.split("\n"):                                          # a line is a paragraph or one list item
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code or line.lstrip().startswith("|"):
                continue
            self.assertLessEqual(len(line.split()), 80, "README line too long: %s..." % line[:50])
        for word in ("log5", "shrunk", "Exp.", "schedule.json", "odds.json"):
            self.assertNotIn(word, text)                                       # internals live in ARCHITECTURE.md
        self.assertLessEqual(len(text.split()), 900)

    def test_no_week_is_labelled_w_followed_by_a_number(self):
        with open(PAGE, encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(re.findall(r'"W"\s*\+', src), [])                     # "W4" reads as "won 4"; weeks are "Wk 4"

    def test_css_uses_only_the_root_selectors_the_image_export_knows_how_to_move(self):
        # Save-as-image copies the page's CSS into a wrapper and rewrites `:root{`, `html{`, `body{` and `body.static`. A rule that targets html/body any other way would
        # silently lose its styling in saved images, so this fails until the export code is taught about it.
        with open(PAGE, encoding="utf-8") as f:
            css = re.search(r"<style>(.*?)</style>", f.read(), re.S).group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for m in re.finditer(r"(?<![\w.#-])(html|body)(?![\w-])([^{,]*)[{,]", css):
            rest = m.group(2)
            ok = (m.group(1) == "html" and (rest == "" or rest.startswith("[data-theme=dark]")) or m.group(1) == "body" and (rest in ("", ".static") or rest.startswith(".static ")))
            self.assertTrue(ok, "unsupported root selector: %s%s" % (m.group(1), rest))
        self.assertNotIn(":root", re.sub(r":root\{", "", css))

    def test_roto_point_buckets_for_16_teams(self):
        # two shades per side; the middle four places (7-10) are white
        got = js("[1,3,3.5,4,6,6.5,7,8,8.5,10,10.5,11,13,13.5,14,16].map(p=>RotoPure.cls(p,16))")
        self.assertEqual(got, ["red-strong", "red-strong", "red-soft", "red-soft", "red-soft", "red-soft", "mid", "mid", "mid", "mid", "green-soft", "green-soft", "green-soft",
                               "green-soft", "green-strong", "green-strong"])

    def test_the_white_band_is_places_8_to_11_of_18(self):
        got = js("Array.from({length:18},(_,i)=>RotoPure.cls(i+1,18))")
        self.assertEqual([i + 1 for i, c in enumerate(got) if c == "mid"], [8, 9, 10, 11])
        self.assertEqual(got[:3] + got[-3:], ["red-strong"] * 3 + ["green-strong"] * 3)
        self.assertEqual(got[3:7], ["red-soft"] * 4)
        self.assertEqual(got[11:15], ["green-soft"] * 4)

    def test_buckets_scale_with_the_team_count_and_stay_symmetric(self):
        for n, white in ((8, 2), (10, 4), (12, 4), (14, 4), (16, 4), (18, 4), (20, 4)):
            got = js("[%s].map(p=>RotoPure.cls(p,%d))" % (",".join(str(i) for i in range(1, n + 1)), n))
            flip = ["red-" + c[6:] if c.startswith("green-") else "green-" + c[4:] if c.startswith("red-") else c for c in got]
            self.assertEqual(got, flip[::-1], n)                           # place p and place n+1-p are mirror shades
            self.assertEqual((got[0], got[-1]), ("red-strong", "green-strong"))
            self.assertEqual(got.count("mid"), white, n)
        self.assertEqual(js("RotoPure.cls(null,16)"), "mid")
        self.assertEqual(js("[1,2,16].map(r=>RotoPure.rankCls(r,16))"), ["green-strong", "green-strong", "red-strong"])

    def test_places_share_the_average_and_skip_missing(self):
        self.assertEqual(js("RotoPure.places([5,9,5,null,20])"), [1.5, 3, 1.5, None, 4])

    def test_sort_key_reads_the_number_in_a_cell(self):
        got = js('["+4.79","\u22120.12",".518","W2","W3 \u00b7 105.5","18-8-1","20.5","1978","\u2013","Hai | Bulls Dynasty","0.00",""].map(RotoPure.sortKey)')
        self.assertEqual(got, [4.79, -0.12, 0.518, 2, 105.5, 18, 20.5, 1978, None, None, 0, None])

    def test_shared_ranks_read_t_dash_and_still_sort_as_numbers(self):
        self.assertEqual(js('[RotoPure.tl(2,[1,2,2,4]),RotoPure.tl(1,[1,2,2,4]),RotoPure.tl(4,[1,2,2,4])]'), ["T-2", "1", "4"])
        self.assertEqual(js('["T-2","T-10","3"].map(RotoPure.sortKey)'), [2, 10, 3])

    def test_matrix_margin_buckets(self):
        got = js("[9,5,4,3,2,1,0,-1,-2,-3,-4,-5,-9,0.4,-0.4].map(RotoPure.matrixCls)")
        self.assertEqual(got, ["dark-green", "dark-green", "green", "green", "light-green", "light-green", "white", "light-red", "light-red", "red", "red", "dark-red", "dark-red",
                               "light-green", "light-red"])

    def test_number_formats(self):
        self.assertEqual(js("[RotoPure.fmtVal(true,0.4817),RotoPure.fmtVal(false,68),RotoPure.fmtVal(false,571),RotoPure.fmtVal(true,1),RotoPure.fmtVal(false,null)]"), [".482", "68", "571", "1.000", "–"])
        self.assertEqual(js("[RotoPure.fmtPts(6.5),RotoPure.fmtPts(9),RotoPure.pct(0.88235),RotoPure.pct(0),RotoPure.signed(0.1667,2),RotoPure.signed(-1/3,2)]"),
                         ["6.5", "9", "88.2%", "0.0%", "+0.17", "−0.33"])


if __name__ == "__main__":
    unittest.main()
