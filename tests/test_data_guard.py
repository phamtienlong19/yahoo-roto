"""Safe publishing of the data branch: chain, policies, restore verification, compare-and-swap push, alerts.
Git cases use local bare repositories and file:// remotes; nothing touches the network."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import data_guard as dg  # noqa: E402

GUARD = os.path.join(ROOT, "data_guard.py")
ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def chain(rows):
    out, prev = [], ""
    for r in rows:
        r = dict(r)
        r["id"] = dg.row_id(prev, r)
        prev = r["id"]
        out.append(r)
    return {"v": 1, "chain": dg.CHAIN, "rows": out, "head": prev}


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def git(*args, cwd, check=True):
    r = subprocess.run(["git", *ID, *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError("git %s: %s" % (args, r.stderr))
    return r.stdout.strip()


WEEK = {"v": 2, "matchups": [], "teams": {}}


def good_tree(extra=None):
    t = {"_cache/7-games.json": chain([{"w": 1, "p": 2}, {"w": 1, "p": 3}]), "_cache/7-week-1.json": WEEK,
         "_cache/7-odds.json": {"fp": "x"}, "7/report.json": {"schemaVersion": 3}, "status.json": {"leagues": {}},
         "_cache/aaa.html": "<html>"}
    t.update(extra or {})
    return t


class Chain(unittest.TestCase):
    def test_vectors_computed_independently_of_the_code(self):
        with open(os.path.join(ROOT, "tests", "fixtures", "chain_vectors.json"), encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        for name, rows in cases.items():
            prev = ""
            for r in rows:
                self.assertEqual(dg.row_id(prev, r["row"]), r["id"], name)
                prev = r["id"]
            doc = {"v": 1, "chain": dg.CHAIN, "rows": [dict(r["row"], id=r["id"]) for r in rows], "head": prev}
            self.assertIsNone(dg.chain_error(doc), name)

    def test_valid_and_appended(self):
        old = chain([{"a": 1}, {"a": 2}])
        new = chain([{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertIsNone(dg.chain_error(old))
        self.assertIsNone(dg.chain_extends(old, new))
        self.assertIsNone(dg.chain_extends(chain([]), old))

    def test_an_edited_removed_or_reordered_row_is_caught(self):
        old = chain([{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertIn("lost", dg.chain_extends(old, chain([{"a": 1}, {"a": 2}])))
        self.assertIn("changed", dg.chain_extends(old, chain([{"a": 1}, {"a": 9}, {"a": 3}])))
        self.assertIn("changed", dg.chain_extends(old, chain([{"a": 2}, {"a": 1}, {"a": 3}])))
        edited = json.loads(json.dumps(old))
        edited["rows"][1]["a"] = 9                      # contents edited but the id left alone
        self.assertIn("row 1", dg.chain_error(edited))

    def test_a_wrong_head_or_format_is_invalid(self):
        doc = chain([{"a": 1}])
        doc["head"] = "0" * 20
        self.assertIn("head", dg.chain_error(doc))
        self.assertTrue(dg.chain_error({"v": 2, "rows": []}))
        self.assertTrue(dg.chain_error([]))


class Policies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prev, self.out = os.path.join(self.tmp.name, "prev"), os.path.join(self.tmp.name, "out")
        for root in (self.prev, self.out):
            for rel, obj in good_tree({"_cache/_writer.json": {"formats": {"games": 1, "chain": 1}}}).items():
                dump(os.path.join(root, rel), obj)

    def bad(self, exempt=()):
        return dg.check(self.prev, self.out, {"7"}, exempt)

    def test_an_unchanged_tree_is_safe(self):
        self.assertEqual(self.bad(), [])

    def test_persisted_files_may_not_disappear(self):
        for rel in ("_cache/7-week-1.json", "7/report.json", "_cache/7-games.json"):
            os.remove(os.path.join(self.out, rel))
            self.assertIn("missing now", " ".join(self.bad()), rel)
            dump(os.path.join(self.out, rel), dg_read(self.prev, rel))

    def test_a_report_of_a_league_not_in_leagues_json_carries_no_constraint(self):
        dump(os.path.join(self.prev, "99/report.json"), {})
        self.assertEqual(self.bad(), [])

    def test_broken_json_in_a_policed_file_blocks(self):
        dump(os.path.join(self.out, "_cache/7-odds.json"), "{not json")
        self.assertIn("new copy invalid", " ".join(self.bad()))

    def test_week_files_may_change_but_must_keep_a_known_version(self):
        dump(os.path.join(self.out, "_cache/7-week-1.json"), {"v": 3, "matchups": [1]})
        self.assertEqual(self.bad(), [])
        dump(os.path.join(self.out, "_cache/7-week-1.json"), {"v": 9})
        self.assertIn("version", " ".join(self.bad()))

    def test_a_writer_older_than_the_branch_is_refused(self):
        dump(os.path.join(self.prev, dg.WRITER), {"formats": {"games": 2, "chain": 1}})
        self.assertIn("older than the branch", " ".join(self.bad()))
        dump(os.path.join(self.out, dg.WRITER), {"formats": {"games": 2, "chain": 1, "new": 1}})
        self.assertEqual(self.bad(), [])

    def test_an_unlisted_file_may_be_removed(self):
        os.remove(os.path.join(self.out, "_cache/aaa.html"))
        self.assertEqual(self.bad(), [])

    def test_rewriting_history_blocks_and_a_corrupt_prior_file_blocks(self):
        dump(os.path.join(self.out, "_cache/7-games.json"), chain([{"w": 1, "p": 2}]))
        self.assertIn("history not preserved", " ".join(self.bad()))
        dump(os.path.join(self.prev, "_cache/7-games.json"), "{trunc")
        dump(os.path.join(self.out, "_cache/7-games.json"), chain([{"w": 1}]))
        self.assertIn("prior copy invalid", " ".join(self.bad()))

    def test_an_exempt_path_is_skipped_and_only_that_one(self):
        dump(os.path.join(self.prev, "_cache/7-games.json"), "{trunc")
        dump(os.path.join(self.prev, "_cache/7-odds.json"), "{trunc")
        got = self.bad(exempt={"_cache/7-games.json"})
        self.assertEqual(len(got), 1)
        self.assertIn("7-odds.json", got[0])


def dg_read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


class Remote(unittest.TestCase):
    """Real git against local bare remotes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.bare = os.path.join(self.d, "remote.git")
        git("init", "-q", "--bare", self.bare, cwd=self.d)
        self.url = "file://" + self.bare
        self.repo = os.path.join(self.d, "repo")             # the "checkout": where restore runs
        os.makedirs(self.repo)
        git("init", "-q", cwd=self.repo)
        self.env = dict(os.environ, DATA_REMOTE=self.url, GITHUB_SHA="abc")

    def seed(self, tree, msg="seed"):
        """Commit `tree` as a fresh orphan commit on the remote's data branch (this is what the live workflow does)."""
        w = tempfile.mkdtemp(dir=self.d)
        for rel, obj in tree.items():
            dump(os.path.join(w, rel), obj)
        git("init", "-q", "-b", "data", cwd=w)
        git("add", "-A", cwd=w)
        git("commit", "-q", "-m", msg, cwd=w)
        git("push", "-q", "--force", self.url, "HEAD:refs/heads/data", cwd=w)
        return git("rev-parse", "HEAD", cwd=w)

    def head(self):
        return git("rev-parse", "refs/heads/data", cwd=self.bare, check=False)

    def guard(self, *args, env=None):
        r = subprocess.run([sys.executable, GUARD, *args], cwd=self.repo, capture_output=True, text=True, env=env or self.env)
        return r.returncode, r.stdout.strip(), r.stderr

    def restore(self, *extra):
        return self.guard("restore", "--cache", "cache", "--prev", "prev", *extra)

    def out_from_prev(self):
        out = os.path.join(self.d, "out")
        if os.path.exists(out):
            subprocess.run(["rm", "-rf", out])
        subprocess.run(["cp", "-R", os.path.join(self.repo, "prev"), out], check=True)
        return out

    def publish(self, out, base, *extra, env=None):
        return self.guard("publish", "--out", out, "--prev", "prev", "--cache", "cache", "--base", base, *extra, env=env)


class Restore(Remote):
    def test_restores_the_tree_and_the_cache_and_reports_the_base(self):
        sha = self.seed(good_tree())
        rc, out, err = self.restore()
        self.assertEqual((rc, out), (0, "BASE=" + sha), err)
        self.assertEqual(json.loads(dg_read(self.repo, "prev/7/report.json")), {"schemaVersion": 3})
        self.assertTrue(os.path.exists(os.path.join(self.repo, "cache/_cache/7-games.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "cache/7")))     # only _cache goes to the cache dir

    def test_a_restore_replaces_what_a_failed_pass_left_behind(self):
        self.seed(good_tree())
        dump(os.path.join(self.repo, "cache/_cache/stray.json"), {})
        dump(os.path.join(self.repo, "prev/stray.json"), {})
        self.assertEqual(self.restore()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "cache/_cache/stray.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "prev/stray.json")))

    def test_a_branch_that_does_not_exist_yet_is_a_clean_start(self):
        rc, out, _ = self.restore()
        self.assertEqual((rc, out), (0, "BASE="))
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "prev")))

    def test_an_unreachable_remote_is_transient_never_a_clean_start(self):
        rc, out, _ = self.restore("--remote", "file://" + os.path.join(self.d, "nope.git"))
        self.assertEqual((rc, out), (3, ""))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "prev")))

    def test_a_corrupt_protected_file_is_an_integrity_failure_and_nothing_is_installed(self):
        self.seed(good_tree({"_cache/7-games.json": "{trunc"}))
        rc, out, err = self.restore()
        self.assertEqual((rc, out), (4, ""))
        self.assertIn("7-games.json", err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "prev")))

    def test_quarantine_exempts_only_the_named_file_at_restore(self):
        self.seed(good_tree({"_cache/7-games.json": "{trunc"}))
        self.assertEqual(self.restore("--quarantine", "_cache/7-games.json")[0], 0)
        self.seed(good_tree({"_cache/7-games.json": "{trunc", "_cache/7-odds.json": "{trunc"}))
        self.assertEqual(self.restore("--quarantine", "_cache/7-games.json")[0], 4)

    def test_the_extracted_tree_must_match_the_commit_exactly(self):
        sha = self.seed(good_tree())
        entries = subprocess.run(["git", "ls-tree", "-r", "-l", "-z", sha], cwd=self.bare, capture_output=True)
        self.assertTrue(entries.returncode == 0)
        os.chdir(self.bare)
        self.addCleanup(os.chdir, ROOT)
        ents = dg.manifest(sha)
        tree = os.path.join(self.d, "tree")
        for rel, obj in good_tree().items():
            dump(os.path.join(tree, rel), obj)
        self.assertIsNone(dg.verify(tree, ents))
        p = os.path.join(tree, "_cache/aaa.html")
        dump(p, "<HTML>")                                                   # same size, other bytes
        self.assertIn("blob id", dg.verify(tree, ents))
        dump(p, "<html>+")
        self.assertIn("size", dg.verify(tree, ents))
        os.remove(p)
        self.assertIn("file list", dg.verify(tree, ents))
        dump(p, "<html>")
        dump(os.path.join(tree, "extra.json"), {})
        self.assertIn("file list", dg.verify(tree, ents))


class Publish(Remote):
    def test_the_first_publish_creates_the_branch_and_a_second_blind_one_is_rejected(self):
        self.assertEqual(self.restore()[1], "BASE=")
        out = self.out_from_prev()
        dump(os.path.join(out, "7/report.json"), {"n": 1})
        rc, so, err = self.publish(out, "")
        self.assertEqual(rc, 0, err)
        self.assertEqual(so, "BASE=" + self.head())
        out2 = self.out_from_prev()
        rc, so, err = self.publish(out2, "")                 # still believes the branch is absent
        self.assertEqual((rc, so), (5, ""))
        self.assertIn("LEASE REJECTED", err)

    def test_a_publish_advances_the_base_and_writes_the_writer_stamp(self):
        sha = self.seed(good_tree())
        self.assertEqual(self.restore()[1], "BASE=" + sha)
        out = self.out_from_prev()
        dump(os.path.join(out, "_cache/7-games.json"), chain([{"w": 1, "p": 2}, {"w": 1, "p": 3}, {"w": 2, "p": 1}]))
        rc, so, err = self.publish(out, sha)
        self.assertEqual((rc, so), (0, "BASE=" + self.head()), err)
        self.assertNotEqual(self.head(), sha)
        stamp = json.loads(git("show", "data:" + dg.WRITER, cwd=self.bare))
        self.assertEqual((stamp["code"], stamp["formats"]), ("abc", dg.FORMATS))
        self.assertEqual(len(json.loads(git("show", "data:_cache/7-games.json", cwd=self.bare))["rows"]), 3)

    def test_a_competing_push_is_never_overwritten(self):
        sha = self.seed(good_tree())
        self.restore()
        out = self.out_from_prev()
        rival = self.seed(good_tree({"_cache/rival.json": {"x": 1}}), "rival")
        rc, so, err = self.publish(out, sha)
        self.assertEqual((rc, so), (5, ""))
        self.assertEqual(self.head(), rival)

    def test_a_history_violation_blocks_and_the_remote_is_untouched(self):
        sha = self.seed(good_tree())
        self.restore()
        out = self.out_from_prev()
        dump(os.path.join(out, "_cache/7-games.json"), chain([{"w": 1, "p": 2}]))        # a row lost
        rc, so, err = self.publish(out, sha)
        self.assertEqual(rc, 4)
        self.assertIn("history not preserved", err)
        self.assertEqual(self.head(), sha)

    def test_an_unreachable_remote_is_transient(self):
        sha = self.seed(good_tree())
        self.restore()
        rc, _, _ = self.publish(self.out_from_prev(), sha, "--remote", "file://" + os.path.join(self.d, "nope.git"))
        self.assertEqual(rc, 3)
        self.assertEqual(self.head(), sha)

    def test_the_token_is_never_printed(self):
        sha = self.seed(good_tree())
        self.restore()
        env = dict(self.env, GITHUB_TOKEN="s3cr3t-token")
        rc, so, err = self.publish(self.out_from_prev(), sha, "--remote", "file://%s/s3cr3t-token@nowhere" % self.d, env=env)
        self.assertEqual(rc, 3)
        self.assertNotIn("s3cr3t-token", so + err)

    def test_quarantine_keeps_the_bytes_exempts_only_that_file_and_starts_it_afresh(self):
        corrupt = "{truncé"
        sha = self.seed(good_tree({"_cache/7-games.json": corrupt}))
        q = ("--quarantine", "_cache/7-games.json")
        self.assertEqual(self.restore(*q)[0], 0)
        dump(os.path.join(self.repo, "cache/_cache/7-games.json"), corrupt)
        out = self.out_from_prev()
        rc, so, err = self.publish(out, sha, *q)
        self.assertEqual(rc, 0, err)
        names = git("ls-tree", "-r", "--name-only", "data", cwd=self.bare).split("\n")
        kept = [n for n in names if n.startswith("_quarantine/")]
        self.assertEqual(len(kept), 1)
        self.assertEqual(git("show", "data:" + kept[0], cwd=self.bare), corrupt)
        self.assertNotIn("_cache/7-games.json", names)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "cache/_cache/7-games.json")))
        # a second pass in the same run (prev now lacks the file) is still fine
        rc, _, err = self.publish(self.out_from_prev(), self.head(), *q)
        self.assertEqual(rc, 0, err)

    def test_quarantine_does_not_excuse_another_broken_file(self):
        sha = self.seed(good_tree({"_cache/7-games.json": "{trunc"}))
        self.restore("--quarantine", "_cache/7-games.json")
        out = self.out_from_prev()
        dump(os.path.join(out, "_cache/7-odds.json"), "{broken")
        self.assertEqual(self.publish(out, sha, "--quarantine", "_cache/7-games.json")[0], 4)

    def test_quarantine_must_be_a_plain_file_under_cache(self):
        for bad in ("../x", "_cache/../x", "7/report.json", "_cache/a/b.json"):
            rc, _, err = self.restore("--quarantine", bad)
            self.assertNotEqual(rc, 0, bad)


class Alerts(unittest.TestCase):
    def run_alert(self, existing):
        with tempfile.TemporaryDirectory() as d:
            gh = os.path.join(d, "gh")
            dump(gh, '#!/bin/sh\necho "$@" >> "$GH_LOG"\n[ "$1 $2" = "issue list" ] && echo "$GH_EXISTING"\nexit 0\n')
            os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
            env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], GH_LOG=os.path.join(d, "log"), GH_EXISTING=existing,
                       GITHUB_STEP_SUMMARY=os.path.join(d, "summary"), GITHUB_REPOSITORY="o/r", GITHUB_RUN_ID="42")
            r = subprocess.run([sys.executable, GUARD, "alert", "publish", "blocked:", "lost", "a", "row"], capture_output=True, text=True, env=env)
            return r, [x for x in dg_read(d, "log").splitlines() if x.startswith("issue ")], dg_read(d, "summary")   # the body spans lines

    def test_opens_one_issue_when_there_is_none(self):
        r, log, summary = self.run_alert("")
        self.assertEqual(r.returncode, 0)
        self.assertIn("::error title=Roto publish blocked::publish blocked: lost a row", r.stdout)
        self.assertIn("lost a row", summary)
        self.assertTrue(log[0].startswith("issue list"))
        self.assertTrue(log[1].startswith("issue create --title Roto publish blocked"), log)

    def test_comments_on_the_open_issue_instead_of_opening_another(self):
        _, log, _ = self.run_alert("7")
        self.assertEqual(len(log), 2)
        self.assertTrue(log[1].startswith("issue comment 7 --body"), log)

    def test_a_missing_gh_does_not_fail_the_run(self):
        env = dict(os.environ, PATH="/nonexistent")
        r = subprocess.run([sys.executable, GUARD, "alert", "x"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
