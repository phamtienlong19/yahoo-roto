"""Every league in leagues.json has its own address (<id>/index.html), a copy of index.html. Run `python3 pages.py` to refresh the copies."""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import pages  # noqa: E402


class LeaguePages(unittest.TestCase):
    def test_each_league_page_is_a_current_copy_of_index_html(self):
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
            page = f.read()
        ids = pages.league_ids(ROOT)
        self.assertTrue(ids)
        for lid in ids:
            with open(os.path.join(ROOT, lid, "index.html"), encoding="utf-8") as f:
                self.assertEqual(f.read(), page, "%s/index.html is out of date: run python3 pages.py" % lid)


if __name__ == "__main__":
    unittest.main()
