#!/usr/bin/env python3
"""Daily health check of the whole chain against the real Yahoo pages: python3 canary.py LEAGUE_ID

Fetches one league the way the live workflow does and checks that what comes back still makes sense (categories found, a sensible number of teams, at least one week
with stats, every team has a value in every category). If Yahoo changes its markup the parsers usually do not crash, they quietly return less, and the page just
looks stale; this makes that loud: the exit status is 1 and the problems are printed, so the scheduled workflow fails and GitHub emails the owner."""
from __future__ import annotations

import sys

import yahoo_roto as yr


def check(doc):
    """-> a list of problems with a report (empty = healthy)."""
    problems = []
    cats = doc.get("categories") or []
    teams = doc.get("teams") or {}
    if len(cats) < 3:
        problems.append("only %d scoring categories could be read (expected at least 3)" % len(cats))
    if len(teams) < 4:
        problems.append("only %d teams found (expected at least 4)" % len(teams))
    if not doc.get("weeks"):
        problems.append("no week with stats")
        return problems
    season = (doc.get("views") or {}).get("season") or {}
    for tid in teams:
        vals = ((season.get("teams") or {}).get(tid) or {}).get("values") or {}
        missing = [c["cat"] for c in cats if vals.get(c["cat"]) is None]
        if missing:
            problems.append("team %s has no value for %s" % (teams[tid], ", ".join(missing)))
    if doc.get("skipped"):
        problems.append("categories skipped (not computable): %s" % ", ".join(doc["skipped"]))
    return problems


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        doc = yr.report(yr.check_league(a[0]))
    except yr.RotoError as e:
        print("FAILED: %s" % e)
        return 1
    problems = check(doc)
    for p in problems:
        print("PROBLEM: %s" % p)
    if not problems:
        print("OK: %d categories, %d teams, weeks %s" % (len(doc["categories"]), len(doc["teams"]), doc["weeks"]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
