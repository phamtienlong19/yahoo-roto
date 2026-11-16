"""The poll cadence: fast while the numbers move, slower the longer they stay put, with the clock only as a ceiling."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import cadence  # noqa: E402

MIN, HOUR = 60, 3600


class Fingerprint(unittest.TestCase):
    def test_the_timestamp_does_not_count_as_a_change_but_a_number_does(self):
        a = {"asOf": "2026-11-16T01:00:00Z", "views": {"w1": {"x": 1}}}
        b = {"asOf": "2026-11-16T01:04:00Z", "views": {"w1": {"x": 1}}}
        c = {"asOf": "2026-11-16T01:04:00Z", "views": {"w1": {"x": 2}}}
        self.assertEqual(cadence.fingerprint(a), cadence.fingerprint(b))
        self.assertNotEqual(cadence.fingerprint(a), cadence.fingerprint(c))

    def test_record_reports_first_sight_and_real_changes_only(self):
        st = {"leagues": {}}
        self.assertTrue(cadence.record(st, 1, {"v": 1}, 100))              # first sight starts fast
        self.assertFalse(cadence.record(st, 1, {"v": 1, "asOf": "later"}, 400))
        self.assertEqual(st["leagues"]["1"]["changed_at"], 100)
        self.assertTrue(cadence.record(st, 1, {"v": 2}, 700))
        self.assertEqual(cadence.quiet_for(st, 1000), 300)
        self.assertEqual(cadence.quiet_for({"leagues": {}}, 1000), 10 ** 9)

    def test_quiet_time_is_measured_from_the_most_recent_change_in_any_league(self):
        st = {"leagues": {"1": {"changed_at": 100}, "2": {"changed_at": 900}}}
        self.assertEqual(cadence.quiet_for(st, 1000), 100)


class Delay(unittest.TestCase):
    NIGHT, MORNING = 2, 15          # UTC hours: US game hours / the quiet US morning (a Wednesday)

    def test_fast_while_stats_are_moving(self):
        self.assertEqual(cadence.delay(0, self.NIGHT, 3), cadence.FAST)
        self.assertEqual(cadence.delay(19 * MIN, self.MORNING, 3), cadence.FAST)

    def test_it_backs_off_the_longer_nothing_changes(self):
        got = [cadence.delay(q, self.NIGHT, 3) for q in (10 * MIN, 30 * MIN, 2 * HOUR)]
        self.assertEqual(got, [180, 300, 600])
        morning = [cadence.delay(q, self.MORNING, 3) for q in (30 * MIN, 2 * HOUR, 6 * HOUR, 20 * HOUR)]
        self.assertEqual(morning, [300, 600, 1800, 1800])                  # outside game hours the ceiling is 30 minutes
        self.assertTrue(cadence.delay(20 * HOUR, self.NIGHT, 3) <= cadence.GAME_HOURS_CAP)   # in game hours a long quiet is still checked every 10 minutes at most

    def test_the_clock_is_only_a_ceiling_so_a_tip_off_is_noticed(self):
        for q in (4 * HOUR, 20 * HOUR, 2 * 86400):
            self.assertLessEqual(cadence.delay(q, self.NIGHT, 3), cadence.GAME_HOURS_CAP)
            self.assertLessEqual(cadence.delay(q, self.MORNING, 3), cadence.OTHER_CAP)

    def test_weekend_afternoons_count_as_game_hours(self):
        self.assertTrue(cadence.game_hours(17, 6))
        self.assertTrue(cadence.game_hours(17, 7))
        self.assertFalse(cadence.game_hours(17, 3))
        self.assertTrue(cadence.game_hours(23, 3) and cadence.game_hours(5, 3))
        self.assertFalse(cadence.game_hours(12, 3))

    def test_the_offseason_is_hourly(self):
        self.assertEqual(cadence.delay(5 * 86400, self.NIGHT, 3), cadence.SLOW_HOUR)
        self.assertEqual(cadence.delay(10 ** 9, self.MORNING, 3), cadence.SLOW_HOUR)

    def test_a_live_game_from_an_optional_feed_forces_fast(self):
        self.assertEqual(cadence.delay(20 * HOUR, self.MORNING, 3, games=[{"status": 2, "start": 0}]), cadence.FAST)
        self.assertEqual(cadence.delay(20 * HOUR, self.MORNING, 3, games=[{"status": 3, "start": 0}]), 1800)    # all final: the normal ladder applies

    def test_it_never_sleeps_less_than_the_polite_minimum(self):
        for q in (0, 10, 10 ** 6):
            for hr in (0, 12, 23):
                self.assertGreaterEqual(cadence.delay(q, hr, 3), cadence.FAST)


class Outages(unittest.TestCase):
    def test_failures_are_counted_remembered_and_alerted_once_per_outage(self):
        st = {"leagues": {}}
        for i in range(4):
            cadence.note_failure(st, 7, "HTTP 503\n  from   yahoo", 100 + i)
        self.assertEqual(cadence.due_alerts(st, 5), [])
        cadence.note_failure(st, 7, "x" * 1000, 200)
        self.assertEqual(st["leagues"]["7"]["fail_since"], 100)
        self.assertEqual(len(st["leagues"]["7"]["last_error"]), 300)
        self.assertEqual(cadence.due_alerts(st, 5), ["7"])
        self.assertEqual(cadence.due_alerts(st, 5), [])                    # already told
        cadence.record(st, 7, {"v": 1}, 300)                               # a good pass ends the outage...
        self.assertEqual((st["leagues"]["7"]["fails"], "alerted" in st["leagues"]["7"], "last_error" in st["leagues"]["7"]), (0, False, False))
        for i in range(5):
            cadence.note_failure(st, 7, "again", 400 + i)
        self.assertEqual(cadence.due_alerts(st, 5), ["7"])                 # ...so the next outage alerts again

    def test_the_public_status_has_no_internal_fields(self):
        st = {"leagues": {"7": {"fp": "abc", "changed_at": 1, "last_ok": 50, "fails": 2, "fail_since": 60, "last_error": "boom", "alerted": True}}}
        self.assertEqual(cadence.public_status(st, 99.7), {"updated": 99, "leagues": {"7": {"lastOk": 50, "fails": 2, "since": 60, "error": "boom"}}})

    def test_cli_fail_status_alerts_and_atomic_state(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            st, out = os.path.join(d, "_state.json"), os.path.join(d, "status.json")
            for _ in range(5):
                cadence.main(["fail", st, "85092", "HTTP", "503"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cadence.main(["alerts", st, "5"])
                cadence.main(["alerts", st, "5"])
            self.assertEqual(buf.getvalue().split("\n")[:2], ["85092", ""])
            cadence.main(["status", st, out])
            self.assertEqual(json.load(open(out))["leagues"]["85092"]["fails"], 5)
            self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Cli(unittest.TestCase):
    def test_record_then_delay_through_the_state_file(self):
        with tempfile.TemporaryDirectory() as d:
            st, rep = os.path.join(d, "sub", "_state.json"), os.path.join(d, "r.json")
            with open(rep, "w") as f:
                json.dump({"asOf": "x", "v": 1}, f)
            self.assertEqual(cadence.main(["record", st, "85092", rep]), 0)
            self.assertEqual(cadence.main(["delay", st]), 0)
            self.assertFalse(cadence.record(cadence.load_state(st), "85092", {"v": 1}, 1))
            self.assertEqual(cadence.main(["record", st, "85092", os.path.join(d, "missing.json")]), 2)
            self.assertEqual(cadence.load_state(os.path.join(d, "none.json")), {"leagues": {}})


if __name__ == "__main__":
    unittest.main()
