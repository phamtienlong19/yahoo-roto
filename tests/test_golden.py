"""Invariants that must hold for any league, checked on a generated 18-team, 4-week report that went through the real pipeline."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden  # noqa: E402
import yahoo_roto as yr  # noqa: E402


def drop_time(doc):
    d = json.loads(json.dumps(doc))
    d.pop("asOf", None)
    return d


class Invariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = golden.build_report(18, 4)
        cls.n = 18

    def test_every_weekly_category_hands_out_exactly_the_points_there_are(self):
        n = self.n
        for key, v in self.doc["views"].items():
            for c in self.doc["categories"]:
                self.assertAlmostEqual(sum(t["points"][c["cat"]] for t in v["teams"].values()), n * (n + 1) / 2, msg="%s %s" % (key, c["cat"]))

    def test_each_weekly_all_play_record_is_one_game_per_opponent(self):
        for w in self.doc["weeks"]:
            for t in self.doc["views"]["w%d" % w]["teams"].values():
                self.assertEqual(sum(t["allPlay"]), self.n - 1)
        weeks = len(self.doc["views"]["season"]["weeks"])
        for t in self.doc["views"]["season"]["teams"].values():
            self.assertEqual(sum(t["allPlay"]), weeks * (self.n - 1))

    def test_luck_and_category_luck_add_up_to_zero_across_the_league(self):
        for comp in (self.doc["composites"], self.doc["compositesFinal"]):
            self.assertAlmostEqual(sum(v["luck"] for v in comp["realRecord"].values()), 0, places=6)
            self.assertAlmostEqual(sum(v["luck"] for v in comp["catLuck"].values()), 0, places=6)
            self.assertAlmostEqual(sum(v["realWins"] for v in comp["realRecord"].values()), sum(v["expectedWins"] for v in comp["realRecord"].values()), places=6)

    def test_roto_totals_follow_from_the_points(self):
        for v in self.doc["views"].values():
            for t in v["teams"].values():
                self.assertAlmostEqual(t["total"], sum(t["points"].values()))

    def test_the_final_snapshot_is_the_report_you_would_have_without_the_live_week(self):
        three = golden.build_report(18, 3)
        full = self.doc
        self.assertEqual(drop_time(full["views"]["seasonFinal"]), drop_time(three["views"]["season"]))
        self.assertEqual(drop_time(full["compositesFinal"]), drop_time(three["composites"]))
        self.assertEqual(full["views"]["seasonFinal"]["weeks"], [1, 2, 3])

    def test_the_champion_and_format_version_are_set(self):
        self.assertEqual(self.doc["teams"][str(self.doc["champion"])], "sup fam")
        self.assertEqual(self.doc["schemaVersion"], 3)

    def test_yahoos_standings_are_read_again_only_while_they_lag_the_finished_weeks(self):
        pages = golden.build_pages(18, 4)
        old = golden.build_pages(18, 3)["lhst=stand"]                                      # Yahoo's table as it was before the last week closed

        def run(first):
            asked = []

            class Lagging(golden.FakeFetcher):
                def get(self, url, ttl=None):
                    if url.endswith("lhst=stand"):
                        asked.append(ttl)
                        return first if ttl == yr.TTL["standings"] else pages["lhst=stand"]
                    return super().get(url, ttl)
            fx, orig = Lagging(pages), yr.Fetcher
            yr.Fetcher = lambda **k: fx
            try:
                return yr.report("9"), asked
            finally:
                yr.Fetcher = orig
        doc, asked = run(old)
        self.assertEqual(asked, [yr.TTL["standings"], yr.STANDINGS_BEHIND_TTL])
        self.assertTrue(all(doc["yahooStandings"][t]["record"] == r["catRecord"] for t, r in doc["compositesFinal"]["realRecord"].items()))
        doc, asked = run(pages["lhst=stand"])
        self.assertEqual(asked, [yr.TTL["standings"]])                                     # in step: no extra request

    def test_rerunning_gives_the_same_numbers(self):
        self.assertEqual(drop_time(golden.build_report(18, 4)), drop_time(self.doc))


if __name__ == "__main__":
    unittest.main()
