"""The canary's health rules, on the generated league and on broken variants of it."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import canary  # noqa: E402
import golden  # noqa: E402


class Canary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = golden.build_report(18, 2)

    def test_a_healthy_report_has_no_problems(self):
        self.assertEqual(canary.check(self.doc), [])

    def test_each_kind_of_silent_breakage_is_reported(self):
        d = copy.deepcopy(self.doc)
        d["categories"] = d["categories"][:2]
        self.assertTrue(any("scoring categories" in p for p in canary.check(d)))
        d = copy.deepcopy(self.doc)
        d["teams"] = {"1": "A"}
        self.assertTrue(any("teams found" in p for p in canary.check(d)))
        d = copy.deepcopy(self.doc)
        d["weeks"] = []
        self.assertEqual(canary.check(d), ["no week with stats"])
        d = copy.deepcopy(self.doc)
        d["views"]["season"]["teams"]["3"]["values"]["PTS"] = None
        self.assertTrue(any("no value for PTS" in p for p in canary.check(d)))
        d = copy.deepcopy(self.doc)
        d["skipped"] = ["ERA"]
        self.assertTrue(any("skipped" in p for p in canary.check(d)))

    def test_the_command_needs_exactly_one_league_id(self):
        self.assertEqual(canary.main([]), 2)
        self.assertEqual(canary.main(["a", "b"]), 2)


if __name__ == "__main__":
    unittest.main()
