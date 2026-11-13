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
        names = pages.league_names(ROOT)
        self.assertTrue(ids)
        for lid in ids:
            with open(os.path.join(ROOT, lid, "index.html"), encoding="utf-8") as f:
                self.assertEqual(f.read(), pages.render(page, names.get(lid)), "%s/index.html is out of date: run python3 pages.py" % lid)

    def test_each_league_page_has_its_own_title_and_preview_tags(self):
        names = pages.league_names(ROOT)
        self.assertTrue(names)
        for lid, name in names.items():
            with open(os.path.join(ROOT, lid, "index.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("<title>%s \u00b7 Roto standings</title>" % name, html)
            self.assertIn('<meta property="og:title" content="%s">' % name, html)
            self.assertEqual(html.count("<title>"), 1)

    def test_names_are_html_escaped(self):
        out = pages.render("<!--meta--><title>x</title><!--/meta-->", 'A "B" <i>')
        self.assertNotIn("<i>", out)
        self.assertIn("&quot;B&quot;", out)


if __name__ == "__main__":
    unittest.main()
