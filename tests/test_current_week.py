"""Yahoo's own current week decides whether a week is still being played, and its Stat Corrections page says until when a closed week may still change."""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import golden  # noqa: E402
import yahoo_roto as yr  # noqa: E402

NOW = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)


def corrections_page(rows, late, applies="Monday, Nov 16"):
    """The parts of Yahoo's Stat Corrections page the parser reads: a table of rows (the date cell of a late one is red) and the footer sentence."""
    body = "".join('<tr><td class="Alt Ta-start%s"><div>Nov 9</div></td><td><div>Player %d</div></td><td><div>BLK</div></td><td><div>-1</div></td></tr>' % (" F-negative" if i < late else "", i)
                   for i in range(rows))
    return ('<table class="Tst-table Table"><thead><tr class="First Last"><th>Date</th><th>Player</th><th>Stat</th><th>Change</th></tr></thead><tbody>%s</tbody></table>'
            "<p>Corrections displayed in this way were received too late to apply to the scoring for your league.</p><p>Stat corrections are applied on %s. All game times are shown in EST.</p>"
            % (body, applies))


class Fake(golden.FakeFetcher):
    """A league whose Yahoo calendar says `current` is the current week; `corr` is what its corrections page shows (None: the page cannot be read)."""
    def __init__(self, pages, current, corr):
        super().__init__(pages)
        self.current, self.corr, self.seen = current, corr, []

    def get(self, url, ttl=None):
        self.seen.append(url)
        if url.endswith("/matchup?date=totals&mid1=1"):
            if self.current is None:
                raise yr.RotoError("unexpected " + url)
            return self.pages["week=%d&mid1=1" % self.current]
        if "/statcorrections?week=" in url:
            if self.corr is None:
                raise yr.RotoError("unexpected " + url)
            return self.corr
        return super().get(url, ttl)


def report(pages, fx, cache, now=NOW):
    orig = yr.Fetcher
    saved = (yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS)
    yr.Fetcher, (yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS) = (lambda **k: fx), (4000, 200, 1000)
    try:
        return yr.report("9", cache=cache, now=now)
    finally:
        yr.Fetcher, (yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS) = orig, saved


class Parser(unittest.TestCase):
    def test_rows_late_rows_and_the_day_yahoo_applies_them(self):
        got = yr.parse_stat_corrections(corrections_page(26, 22), NOW.timestamp())
        self.assertEqual((got["rows"], got["late"], got["pending"]), (26, 22, 4))
        self.assertEqual(datetime.datetime.fromtimestamp(got["applies"], datetime.timezone.utc).strftime("%Y-%m-%d"), "2026-11-16")

    def test_a_week_without_corrections_is_still_a_dated_page(self):
        got = yr.parse_stat_corrections(corrections_page(0, 0), NOW.timestamp())
        self.assertEqual((got["rows"], got["pending"]), (0, 0))

    def test_a_year_boundary_picks_the_nearest_date(self):
        dec = datetime.datetime(2026, 12, 28, tzinfo=datetime.timezone.utc)
        got = yr.parse_stat_corrections(corrections_page(1, 0, "Monday, Jan 4"), dec.timestamp())
        self.assertEqual(datetime.datetime.fromtimestamp(got["applies"], datetime.timezone.utc).strftime("%Y-%m-%d"), "2027-01-04")

    def test_a_page_that_is_not_recognised_gives_nothing(self):
        self.assertIsNone(yr.parse_stat_corrections("<html><body>Sign in</body></html>", NOW.timestamp()))
        self.assertIsNone(yr.parse_stat_corrections(corrections_page(2, 0).replace("are applied on", "come soon, on"), NOW.timestamp()))


class Schedule(unittest.TestCase):
    def test_rechecks_every_few_hours_until_yahoo_applies_corrections_then_once_more_and_never_again(self):
        a = int(NOW.timestamp())
        meta = {"finalized": a - 86400, "checks": 0, "applies": a}
        self.assertTrue(yr.recheck_due(meta, a))                                              # never checked: due
        meta["checked"] = a - 3600
        self.assertFalse(yr.recheck_due(meta, a))                                             # looked an hour ago
        self.assertTrue(yr.recheck_due(meta, a + 3 * 3600 - 3600 + 1))
        self.assertTrue(yr.recheck_due(dict(meta, checked=a + 3600), a + yr.SETTLE + 1))      # after the apply day plus the grace: one last look
        self.assertFalse(yr.recheck_due(dict(meta, checks=len(yr.CHECK_AGES)), a + 10 ** 7))  # frozen

    def test_without_a_known_date_the_old_fixed_schedule_applies(self):
        meta = {"finalized": 1000, "checks": 1}
        self.assertFalse(yr.recheck_due(meta, 1000 + 6 * 3600 - 1))
        self.assertTrue(yr.recheck_due(meta, 1000 + 6 * 3600))


class InTheReport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.pages = golden.build_pages(18, 4, 7, regular=8, divisions=True)

    def test_when_yahoo_is_on_the_next_week_the_last_week_with_stats_is_over_and_settling(self):
        fx = Fake(self.pages, 5, corrections_page(26, 22))
        doc = report(self.pages, fx, self.dir)
        self.assertIsNone(doc["inProgressWeek"])
        self.assertEqual(doc["currentWeek"], 5)
        self.assertEqual(doc["settling"], {"week": 4, "applies": "2026-11-16", "pending": 4, "late": 22})
        self.assertNotIn("seasonFinal", doc["views"])
        self.assertIsNone(doc["compositesFinal"])
        self.assertEqual(doc["weeks"], [1, 2, 3, 4])
        self.assertEqual(doc["odds"]["remaining"], [5, 6, 7, 8])                              # nothing is half-played: the season continues from week 5
        self.assertEqual([h["week"] for h in doc["odds"]["history"]], [1, 2, 3, 4])          # week 4 counts as a finished week
        self.assertEqual(sum(doc["composites"]["realRecord"][str(t)]["record"][0] + doc["composites"]["realRecord"][str(t)]["record"][1] + doc["composites"]["realRecord"][str(t)]["record"][2] for t in range(1, 19)), 4 * 18)

    def test_when_yahoo_is_still_on_the_last_week_it_is_live_as_before(self):
        fx = Fake(self.pages, 4, corrections_page(1, 0))
        doc = report(self.pages, fx, self.dir)
        self.assertEqual((doc["inProgressWeek"], doc["currentWeek"], doc["settling"]), (4, 4, None))
        self.assertIn("seasonFinal", doc["views"])
        self.assertEqual(doc["odds"]["remaining"], [4, 5, 6, 7, 8])
        self.assertEqual([url for url in fx.seen if "statcorrections?week=4" in url], [])    # a live week has nothing to settle yet

    def test_an_unreadable_calendar_falls_back_to_the_old_rule(self):
        doc = report(self.pages, Fake(self.pages, None, corrections_page(1, 0)), self.dir)
        self.assertEqual((doc["inProgressWeek"], doc["currentWeek"]), (4, None))

    def test_an_unreadable_corrections_page_still_ends_the_live_week_but_adds_no_banner(self):
        doc = report(self.pages, Fake(self.pages, 5, None), self.dir)
        self.assertEqual((doc["inProgressWeek"], doc["settling"]), (None, None))

    def test_a_closed_week_is_cached_and_read_again_until_the_apply_day(self):
        fx = Fake(self.pages, 5, corrections_page(3, 1))
        report(self.pages, fx, self.dir, NOW)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "9-week-4.json")))
        fx2 = Fake(self.pages, 5, corrections_page(3, 1))
        report(self.pages, fx2, self.dir, NOW + datetime.timedelta(hours=1))                  # an hour later: not due
        self.assertEqual([u for u in fx2.seen if "week=4&mid1=" in u], [])
        fx3 = Fake(self.pages, 5, corrections_page(3, 1))
        report(self.pages, fx3, self.dir, NOW + datetime.timedelta(hours=4))                  # four hours later: week 4 is read again
        self.assertTrue([u for u in fx3.seen if "week=4&mid1=" in u])

    def test_a_week_that_changed_before_the_apply_day_is_recorded_as_a_correction(self):
        report(self.pages, Fake(self.pages, 5, corrections_page(3, 1)), self.dir, NOW)
        changed = dict(self.pages)
        key = next(k for k in changed if k.startswith("week=4&mid1=1"))
        import re
        changed[key] = re.sub(r"(<td>)(\d+)(</td><td>\d+</td><td>\d+</td><td>\d+</td><td>\d+</td><td>\d+</td><td>\d+</td><td>-?\d+</td>)", lambda m: m.group(1) + str(int(m.group(2)) + 5) + m.group(3), changed[key], 1)
        fx = Fake(changed, 5, corrections_page(3, 1))
        doc = report(changed, fx, self.dir, NOW + datetime.timedelta(hours=4))
        self.assertTrue(any(c["week"] == 4 for c in doc["corrections"]), doc["corrections"])


if __name__ == "__main__":
    unittest.main()
