#!/usr/bin/env python3
"""Roto standings for any PUBLICLY VIEWABLE Yahoo fantasy league, from its league id. Standard library only, read-only, no sign-in.

    python3 yahoo_roto.py 85092                      # season roto: every week with data, categories read from the league's settings
    python3 yahoo_roto.py 85092 --week 3             # one week only
    python3 yahoo_roto.py 85092 --through 3 --json   # weeks 1-3, machine-readable
    python3 yahoo_roto.py 85092 --cache .cache       # keep fetched pages: finished weeks are never fetched twice

How it works: the league's public settings page gives the scoring type and the categories; the standings page gives the teams; each team's
weekly matchup page ("totals" view) gives that week's category totals for it and its opponent. Season roto adds the weekly totals and ranks
the teams in every category (worst = 1 point, best = number of teams; level teams share the average place; fewer is better for TO / PF).
Percentage categories are computed from the summed makes and attempts, never by averaging percentages.

Limits, stated plainly: a league has to be viewable without a login (Yahoo's "Make League Publicly Viewable"). Counting categories and made/attempted
percentages are supported (points, rebounds, FG%, FT% ...); ratio categories such as ERA/WHIP are reported and skipped. The league is read as
head-to-head weekly pages, so a pure-roto league (no weekly matchups) is detected and refused rather than guessed. Roto here is derived and
display-only: it is not a Yahoo number. Be polite: one request per 1.5 s by default.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from fractions import Fraction
from html.parser import HTMLParser

SPORTS = {"nba": "basketball.fantasysports.yahoo.com/nba", "nfl": "football.fantasysports.yahoo.com/f1", "mlb": "baseball.fantasysports.yahoo.com/b1",
          "nhl": "hockey.fantasysports.yahoo.com/hockey"}
LOWER_IS_BETTER = {"TO", "PF", "DQ", "GA", "GAA", "ERA", "WHIP", "BB"}
UA = "yahoo-roto/1.0 (read-only; public pages)"
RETRIES = 2                                                              # extra attempts for a request that failed in a way that may pass (timeout, 5xx, 429)
BACKOFF = (2, 6)                                                         # seconds to wait before the 2nd and 3rd attempt
TTL = {"settings": 12 * 3600, "standings": 6 * 3600, "weeks": 6 * 3600}   # pages that hardly ever change are not fetched on every pass
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class RotoError(RuntimeError):
    pass


# ------------------------------------------------------------------ fetching
def write_atomic(path, text):
    """Write a file so that a run killed half-way never leaves a truncated file behind (the cache is carried between runs)."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class Fetcher:
    """GET with a polite delay, a few retries for failures that may pass, and an optional on-disk copy of slow-changing pages (`ttl` seconds)."""

    def __init__(self, delay=1.5, cache=None, opener=None, sleep=time.sleep):
        self.delay, self.cache, self.last = delay, cache, 0.0
        self.opener, self.sleep = opener or urllib.request.urlopen, sleep

    def _path(self, url):
        return os.path.join(self.cache, hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url, ttl=None):
        path = self._path(url) if self.cache and ttl else None
        if path and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except (OSError, ValueError):
                pass                                                    # unreadable copy: fetch again
        body = self._fetch(url)
        if path:
            write_atomic(path, body)
        return body

    def _fetch(self, url):
        problem = None
        for attempt in range(RETRIES + 1):
            if attempt:
                self.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)] if problem is None or problem[1] is None else problem[1])
            wait = self.delay - (time.time() - self.last)
            if wait > 0:
                self.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            try:
                with self.opener(req, timeout=30) as r:
                    body, final = r.read().decode("utf-8", "replace"), r.geturl()
            except urllib.error.HTTPError as e:
                retry_after = None
                try:
                    retry_after = min(int(e.headers.get("Retry-After", "")), 60) if e.headers else None
                except (TypeError, ValueError):
                    pass
                if e.code in (403, 429, 999):
                    problem = ("Yahoo refused the request (HTTP %s): it may be rate limiting or blocking this address; the next pass will try again" % e.code, retry_after)
                elif e.code >= 500:
                    problem = ("%s answered HTTP %s" % (url, e.code), retry_after)
                else:
                    raise RotoError("%s answered HTTP %s" % (url, e.code))
                if e.code == 403:
                    raise RotoError(problem[0])                          # a block will not clear in a few seconds: do not hammer
            except (urllib.error.URLError, OSError) as e:                # timeouts and dropped connections
                problem = ("could not reach %s (%s)" % (url, getattr(e, "reason", e)), None)
            else:
                if "login.yahoo.com" in final or "/login" in final.split("?")[0]:
                    raise RotoError("this league is not publicly viewable (Yahoo asked for a sign-in). Only public leagues can be read; "
                                    "a commissioner can turn on 'Make League Publicly Viewable' in the league settings.")
                return body
            finally:
                self.last = time.time()
        raise RotoError(problem[0])


# ------------------------------------------------------------------ a tiny element tree
class El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, dict(attrs), [], parent

    def text(self):
        out = []

        def walk(e):
            for k in e.kids:
                out.append(k) if isinstance(k, str) else walk(k)
        walk(self)
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def find_all(self, pred):
        res = []

        def walk(e):
            for k in e.kids:
                if isinstance(k, El):
                    if pred(k):
                        res.append(k)
                    walk(k)
        walk(self)
        return res


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = El(tag, [(k, v or "") for k, v in attrs], self.cur)
        self.cur.kids.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(El(tag, [(k, v or "") for k, v in attrs], self.cur))

    def handle_endtag(self, tag):
        e = self.cur
        while e is not None and e.tag != tag:
            e = e.parent
        if e is not None and e.parent is not None:
            self.cur = e.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse_tree(html):
    t = _Tree()
    t.feed(html)
    t.close()
    return t.root


def page_text(html):
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ")


# ------------------------------------------------------------------ settings, teams, weekly totals
def parse_settings(html):
    """-> {"scoring": "Head-to-Head - Categories" | ..., "categories": ["FG%", ...], "public": bool|None}"""
    t = page_text(html)
    m = re.search(r"Scoring Type:\s*(.+?)\s+(?:Max Acquisitions|Max Trades|Trade End|Allow|Waiver|Roster)", t)
    c = re.search(r"Stat Categories:\s*(.+?)\s+(?:Stat Modifiers|Roster Positions|Max |Minimum|Games|Lineup|League|Waiver|Trade)", t)
    cats = re.findall(r"\(([A-Z0-9%/+\-]+)\)", c.group(1)) if c else []
    pub = re.search(r"Make League Publicly Viewable:\s*(Yes|No)", t)
    nm = re.search(r"League Name:\s*(.+?)\s+(?:League Logo|Auto-renew|Custom|Draft|Scoring Type|Max )", t)
    po = re.search(r"Playoffs:\s*(\d+)\s*teams?\s*-\s*Weeks?\s*(\d+)", t)            # "Playoffs: 6 teams - Week 19, 20 and 21": the regular season ends the week before
    seeding = re.search(r"Playoff Seeding Options:\s*(.+?)\s+(?:Lock Benched|IL-eligible|Make League|Invite)", t)
    return {"scoring": m.group(1).strip() if m else None, "categories": cats, "public": (pub.group(1) == "Yes") if pub else None,
            "name": nm.group(1).strip() if nm else None, "playoff_teams": int(po.group(1)) if po else None, "playoff_start": int(po.group(2)) if po else None,
            "div_winners": bool(seeding and "Division winners advance" in seeding.group(1))}


def parse_teams(html, league):
    """-> {teamId: name} from the standings page (the rows of any table that has a Team column)."""
    out = {}
    for tb in parse_tree(html).find_all(lambda e: e.tag == "table"):
        heads = [th.text() for th in tb.find_all(lambda e: e.tag == "th")]
        if "Team" not in heads:
            continue
        for a in tb.find_all(lambda e: e.tag == "a" and re.search(r"/%s/(\d+)/?$" % re.escape(str(league)), e.attrs.get("href", "")) and e.text()):
            out.setdefault(int(re.search(r"/(\d+)/?$", a.attrs["href"]).group(1)), a.text())
    return out


def parse_divisions(html, league):
    """{teamId: division name} from the standings page, where each division is a heading (<h4>) above its rows; {} when the league has no divisions."""
    out, cur = {}, None
    for part in re.split(r"(<h4[^>]*>.*?</h4>)", html, flags=re.S):
        m = re.fullmatch(r"<h4[^>]*>(.*?)</h4>", part, re.S)
        if m:
            cur = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
            continue
        if cur is not None:
            for tid in re.findall(r'href="[^"]*/%s/(\d+)/?"' % re.escape(str(league)), part):
                out.setdefault(int(tid), cur)
    return out if len(set(out.values())) > 1 else {}


def _num(s):
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "--"):
        return None
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


def _made_att(s):
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_week(html, league):
    """One matchup page (totals view) -> {"week": n, "weeks": [...], "pair": [teamId, teamId], "teams": {teamId: {"name", "cols": {header: value}, "score"}}}.
    A made/attempted column ("FGM/A*") is kept as a (made, att) pair; every other column as an exact number, None when Yahoo shows '-'.
    "score" is the page's last, unnamed column: the category wins that team has this week. "pair" is the two teams that played each other (a matchup
    page shows exactly the two sides of one matchup)."""
    root = parse_tree(html)
    week, weeks = None, []
    for o in root.find_all(lambda e: e.tag == "option"):
        m = re.search(r"[?&]week=(\d+)", o.attrs.get("value", ""))
        if m and "module=matchup" in o.attrs.get("value", ""):
            weeks.append(int(m.group(1)))
            if "selected" in o.attrs:
                week = int(m.group(1))
    for tb in root.find_all(lambda e: e.tag == "table"):
        heads = [th.text() for th in tb.find_all(lambda e: e.tag == "th")]
        if "Team" not in heads or not any(h.endswith("M/A*") for h in heads):
            continue
        teams = {}
        for tr in tb.find_all(lambda e: e.tag == "tr"):
            tds = [c for c in tr.kids if isinstance(c, El) and c.tag == "td"]
            if not tds:
                continue
            link = [a for a in tds[0].find_all(lambda e: e.tag == "a") if re.search(r"/%s/(\d+)" % re.escape(str(league)), e_href(a))]
            if not link:
                continue
            tid = int(re.search(r"/%s/(\d+)" % re.escape(str(league)), e_href(link[0])).group(1))
            name = next((a.text() for a in link if a.text()), "")
            cols, score = {}, None
            for i, (h, td) in enumerate(zip(heads[1:], tds[1:]), 1):
                if h:
                    cols[h] = _made_att(td.text()) if h.endswith("M/A*") else _num(td.text())
                elif i == len(heads) - 1:
                    score = _num(td.text())
            teams[tid] = {"name": name, "cols": cols, "score": score}
        if teams:
            return {"week": week, "weeks": sorted(set(weeks)), "pair": list(teams) if len(teams) == 2 else [], "teams": teams}
    raise RotoError("no matchup table found on the page (is this a head-to-head league with matchups?)")


def e_href(a):
    return a.attrs.get("href", "")


# ------------------------------------------------------------------ categories and roto math
def plan(categories, headers):
    """Decide, for each scoring category, how to compute it from the matchup columns.
    -> ([{"cat", "kind": "count"|"pct", "col", "num"/"den" cols, "lower"}], [skipped categories])"""
    out, skipped = [], []
    hs = [h for h in headers if h]
    for cat in categories:
        if cat in hs and not cat.endswith("M/A*"):
            if cat.endswith("%"):
                i = hs.index(cat)
                if i > 0 and hs[i - 1].endswith("M/A*"):
                    out.append({"cat": cat, "kind": "pct", "col": hs[i - 1], "lower": cat in LOWER_IS_BETTER})
                else:
                    skipped.append(cat)
            elif cat in ("ERA", "WHIP", "AVG", "OBP", "SLG", "OPS", "K/9", "SV+H"):
                skipped.append(cat)
            else:
                out.append({"cat": cat, "kind": "count", "col": cat, "lower": cat in LOWER_IS_BETTER})
        else:
            skipped.append(cat)
    return out, skipped


def add(a, b):
    if a is None or b is None:
        return None
    return (a[0] + b[0], a[1] + b[1]) if isinstance(a, tuple) else a + b


def totals(weeks_data, teams):
    """Sum the weekly columns per team over the weeks given: {teamId: {col: value}}. A week where a team has no value for a column adds nothing."""
    tot = {t: {} for t in teams}
    for wk in weeks_data:
        for tid, rec in wk["teams"].items():
            for h, v in rec["cols"].items():
                if v is None:
                    continue
                cur = tot.setdefault(tid, {}).get(h)
                tot[tid][h] = v if cur is None else add(cur, v)
    return tot


def cat_value(stats, spec):
    v = stats.get(spec["col"])
    if v is None:
        return None
    if spec["kind"] == "pct":
        return Fraction(v[0], v[1]) if v[1] else None
    return v


def places(values, lower):
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=lower)
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in order[i:j + 1]:
            out[k] = (i + 1 + j + 1) / 2
        i = j + 1
    return out


def roto(stats_by_team, specs):
    ids = sorted(stats_by_team)
    res = {t: {"points": {}, "total": 0.0} for t in ids}
    for sp in specs:
        vals = [cat_value(stats_by_team[t], sp) for t in ids]
        if any(v is None for v in vals):
            for t in ids:
                res[t]["points"][sp["cat"]] = None
            continue
        for k, p in places(vals, sp["lower"]).items():
            res[ids[k]]["points"][sp["cat"]] = p
            res[ids[k]]["total"] += p
    ranked = sorted(ids, key=lambda t: -res[t]["total"])
    for t in ids:
        res[t]["rank"] = 1 + sum(1 for o in ids if res[o]["total"] > res[t]["total"])
    return res, ranked


# Categories left out of the Category Kings board only: a tanking or AFK team racks up few turnovers, so leading TO says nothing about skill.
# (Every other board, Category Luck included, still counts all categories.)
KINGS_SKIP = ("TO",)


# ------------------------------------------------------------------ the run
def cat_result(x, y, sp):
    """One category, x against y: 1 = x wins, 0 = level, -1 = x loses (fewer is better for a `lower` category)."""
    if x == y:
        return 0
    return 1 if (x < y) == sp["lower"] else -1


def head_to_head(a, b, specs):
    r = [0, 0, 0]
    for sp in specs:
        x, y = cat_value(a, sp), cat_value(b, sp)
        if x is None or y is None:
            continue
        r[{1: 0, -1: 1, 0: 2}[cat_result(x, y, sp)]] += 1
    return r


def cat_play(stats_by_team, specs):
    """Per team and category, the share of the other teams it would have beaten (a level team counts half): {team: {cat: Fraction}}.
    This is the expected category win of that team that week; a category with a missing value is left out."""
    ids = sorted(stats_by_team)
    out = {t: {} for t in ids}
    for sp in specs:
        vals = {t: cat_value(stats_by_team[t], sp) for t in ids}
        if any(v is None for v in vals.values()) or len(ids) < 2:
            continue
        for t in ids:
            pts = sum(Fraction(cat_result(vals[t], vals[o], sp) + 1, 2) for o in ids if o != t)
            out[t][sp["cat"]] = pts / (len(ids) - 1)
    return out


def all_play(stats_by_team, specs):
    """Every team against every other, category by category: {a: {b: [w, l, t]}} and each team's [W, L, T] record (a cell is won with more category wins)."""
    ids = sorted(stats_by_team)
    cells = {a: {b: head_to_head(stats_by_team[a], stats_by_team[b], specs) for b in ids if b != a} for a in ids}
    rec = {}
    for a in ids:
        r = [0, 0, 0]
        for c in cells[a].values():
            r[0 if c[0] > c[1] else 1 if c[0] < c[1] else 2] += 1
        rec[a] = r
    return cells, rec


def _enc(v):
    return list(v) if isinstance(v, tuple) else (None if v is None else str(v))


def _dec(v):
    return tuple(v) if isinstance(v, list) else (None if v is None else Fraction(v))


def _cache_path(cache, league, week):
    return os.path.join(cache, "%s-week-%d.json" % (league, week)) if cache else None


# Stat corrections: Yahoo and the NBA fix box scores for a day or two after a game. A finished week is kept in the cache but checked again at these ages
# (seconds since it was first stored): soon after, the next morning, and over the following two days. A changed total replaces the cached week and is recorded.
CHECK_AGES = (3600, 6 * 3600, 24 * 3600, 48 * 3600)
KEEP_CORRECTIONS = 14 * 86400


def _cache_get(cache, league, week):
    p = _cache_path(cache, league, week)
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("v") not in (2, 3):                                # an older file without Score / matchups: fetch again
                return None
            meta = {"finalized": d.get("finalized", 0), "checks": d.get("checks", len(CHECK_AGES))}     # a v2 file predates re-checking: leave it alone
            return {"week": week, "matchups": d["matchups"], "_meta": meta,
                    "teams": {int(t): {"name": r["name"], "score": _dec(r["score"]), "cols": {h: _dec(v) for h, v in r["cols"].items()}} for t, r in d["teams"].items()}}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
            print("note: the cached copy of week %s is damaged; fetching it again" % week, file=sys.stderr)        # never let one bad file stop a league for good
    return None


def _cache_put(cache, league, wk, finalized=None, checks=0):
    p = _cache_path(cache, league, wk["week"])
    if p:
        write_atomic(p, json.dumps({"v": 3, "finalized": time.time() if finalized is None else finalized, "checks": checks, "matchups": wk.get("matchups", []),
                                    "teams": {str(t): {"name": r["name"], "score": _enc(r.get("score")), "cols": {h: _enc(v) for h, v in r["cols"].items()}}
                                              for t, r in wk["teams"].items()}}))


def collect_week(fx, league, week, team_ids, base):
    """All teams' totals for one week, walking only as many matchup pages as needed (each page covers two teams)."""
    got, pairs = {}, []
    for tid in team_ids:
        if tid in got:
            continue
        parsed = parse_week(fx.get("%s/matchup?date=totals&week=%d&mid1=%d" % (base, week, tid)), league)
        if parsed["week"] not in (None, week):
            raise RotoError("asked for week %d but Yahoo showed week %s" % (week, parsed["week"]))
        got.update(parsed["teams"])
        if parsed["pair"] and sorted(parsed["pair"]) not in pairs:
            pairs.append(sorted(parsed["pair"]))
        if not has_data({"teams": got}):                                # a week that has not started: the first page says so, skip the other pages
            break
    return {"week": week, "teams": got, "matchups": pairs}


def has_data(wk):
    return any(v is not None for rec in wk["teams"].values() for v in rec["cols"].values())


def week_changed(a, b):
    """True when two reads of the same week differ in any team's total or Score."""
    if set(a["teams"]) != set(b["teams"]):
        return True
    return any(a["teams"][t]["cols"] != b["teams"][t]["cols"] or a["teams"][t].get("score") != b["teams"][t].get("score") for t in a["teams"])


def check_league(league):
    """The league id goes into URLs and file names: digits only."""
    if not re.fullmatch(r"[0-9]{1,12}", str(league)):
        raise RotoError("the league id must be the number in the league's URL (digits only), got %r" % (league,))
    return str(league)


def load(league, cache=None, delay=1.5, sport="nba", only_week=None, through=None, now=None, fixes=None):
    """-> (settings, teams {id: name}, weeks_data [{week, teams}], in_progress_week or None). Weeks are read in order and the walk stops at the first
    week with no stats. A week is kept in the cache only once a later week has stats (it is then final); the newest week is always fetched again."""
    league = check_league(league)
    base = "https://%s/%s" % (SPORTS[sport], league)
    fx = Fetcher(delay=delay, cache=cache)
    st = parse_settings(fx.get(base + "/settings", ttl=TTL["settings"]))
    if st["scoring"] is None and not st["categories"]:
        raise RotoError("could not read league %s's public settings: it does not exist or it is not publicly viewable (Yahoo shows a generic "
                        "error page). Only public leagues can be read; a commissioner can turn on 'Make League Publicly Viewable' in the settings." % league)
    if st["scoring"] and "Head-to-Head" not in st["scoring"]:
        raise RotoError("this league's scoring type is %r; only head-to-head leagues (weekly matchup pages) are supported" % st["scoring"])
    stand = fx.get(base + "?lhst=stand", ttl=TTL["standings"])
    teams = parse_teams(stand, league)
    st["divisions"] = {t: d for t, d in parse_divisions(stand, league).items() if t in teams}
    if len(teams) < 2:
        raise RotoError("could not read the teams from the standings page")
    ids = sorted(teams)
    first = parse_week(fx.get("%s/matchup?date=totals&week=1&mid1=%d" % (base, ids[0]), ttl=TTL["weeks"]), league)
    all_weeks = first["weeks"] or [1]
    limit = min(only_week or 10 ** 6, through or 10 ** 6)
    weeks_data, stored = [], set()
    for w in [x for x in all_weeks if x <= limit]:
        wk = _cache_get(cache, league, w)
        if wk:
            stored.add(w)
        else:
            wk = collect_week(fx, league, w, ids, base)
        if not has_data(wk):
            break
        weeks_data.append(wk)
    t_now = time.time() if now is None else now
    for i, wk in enumerate(weeks_data[:-1]):                            # final: a later week already has stats
        if wk["week"] not in stored:
            _cache_put(cache, league, wk, finalized=t_now)
        elif cache and only_week is None and (wk.get("_meta") or {}).get("checks", len(CHECK_AGES)) < len(CHECK_AGES):
            meta = wk["_meta"]
            if t_now - meta["finalized"] >= CHECK_AGES[meta["checks"]]:      # due for another look: did Yahoo change anything?
                try:
                    fresh = collect_week(fx, league, wk["week"], ids, base)
                except RotoError as e:                                   # the check is best effort: a failed look must not stop the report; it is tried again next pass
                    print("note: could not re-check week %d (%s)" % (wk["week"], e), file=sys.stderr)
                    continue
                if has_data(fresh) and week_changed(wk, fresh):
                    if fixes is not None:
                        fixes.append({"week": wk["week"], "old": wk, "new": fresh, "at": t_now})
                    weeks_data[i] = fresh
                    wk = fresh
                _cache_put(cache, league, wk, finalized=meta["finalized"], checks=meta["checks"] + 1)
    if only_week:
        weeks_data = [wk for wk in weeks_data if wk["week"] == only_week]
        if not weeks_data:
            raise RotoError("week %d has no stats yet" % only_week)
    if not weeks_data:
        raise RotoError("no week with stats yet")
    return st, teams, weeks_data, base


def win_pct(rec):
    """All-play Win% = (W + T/2) / (W + L + T), exact; None before any game."""
    n = sum(rec)
    return Fraction(2 * rec[0] + rec[2], 2 * n) if n else None


def comp_rank(vals, high=True):
    """Competition rank of {key: number}: the best is 1, level keys share a rank and the next rank is skipped (1, 2, 2, 4). None -> None."""
    ok = {k: v for k, v in vals.items() if v is not None}
    return {k: (None if v is None else 1 + sum(1 for o in ok.values() if (o > v if high else o < v))) for k, v in vals.items()}


def _core(wk, specs):
    tot = totals([wk], wk["teams"])
    res, _ = roto(tot, specs)
    cells, rec = all_play(tot, specs)
    return {"week": wk["week"], "tot": tot, "res": res, "cells": cells, "rec": rec}


def _teams_block(ids, specs, tot, res, rec):
    return {str(t): {"rank": res[t]["rank"], "total": res[t]["total"], "points": res[t]["points"], "allPlay": rec[t], "winPct": _plain(win_pct(rec[t])),
                     "values": {sp["cat"]: _plain(cat_value(tot[t], sp)) for sp in specs}} for t in ids}


def _orders(ids, res, rec):
    """Roto and Raw views: roto total (ties keep team-id order, share the rank). All-Play: Win%, then roto total."""
    roto_order = sorted(ids, key=lambda t: (-res[t]["total"], t))
    ap_order = sorted(ids, key=lambda t: (-(win_pct(rec[t]) or 0), -res[t]["total"], t))
    return roto_order, ap_order


def _matrix(cells):
    return {str(a): {str(b): c for b, c in row.items()} for a, row in cells.items()}


def _week_view(core, wk, specs, ids):
    res, rec = core["res"], core["rec"]
    ro, ap = _orders(ids, res, rec)
    teams = _teams_block(ids, specs, core["tot"], res, rec)
    for t in ids:
        teams[str(t)]["score"] = _plain(wk["teams"][t].get("score")) if t in wk["teams"] else None
        # made/attempts of the percentage categories: the page re-adds weeks into any range (a ratio cannot be summed from its value)
        teams[str(t)]["raw"] = {sp["cat"]: list(core["tot"][t][sp["col"]]) for sp in specs if sp["kind"] == "pct" and core["tot"].get(t, {}).get(sp["col"]) is not None}
    return {"label": "Week %d" % wk["week"], "weeks": [wk["week"]], "order": ro, "allPlayOrder": ap, "teams": teams, "matrix": _matrix(core["cells"]),
            "matchups": wk.get("matchups", [])}


def _season_view(cores, weeks_data, specs, ids):
    """Season roto ranks the summed category totals. The season All-Play record and matrix add up the weekly ones (no Score, no actual-matchup marker)."""
    tot = totals(weeks_data, ids)
    res, _ = roto(tot, specs)
    rec = {t: [sum(c["rec"][t][i] for c in cores) for i in range(3)] for t in ids}
    cells = {a: {b: [sum(c["cells"][a][b][i] for c in cores) for i in range(3)] for b in ids if b != a} for a in ids}
    ro, ap = _orders(ids, res, rec)
    ws = [w["week"] for w in weeks_data]
    return {"label": "Season, weeks %s" % (("%d-%d" % (ws[0], ws[-1])) if len(ws) > 1 else ws[0]), "weeks": ws, "order": ro, "allPlayOrder": ap,
            "teams": _teams_block(ids, specs, tot, res, rec), "matrix": _matrix(cells)}


def composites(weeks_data, cores, specs, ids, season):
    """The season boards, derived only from the weekly data already fetched. `season` is the season view."""
    wk_by = {w["week"]: w for w in weeks_data}
    weeks = [w["week"] for w in weeks_data]
    weekly = {str(t): {} for t in ids}
    for c in cores:
        wk = wk_by[c["week"]]
        opp = {}
        for a, b in wk.get("matchups", []):
            opp[a], opp[b] = b, a
        for t in ids:
            sc = wk["teams"].get(t, {}).get("score")
            o = opp.get(t)
            osc = wk["teams"].get(o, {}).get("score") if o is not None else None
            result = None if sc is None or osc is None else "W" if sc > osc else "L" if sc < osc else "T"
            weekly[str(t)][str(c["week"])] = {"points": c["res"][t]["points"], "total": c["res"][t]["total"], "rank": c["res"][t]["rank"], "allPlay": c["rec"][t],
                                              "winPct": _plain(win_pct(c["rec"][t])), "score": _plain(sc), "opp": o, "result": result,
                                              "catRecord": head_to_head(c["tot"][t], c["tot"][o], specs) if result else None}
    # 1 season roto (the headline board: the season view)
    seasonRoto = {str(t): {"total": season["teams"][str(t)]["total"], "rank": season["teams"][str(t)]["rank"]} for t in ids}
    # 2 weekly roto points: the sum of each week's roto total
    sums = {t: sum(Fraction(weekly[str(t)][str(w)]["total"]) for w in weeks) for t in ids}
    rk = comp_rank(sums)
    weeklyRoto = {str(t): {"sum": _plain(sums[t]), "avg": _plain(sums[t] / len(weeks)), "rank": rk[t], "weekRanks": [weekly[str(t)][str(w)]["rank"] for w in weeks]} for t in ids}
    # 3 season all-play: every week's record added up
    ap = {t: season["teams"][str(t)]["allPlay"] for t in ids}
    rk = comp_rank({t: win_pct(ap[t]) for t in ids})
    seasonAllPlay = {str(t): {"record": ap[t], "winPct": season["teams"][str(t)]["winPct"], "rank": rk[t]} for t in ids}
    # 4 real record vs expected wins; luck = real wins - expected wins (a tied matchup counts half a win; expected wins = the sum of weekly all-play Win%)
    # The real RANK uses the category record against the actual opponents (W-L-T over every category battle): that is what Yahoo's head-to-head
    # categories standings show, and with only a few matchups played the matchup record alone leaves many teams level.
    real = {}
    for t in ids:
        rec, exp, crec = [0, 0, 0], Fraction(0), [0, 0, 0]
        for w in weeks:
            wv = weekly[str(t)][str(w)]
            if wv["result"] is None:
                continue
            rec["WLT".index(wv["result"])] += 1
            crec = [a + b for a, b in zip(crec, wv["catRecord"])]
            exp += win_pct(wv["allPlay"]) or 0
        games = sum(rec)
        wins = Fraction(2 * rec[0] + rec[2], 2)
        real[t] = {"record": rec, "games": games, "realWins": wins, "expectedWins": exp, "luck": wins - exp, "pct": win_pct(rec) if games else None,
                "catRecord": crec, "catPct": win_pct(crec) if sum(crec) else None}
    rk = comp_rank({t: real[t]["catPct"] for t in ids})
    realRecord = {str(t): {"record": real[t]["record"], "winPct": _plain(real[t]["pct"]), "realWins": _plain(real[t]["realWins"]),
                           "expectedWins": _plain(real[t]["expectedWins"]), "luck": _plain(real[t]["luck"]), "catRecord": real[t]["catRecord"], "catWinPct": _plain(real[t]["catPct"]), "rank": rk[t]} for t in ids}
    realRank = rk
    # 4b category luck: real category wins against the actual opponent vs the all-play share in each category; diff = real - expected
    cl = {t: {sp["cat"]: [Fraction(0), Fraction(0)] for sp in specs} for t in ids}
    for c in cores:
        wk = wk_by[c["week"]]
        expct = cat_play(c["tot"], specs)
        opp = {}
        for a, b in wk.get("matchups", []):
            opp[a], opp[b] = b, a
        for t in ids:
            o = opp.get(t)
            if o is None or wk["teams"].get(t, {}).get("score") is None or wk["teams"].get(o, {}).get("score") is None:
                continue
            for sp in specs:
                x, y = cat_value(c["tot"][t], sp), cat_value(c["tot"][o], sp)
                if x is None or y is None:
                    continue
                cl[t][sp["cat"]][0] += Fraction(cat_result(x, y, sp) + 1, 2)
                cl[t][sp["cat"]][1] += expct[t][sp["cat"]]
    luck = {t: sum(r - e for r, e in cl[t].values()) for t in ids}
    rk = comp_rank(luck)
    catLuck = {str(t): {"real": _plain(sum(r for r, _ in cl[t].values())), "expected": _plain(sum(e for _, e in cl[t].values())), "luck": _plain(luck[t]),
                        "byCat": {cat: {"real": _plain(r), "expected": _plain(e), "diff": _plain(r - e)} for cat, (r, e) in cl[t].items()}, "rank": rk[t]} for t in ids}
    # 5 category kings: the season leader and the best single week, per category
    kings = {}
    for sp in (sp for sp in specs if sp["cat"] not in KINGS_SKIP):
        cat = sp["cat"]
        def best(items):                                                      # items: [(teamId, week|None, value)] -> the best, with level holders listed
            items = [i for i in items if i[2] is not None]
            if not items:
                return None
            key = (lambda i: i[2]) if sp["lower"] else (lambda i: -i[2])
            m = min(items, key=key)
            level = [i for i in items if i[2] == m[2]]
            return {"team": m[0], "week": m[1], "value": m[2], "also": [i[0] if i[1] is None else [i[0], i[1]] for i in level[1:]]}
        sv = [(t, None, season["teams"][str(t)]["values"][cat]) for t in ids]
        bw = [(t, w, _wval(cores, w, t, sp)) for w in weeks for t in ids]
        kings[cat] = {"season": best(sv), "week": best(bw)}
    # 7 power rank: the plain average of the ranks on boards 1-4 (real record is ranked by its win%)
    comp = {t: {"seasonRoto": seasonRoto[str(t)]["rank"], "weeklyRoto": weeklyRoto[str(t)]["rank"], "seasonAllPlay": seasonAllPlay[str(t)]["rank"],
                "realRecord": realRank[t]} for t in ids}
    avg = {}
    for t in ids:
        got = [v for v in comp[t].values() if v is not None]
        avg[t] = Fraction(sum(got), len(got)) if got else None
    rk = comp_rank(avg, high=False)
    power = {str(t): {"ranks": comp[t], "avg": _plain(avg[t]), "rank": rk[t]} for t in ids}
    return {"weeks": weeks, "weekly": weekly, "seasonRoto": seasonRoto, "weeklyRoto": weeklyRoto, "seasonAllPlay": seasonAllPlay, "realRecord": realRecord, "catLuck": catLuck,
            "categoryKings": kings, "power": power}


def _wval(cores, week, t, sp):
    c = next(c for c in cores if c["week"] == week)
    return _plain(cat_value(c["tot"][t], sp))


# ------------------------------------------------------------------ playoff odds
SIMS = 50000                   # simulated rest-of-seasons: any figure is accurate to within about +-0.4 percentage points (95%)
PRIOR_WEEKS = 2                # the older fixed shrinkage: a team's weekly average counts as this many weeks of league-average play too (eb=False)
STRENGTH_DRAWS = 2000          # simulated seasons come in this many groups; each group draws every team's true strength afresh from what the data can say about it
BATCHES = 10                   # the groups are split in this many batches to measure how much the percentages wobble from simulation noise
HIST_SIMS = 8000                # the odds after each finished week are simulated with fewer seasons (they only draw a trend line)
SCHEDULE_PAGES_PER_PASS = 400  # the whole remaining schedule is read in the first pass (9 pages a week for 18 teams) and remembered; this only caps a runaway
SCHEDULE_REFRESH = 24 * 3600   # a remembered week is read again after a day (a commissioner can change the schedule) ...
SCHEDULE_REFRESH_WEEKS = 2     # ... but at most this many weeks per pass, oldest first, so the refresh is a trickle


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def schedule_path(cache, league):
    return os.path.join(cache, "%s-schedule.json" % league) if cache else None


def load_schedule(cache, league):
    """{week: {"at": time fetched, "pairs": [[a, b], ...]}} remembered from earlier passes; {} when there is none or it is damaged."""
    p = schedule_path(cache, league)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return {int(w): v for w, v in d.items() if isinstance(v, dict) and isinstance(v.get("pairs"), list)} if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def fetch_schedule(fx, league, base, ids, weeks, cache, now, budget=SCHEDULE_PAGES_PER_PASS, refresh_weeks=SCHEDULE_REFRESH_WEEKS):
    """Who plays whom in the given future weeks: Yahoo shows the pairing on a week's matchup page before the week starts, but has no page listing a whole week, so it
    is one page per matchup. Weeks not known yet are all read now (`budget` caps the pages per pass); known weeks are re-read after a day, at most `refresh_weeks` a pass.
    Each finished week is saved at once, so an interrupted pass keeps its progress. -> {week: [[a, b], ...]} for the weeks known (a failure only means fewer)."""
    sched = load_schedule(cache, league)
    missing = [w for w in weeks if w not in sched]
    stale = sorted((w for w in weeks if w in sched and now - sched[w]["at"] >= SCHEDULE_REFRESH), key=lambda w: (sched[w]["at"], w))[:refresh_weeks]
    used = 0
    for w in missing + stale:
        if used + len(ids) // 2 > budget:                               # a week is read whole or not at all
            break
        pairs, seen = [], set()
        try:
            for t in ids:
                if t in seen:
                    continue
                used += 1
                got = parse_week(fx.get("%s/matchup?date=totals&week=%d&mid1=%d" % (base, w, t)), league)
                if len(got["pair"]) != 2 or (got["week"] not in (None, w)):
                    raise RotoError("no pairing shown for week %d" % w)
                seen.update(got["pair"])
                pairs.append(sorted(got["pair"]))
        except RotoError as e:
            print("note: could not read the schedule for week %d (%s)" % (w, e), file=sys.stderr)
            break
        sched[w] = {"at": now, "pairs": pairs}
        if cache:
            write_atomic(schedule_path(cache, league), json.dumps({str(k): v for k, v in sched.items()}, separators=(",", ":")))
    return {w: sched[w]["pairs"] for w in weeks if w in sched}


def strengths(weeks_data, specs, ids, half_life=None, eb=True):
    """Per category: each team's weekly strength and how sure we are of it. Only finished weeks are passed in.
    {category: {"mean": {team: strength}, "se": {team: standard error of that strength}, "sd": week-to-week spread (the same for every team), "lower": fewer is better}}.
    With eb (empirical Bayes) a team's average is pulled toward the league average by as much as the league's own spread says is right: how far real team strengths differ is
    estimated from how far the averages differ beyond what week-to-week noise explains (at least 10% of the observed spread is kept, so a small sample cannot declare every
    team identical), and the pull is tau2 / (tau2 + sd2 / weeks). `se` is what is left unsure: the simulation draws true strengths from it. Without eb the old fixed pull of PRIOR_WEEKS
    is used and `se` is zero. `half_life` (weeks) makes recent weeks count more: a week's weight halves every half_life weeks (None = equal weights)."""
    out = {}
    last = len(weeks_data) - 1
    for sp in specs:
        per = {t: [] for t in ids}                                       # [(value, weight)]
        for i, wk in enumerate(weeks_data):
            tot = totals([wk], ids)
            w = 0.5 ** ((last - i) / half_life) if half_life else 1.0
            for t in ids:
                v = cat_value(tot.get(t, {}), sp)
                if v is not None:
                    per[t].append((float(v), w))
        allv = [x for xs in per.values() for x, _ in xs]
        if not allv:
            continue
        mu = sum(allv) / len(allv)
        ss = 0.0
        for xs in per.values():
            if xs:
                m = sum(x for x, _ in xs) / len(xs)
                ss += sum((x - m) ** 2 for x, _ in xs)
        dof = len(allv) - sum(1 for xs in per.values() if xs)
        sd2 = ss / dof if dof > 0 else sum((x - mu) ** 2 for x in allv) / len(allv)
        sd2 = sd2 or 1e-18
        avg, neff = {}, {}
        for t, xs in per.items():
            if xs:
                sw = sum(w for _, w in xs)
                avg[t] = sum(x * w for x, w in xs) / sw
                neff[t] = sw * sw / sum(w * w for _, w in xs)            # the weeks that count in full (equal weights: just the number of weeks)
        if not eb:
            means = {t: (sum(x * w for x, w in xs) + PRIOR_WEEKS * mu) / (sum(w for _, w in xs) + PRIOR_WEEKS) if xs else mu for t, xs in per.items()}
            out[sp["cat"]] = {"mean": means, "se": {t: 0.0 for t in per}, "sd": math.sqrt(sd2), "lower": sp["lower"]}
            continue
        have = list(avg)
        if len(have) > 1:
            m_all = sum(avg.values()) / len(have)
            between = sum((avg[t] - m_all) ** 2 for t in have) / (len(have) - 1)
        else:
            between = 0.0
        if dof <= 0:                                                      # one finished week: the noise cannot be told from real differences; assume a quarter is real
            sd2, tau2 = between or sd2, 0.25 * between
        else:
            noise = sum(sd2 / neff[t] for t in have) / len(have)
            tau2 = max(between - noise, 0.1 * between)
        tau2 = tau2 or 1e-18
        mean, se = {}, {}
        for t in per:
            if t in avg:
                wgt = tau2 / (tau2 + sd2 / neff[t])
                mean[t] = mu + wgt * (avg[t] - mu)
                se[t] = math.sqrt(wgt * sd2 / neff[t])
            else:
                mean[t], se[t] = mu, math.sqrt(tau2)
        out[sp["cat"]] = {"mean": mean, "se": se, "sd": math.sqrt(sd2), "lower": sp["lower"]}
    return out


def cat_win_distribution(a, b, st, drawn=None, predictive=False):
    """P(team a wins exactly k of the categories against b), k = 0..ncat: each category is a normal-difference chance, combined exactly. `drawn` ({category: {team: strength}})
    replaces the estimated strengths with ones drawn for one simulated season; `predictive` (a forecast made now, strengths still uncertain) widens each category's spread by the
    two strengths' standard errors instead."""
    dist = [1.0]
    for name, c in st.items():
        m = drawn[name] if drawn else c["mean"]
        var = 2 * c["sd"] ** 2
        if predictive:
            var += c.get("se", {}).get(a, 0.0) ** 2 + c.get("se", {}).get(b, 0.0) ** 2
        z = (m[a] - m[b]) / math.sqrt(var)
        p = _phi(-z if c["lower"] else z)
        new = [0.0] * (len(dist) + 1)
        for k, q in enumerate(dist):
            new[k] += q * (1 - p)
            new[k + 1] += q * p
        dist = new
    return dist


def simulate(st, ids, points, remaining, divisions=None, spots=None, div_winners=False, sims=SIMS, seed=1, draws=None, stats=None):
    """Play the rest of the regular season about `sims` times. points = {team: category points so far (a won category 1, level 0.5)}, remaining = [[pairs of that week] or None
    (pairing unknown: drawn at random)] per week. Standing = total category points (what Yahoo ranks category leagues by), level teams broken at random. Playoff places: with
    div_winners every division's leader plus the best of the rest by overall standing, otherwise the top `spots`.
    When the strengths in `st` carry a standard error ("se"), the seasons are played in groups (`draws` of them): each group first draws every team's true strength from what
    the data can say about it (stratified draws, so a few hundred groups cover the range evenly) and keeps it for the whole group, so a team that is truly good or bad stays so
    across all its remaining weeks. Without "se" every season uses the estimates as they are. `stats`, when given, receives "margin": how many percentage points the playoff
    chances may be off from simulation noise (95%), measured between batches of groups.
    -> {team: {"playoff", "first", "rank" (expected), "dist": [P(finish 1st), ...]}}"""
    rnd = random.Random(seed)
    rand = rnd.random
    n, ncat = len(ids), len(st)
    ix = {t: i for i, t in enumerate(ids)}
    sampling = any(any(v > 0 for v in c.get("se", {}).values()) for c in st.values())
    groups = max(1, min(draws or STRENGTH_DRAWS, sims // 10)) if sampling else 1
    per = -(-sims // groups)
    total = groups * per
    z = {}
    if sampling:
        inv = statistics.NormalDist().inv_cdf
        for name, c in st.items():
            z[name] = {}
            for t in ids:
                if c["se"].get(t, 0) > 0:
                    zs = [inv((k + rand()) / groups) for k in range(groups)]
                    rnd.shuffle(zs)
                    z[name][t] = zs
    base_pts = [float(points[t]) for t in ids]
    divs = divisions or {}
    div_of = [divs.get(t) for t in ids]
    use_divs = bool(div_winners and divs and spots)
    playoff, first, dist = [0] * n, [0] * n, [[0] * n for _ in range(n)]
    batch = [[0] * n for _ in range(BATCHES)]
    bis = bisect.bisect
    order_idx = list(range(n))
    for g in range(groups):
        drawn = None
        if sampling:
            drawn = {name: {t: c["mean"][t] + (c["se"][t] * z[name][t][g] if t in z[name] else 0.0) for t in ids} for name, c in st.items()}
        cache = {}

        def cdf_of(a, b):                                               # cumulative chances that team a (index) wins 0..ncat categories against b, for this group's strengths
            key = (a, b)
            if key not in cache:
                d, acc, c = cat_win_distribution(ids[a], ids[b], st, drawn), 0.0, []
                for q in d:
                    acc += q
                    c.append(acc)
                cache[key] = c
            return cache[key]
        known = [None if wk is None else [(ix[a], ix[b], cdf_of(ix[a], ix[b])) for a, b in wk] for wk in remaining]
        bt = batch[g % BATCHES]
        for _ in range(per):
            pts = base_pts[:]
            for wk in known:
                if wk is None:
                    perm = order_idx[:]
                    rnd.shuffle(perm)
                    pairs = [(perm[i], perm[i + 1], cdf_of(perm[i], perm[i + 1])) for i in range(0, n - 1, 2)]
                else:
                    pairs = wk
                for a, b, c in pairs:
                    k = bis(c, rand() * c[-1])
                    if k > ncat:
                        k = ncat
                    pts[a] += k
                    pts[b] += ncat - k
            order = sorted(order_idx, key=lambda t: pts[t] + rand() * 0.01, reverse=True)      # level teams are separated at random (points move in halves)
            for r, t in enumerate(order):
                dist[t][r] += 1
            first[order[0]] += 1
            if spots:
                if use_divs:
                    win = {}
                    for t in order:
                        win.setdefault(div_of[t], t)
                    chosen = list(win.values())[:spots]
                    taken = set(chosen)
                    chosen += [t for t in order if t not in taken][:max(0, spots - len(chosen))]
                else:
                    chosen = order[:spots]
                for t in chosen:
                    playoff[t] += 1
                    bt[t] += 1
    if stats is not None:
        used = [i for i in range(BATCHES) if i < groups]
        size = [per * sum(1 for g in range(groups) if g % BATCHES == i) for i in used]
        worst = 0.0
        for t in range(n):
            f = [batch[i][t] / size[k] for k, i in enumerate(used)]
            if len(f) > 1:
                m = sum(f) / len(f)
                worst = max(worst, math.sqrt(sum((x - m) ** 2 for x in f) / (len(f) - 1) / len(f)))
        stats["margin"] = round(1.96 * worst * 100, 2) if len(used) > 1 else round(1.96 * math.sqrt(0.25 / total) * 100, 2)
    return {t: {"playoff": playoff[i] / total, "first": first[i] / total, "rank": sum((r + 1) * c for r, c in enumerate(dist[i])) / total, "dist": [c / total for c in dist[i]]}
            for t, i in ix.items()}


def odds_path(cache, league):
    return os.path.join(cache, "%s-odds.json" % league) if cache else None


def history_path(cache, league):
    return os.path.join(cache, "%s-odds-history.json" % league) if cache else None


def cat_points_through(weeks_data, specs, ids):
    """Category points after each of the given weeks, as a list of {team: points} (index 0 = after the first week); a won category is 1, a level one 0.5."""
    pts, out = {t: 0.0 for t in ids}, []
    for wk in weeks_data:
        tot = totals([wk], wk["teams"])
        for a, b in wk.get("matchups", []):
            r = head_to_head(tot[a], tot[b], specs)
            pts[a] += r[0] + r[2] / 2
            pts[b] += r[1] + r[2] / 2
        out.append(dict(pts))
    return out


def odds_history(settings, weeks_data, specs, ids, pairs_after, regular, cache, league, half_life=None):
    """The playoff chances as they stood after each finished week: [{"week": k, "teams": {team: chance}}]. Week k uses only what was known then (strengths and category points
    from weeks 1..k) and the real pairings of the weeks after it (`pairs_after`: week -> pairs or None). Each week is simulated once and remembered by a fingerprint of its inputs,
    so only a week whose inputs changed (a stat correction, a newly read schedule week) is simulated again."""
    spots = settings.get("playoff_teams")
    divisions = settings.get("divisions") or {}
    done = len(weeks_data) - 1
    pts = cat_points_through(weeks_data[:done], specs, ids)
    p = history_path(cache, league)
    try:
        with open(p, encoding="utf-8") as f:
            saved = json.load(f)
        saved = saved if isinstance(saved, dict) else {}
    except (OSError, ValueError, TypeError):
        saved = {}
    out, changed = [], False
    for k in range(1, done + 1):
        st = strengths(weeks_data[:k], specs, ids, half_life)
        if not st:
            continue
        remaining = [pairs_after.get(w) for w in range(k + 1, regular + 1)]
        inputs = {"v": 3, "sims": HIST_SIMS, "draws": STRENGTH_DRAWS, "hl": half_life, "spots": spots, "dw": bool(settings.get("div_winners")), "points": pts[k - 1], "div": sorted(divisions.items()),
                  "sched": [sorted(map(list, wk)) if wk else None for wk in remaining],
                  "st": {c: {"sd": round(v["sd"], 9), "lower": v["lower"], "mean": sorted((t, round(x, 9)) for t, x in v["mean"].items())} for c, v in st.items()}}
        fp = hashlib.sha1(json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        entry = saved.get(str(k))
        if not (isinstance(entry, dict) and entry.get("fp") == fp and isinstance(entry.get("teams"), dict)):
            res = simulate(st, ids, pts[k - 1], remaining, divisions, spots, settings.get("div_winners"), sims=HIST_SIMS, seed=int(league) * 1000 + k)
            entry = {"fp": fp, "teams": {str(t): round(r["playoff"], 4) for t, r in res.items()}}
            saved[str(k)] = entry
            changed = True
        out.append({"week": k, "teams": entry["teams"]})
    if changed and p:
        write_atomic(p, json.dumps(saved, separators=(",", ":")))
    return out


def backtest(weeks_data, specs, ids, half_life=None):
    """How good would the model's matchup forecasts have been? Each finished week from the second on is forecast from the weeks before it (same strengths, same recency setting as
    the odds) and compared with what happened. -> {"games", "favouriteWon" (share of matchups the favourite won, a tie half), "brier" (mean squared miss; a coin flip scores
    0.25), "baseline", "bins" (50-60 / 60-70 / 70+ %: forecast against result), "weeks", "spreadRatio" (how much more real category scores swing than the model says; 1 = right)},
    or None when there is no week to forecast yet. `weeks_data` holds finished weeks only."""
    rows, per_week, swing_obs, swing_model = [], [], 0.0, 0.0
    for k in range(1, len(weeks_data)):
        st = strengths(weeks_data[:k], specs, ids, half_life)
        if not st:
            continue
        wk = weeks_data[k]
        tot = totals([wk], wk["teams"])
        ncat = len(st)
        games = []
        for a, b in wk.get("matchups", []):
            res = head_to_head(tot[a], tot[b], specs)
            if sum(res) == 0:
                continue
            dist = cat_win_distribution(a, b, st, predictive=True)
            half = ncat / 2.0
            p = sum(q for j, q in enumerate(dist) if j > half) + (0.5 * dist[int(half)] if ncat % 2 == 0 else 0.0)
            y = 1.0 if res[0] > res[1] else 0.0 if res[0] < res[1] else 0.5
            mean_k = sum(j * q for j, q in enumerate(dist))
            swing_model += sum((j - mean_k) ** 2 * q for j, q in enumerate(dist))
            swing_obs += (res[0] + res[2] / 2.0 - mean_k) ** 2
            if p < 0.5:                                                  # always the favourite's side
                p, y = 1 - p, 1 - y
            games.append((p, y))
        rows += games
        if games:
            per_week.append({"week": wk["week"], "games": len(games), "favouriteWon": round(sum(y for _, y in games) / len(games), 4),
                             "brier": round(sum((p - y) ** 2 for p, y in games) / len(games), 4)})
    if not rows:
        return None
    bins = []
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
        g = [(p, y) for p, y in rows if lo <= p < hi]
        if g:
            bins.append({"from": lo, "to": min(hi, 1.0), "games": len(g), "predicted": round(sum(p for p, _ in g) / len(g), 4), "actual": round(sum(y for _, y in g) / len(g), 4)})
    return {"games": len(rows), "favouriteWon": round(sum(y for _, y in rows) / len(rows), 4), "brier": round(sum((p - y) ** 2 for p, y in rows) / len(rows), 4), "baseline": 0.25,
            "bins": bins, "weeks": per_week, "spreadRatio": round(swing_obs / swing_model, 3) if swing_model else None}


HALF_LIVES = (8, 5, 3)         # weeks; tried against equal weights once enough weeks are in
MIN_WEEKS_FOR_RECENCY = 6      # fewer finished weeks cannot tell the options apart
RECENCY_MARGIN = 0.02          # a half-life must beat equal weights by this share of the Brier score to be used


def choose_half_life(weeks_data, specs, ids):
    """Recent weeks count more only if that has actually forecast better: compares equal weights with each half-life by walk-forward Brier score and keeps one only when it wins
    by RECENCY_MARGIN. -> (half_life or None, {"equal": brier, "8": brier, ...}); before MIN_WEEKS_FOR_RECENCY finished weeks it stays equal weights."""
    if len(weeks_data) < MIN_WEEKS_FOR_RECENCY:
        return None, {}
    tested = {}
    for hl in (None,) + HALF_LIVES:
        bt = backtest(weeks_data, specs, ids, hl)
        if bt:
            tested["equal" if hl is None else str(hl)] = bt["brier"]
    best = min((k for k in tested if k != "equal"), key=lambda k: tested[k], default=None)
    if best is not None and "equal" in tested and tested[best] < tested["equal"] * (1 - RECENCY_MARGIN):
        return float(best), tested
    return None, tested


def odds_block(settings, weeks_data, specs, ids, final_cat_record, fx, league, base, cache, now):
    """The `odds` part of the report, or None when it cannot be made (the league's playoff setup is not on the settings page, or no week has finished). The simulation
    only runs when its inputs changed since the last pass (points so far, team strengths, schedule, playoff setup): the answer is remembered in the cache."""
    spots, start = settings.get("playoff_teams"), settings.get("playoff_start")
    done = len(weeks_data) - 1
    if not spots or not start or done < 1:
        return None
    regular = start - 1
    live = weeks_data[-1]["week"]
    left = list(range(live, regular + 1))
    if not left:
        return None
    sched = fetch_schedule(fx, league, base, ids, left[1:], cache, now) if len(left) > 1 else {}
    remaining = [weeks_data[-1].get("matchups") or None] + [sched.get(w) for w in left[1:]]   # the live week: its pairing is known from its own page
    half_life, tested = choose_half_life(weeks_data[:done], specs, ids)
    st = strengths(weeks_data[:done], specs, ids, half_life)
    if not st:
        return None
    points = {t: float(final_cat_record[t][0]) + final_cat_record[t][2] / 2 for t in ids}
    divisions = settings.get("divisions") or {}
    inputs = {"v": 5, "sims": SIMS, "draws": STRENGTH_DRAWS, "hl": half_life, "spots": spots, "start": start, "dw": bool(settings.get("div_winners")), "left": left, "points": points,
              "div": sorted(divisions.items()), "sched": [sorted(map(list, wk)) if wk else None for wk in remaining],
              "st": {c: {"sd": round(v["sd"], 9), "lower": v["lower"], "mean": sorted((t, round(x, 9)) for t, x in v["mean"].items())} for c, v in st.items()}}
    fp = hashlib.sha1(json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    p = odds_path(cache, league)
    try:
        with open(p, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("fp") == fp and isinstance(saved.get("odds"), dict):
            return saved["odds"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    sim_stats = {}
    res = simulate(st, ids, points, remaining, divisions, spots, settings.get("div_winners"), sims=SIMS, seed=int(league) * 1000 + done, stats=sim_stats)
    r4 = lambda x: round(x, 4)                                          # noqa: E731
    known = sum(1 for x in remaining if x)
    out = {"spots": spots, "regularWeeks": regular, "remaining": left, "scheduleWeeks": known, "complete": known == len(remaining), "sims": SIMS,
           "margin": sim_stats.get("margin"), "model": {"version": 2, "strength": "empirical Bayes, drawn per simulated season", "halfLife": half_life, "tested": tested}, "accuracy": backtest(weeks_data[:done], specs, ids, half_life),
           "divisions": sorted(set(divisions.values())) or None, "divisionWinners": bool(settings.get("div_winners") and divisions),
           "teams": {str(t): {"playoff": r4(r["playoff"]), "first": r4(r["first"]), "rank": r4(r["rank"]), "dist": [r4(x) for x in r["dist"]],
                              "division": divisions.get(t), "points": points[t]} for t, r in res.items()}}
    out["schedule"] = {str(w): [list(p) for p in pairs] for w, pairs in zip(left, remaining) if pairs}      # who plays whom in the weeks still to come (the page rates that schedule)
    pairs_after = {wk["week"]: wk.get("matchups") or None for wk in weeks_data}
    pairs_after.update({w: sched.get(w) for w in left[1:]})
    out["history"] = odds_history(settings, weeks_data, specs, ids, pairs_after, regular, cache, league, half_life)
    if p:
        write_atomic(p, json.dumps({"fp": fp, "odds": out}, separators=(",", ":")))
    return out


SCHEMA_VERSION = 3


def configured_champion(league, root=None):
    """The defending champion set for this league in leagues.json ("champions": {"<league id>": "<team name or team id>"}), or None."""
    try:
        with open(os.path.join(root or os.path.dirname(os.path.abspath(__file__)), "leagues.json"), encoding="utf-8") as f:
            return (json.load(f).get("champions") or {}).get(str(league))
    except (OSError, ValueError):
        return None


def _norm(text):
    """A name for comparing: lower case, punctuation dropped, spaces collapsed ("M. Jordat" == "m jordat")."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(text)).casefold().split())


def resolve_champion(spec, names):
    """A team id (as a number or text) or a team name -> the team id in `names` ({id: name}), or None. Names match ignoring case, punctuation and extra spaces; Yahoo team
    names often carry a tagline ("M. Jordat | The Silver Seekers"), so if nothing matches the whole name the part before the "|" is tried. Never raises: no match, or
    more than one, means no crown."""
    if spec is None or str(spec).strip() == "":
        return None
    spec = str(spec).strip()
    if spec.isdigit() and int(spec) in names:
        return int(spec)
    want = _norm(spec)
    hits = [t for t, n in names.items() if _norm(n) == want]
    if not hits:
        hits = [t for t, n in names.items() if "|" in str(n) and _norm(str(n).split("|", 1)[0]) == want]
    if len(hits) != 1:
        print("note: champion %r %s; no crown shown" % (spec, "matches %d teams" % len(hits) if hits else "not found among the team names"), file=sys.stderr)
        return None
    return hits[0]


def _result(sc, osc):
    return None if sc is None or osc is None else "W" if sc > osc else "L" if sc < osc else "T"


def correction_event(fix, specs):
    """One re-read of a finished week that came back different -> {"week", "at", "changes", "rank", "flips"} in the terms the page shows, or None when no
    scoring category moved. changes: category totals that moved; rank: teams whose roto rank for that week changed; flips: matchups whose result changed."""
    old, new = fix["old"], fix["new"]
    changes = []
    for tid in sorted(new["teams"]):
        for sp in specs:
            ov = cat_value(old["teams"].get(tid, {}).get("cols", {}), sp)
            nv = cat_value(new["teams"][tid]["cols"], sp)
            if ov is not None and nv is not None and ov != nv:
                changes.append({"team": tid, "cat": sp["cat"], "old": _plain(ov), "new": _plain(nv)})
    if not changes:
        return None
    oc, nc = _core(old, specs)["res"], _core(new, specs)["res"]
    rank = [{"team": t, "old": oc[t]["rank"], "new": nc[t]["rank"]} for t in sorted(nc) if t in oc and oc[t]["rank"] != nc[t]["rank"]]
    flips = []
    for a, b in new.get("matchups", []):
        for x, y in ((a, b), (b, a)):
            before = _result(old["teams"].get(x, {}).get("score"), old["teams"].get(y, {}).get("score"))
            after = _result(new["teams"].get(x, {}).get("score"), new["teams"].get(y, {}).get("score"))
            if before and after and before != after:
                flips.append({"team": x, "opp": y, "old": before, "new": after})
    return {"week": new["week"], "at": int(fix["at"]), "changes": changes, "rank": rank, "flips": flips}


def update_corrections(cache, league, events, now):
    """Corrections stay on the report for 14 days: they are kept next to the cached weeks (which the live workflow carries between runs)."""
    p = os.path.join(cache, "%s-corrections.json" % league) if cache else None
    kept = []
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                kept = json.load(f)
        except (OSError, ValueError):
            kept = []
    have = {(e["week"], e["at"]) for e in kept}
    kept = [e for e in kept + [e for e in events if (e["week"], e["at"]) not in have] if now - e["at"] <= KEEP_CORRECTIONS]
    if p:
        write_atomic(p, json.dumps(kept, separators=(",", ":")))
    return sorted(kept, key=lambda e: -e["at"])


def report(league, cache=None, delay=1.5, sport="nba", now=None, champion=None):
    """The whole report: one view for the season and one per week that has stats, plus the season composites (what the page and the PNGs are drawn from)."""
    import datetime
    when = now or datetime.datetime.now(datetime.timezone.utc)
    t_now = when.timestamp()                                              # the one clock: everything time-based below uses it
    fixes = []
    st, teams, weeks_data, base = load(league, cache, delay, sport, now=t_now, fixes=fixes)
    headers = list(next(iter(weeks_data[0]["teams"].values()))["cols"])
    cats = st["categories"] or [h for h in headers if h and not h.endswith("M/A*")]
    specs, skipped = plan(cats, headers)
    if not specs:
        raise RotoError("none of the league's categories (%s) can be computed from the matchup pages" % ", ".join(cats))
    corrections = update_corrections(cache, league, [e for e in (correction_event(f, specs) for f in fixes) if e], t_now)
    names = {t: teams.get(t) or next((wk["teams"][t]["name"] for wk in weeks_data if t in wk["teams"]), str(t)) for t in teams}
    ids = sorted(teams)
    cores = [_core(wk, specs) for wk in weeks_data]
    views = {"season": _season_view(cores, weeks_data, specs, ids)}
    done = len(weeks_data) - 1                                           # the newest week is still being played: the "final" snapshot leaves it out
    if done >= 1:
        views["seasonFinal"] = _season_view(cores[:done], weeks_data[:done], specs, ids)
    for wk, c in zip(weeks_data, cores):
        views["w%d" % wk["week"]] = _week_view(c, wk, specs, ids)
    composites_final = composites(weeks_data[:done], cores[:done], specs, ids, views["seasonFinal"]) if done >= 1 else None
    odds = None
    if done >= 1:
        try:
            final_rec = {t: composites_final["realRecord"][str(t)]["catRecord"] for t in ids}
            odds = odds_block(st, weeks_data, specs, ids, final_rec, Fetcher(delay=delay, cache=cache), league, base, cache, t_now)
        except Exception as e:                                           # the odds are an extra: whatever goes wrong must not take the report down
            print("note: playoff odds skipped (%s)" % e, file=sys.stderr)
    champ = resolve_champion(champion if champion is not None else configured_champion(league), names)
    return {"schema": "yahoo-roto-report/2", "schemaVersion": SCHEMA_VERSION, "league": str(league), "champion": champ, "corrections": corrections, "leagueName": st.get("name"), "sport": sport, "scoring": st["scoring"], "asOf": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inProgressWeek": weeks_data[-1]["week"], "categories": [{"cat": sp["cat"], "lower": sp["lower"], "pct": sp["kind"] == "pct"} for sp in specs],
            "skipped": skipped, "teams": {str(t): names[t] for t in names}, "weeks": [wk["week"] for wk in weeks_data], "views": views,
            "composites": composites(weeks_data, cores, specs, ids, views["season"]),
            "compositesFinal": composites_final, "odds": odds}


def run(league, week=None, through=None, cache=None, delay=1.5, sport="nba", out=print):
    st, teams, weeks_data, _base = load(league, cache, delay, sport, only_week=week, through=through)
    headers = list(next(iter(weeks_data[0]["teams"].values()))["cols"])
    cats = st["categories"] or [h for h in headers if h and not h.endswith("M/A*")]
    specs, skipped = plan(cats, headers)
    if not specs:
        raise RotoError("none of the league's categories (%s) can be computed from the matchup pages" % ", ".join(cats))
    tot = totals(weeks_data, teams)
    res, ranked = roto(tot, specs)
    names = {t: teams.get(t) or next((wk["teams"][t]["name"] for wk in weeks_data if t in wk["teams"]), str(t)) for t in tot}
    return {"league": str(league), "scoring": st["scoring"], "weeks": [w["week"] for w in weeks_data], "categories": [s["cat"] for s in specs],
            "skipped": skipped, "teams": [{"teamId": t, "name": names[t], "rank": res[t]["rank"], "total": res[t]["total"], "points": res[t]["points"],
                                           "values": {s["cat"]: _plain(cat_value(tot[t], s)) for s in specs}} for t in ranked]}


def _plain(v):
    return None if v is None else (float(v) if v.denominator != 1 else int(v))


def render(doc):
    cats = doc["categories"]
    wk = doc["weeks"]
    lines = ["League %s · %s · weeks %s" % (doc["league"], doc["scoring"] or "?", ("%d-%d" % (wk[0], wk[-1])) if len(wk) > 1 else wk[0])]
    if doc["skipped"]:
        lines.append("skipped (not computable from matchup pages): " + ", ".join(doc["skipped"]))
    w = max(len(t["name"]) for t in doc["teams"])
    lines.append("%3s  %-*s  %6s  " % ("#", w, "Team", "ROTO") + " ".join("%6s" % c for c in cats))
    for t in doc["teams"]:
        lines.append("%3d  %-*s  %6.1f  " % (t["rank"], w, t["name"], t["total"]) + " ".join("%6s" % (("%g" % t["points"][c]) if t["points"][c] is not None else "-") for c in cats))
    lines.append("")
    lines.append("category totals")
    lines.append("%-*s  " % (w, "Team") + " ".join("%8s" % c for c in cats))
    for t in doc["teams"]:
        lines.append("%-*s  " % (w, t["name"]) + " ".join("%8s" % (_fmt(c, t["values"][c])) for c in cats))
    return "\n".join(lines)


def _fmt(cat, v):
    if v is None:
        return "-"
    return ("%.3f" % v).lstrip("0") if cat.endswith("%") else ("%g" % v)


# ------------------------------------------------------------------ files: self-contained HTML and the three images
IMAGES = (("roto", "roto", 1680), ("stats", "stats", 1680), ("allplay", "allplay", 2600), ("matchups", "matchups", 1680))        # (page view, file name, css width); drawn at device scale 1.5
SEASON_BOARDS = ("roto", "weekly", "allplay", "real", "luckweeks", "catluck", "kings", "form", "split", "sos", "odds", "power")                   # the season composites; files are season-<board>.png
SEASON_WIDTH = 1680
SCALE = 1.5


def write_html(doc, out_dir):
    """index.html = the page template with the report inlined: opens anywhere, offline, no server. Returns the path."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "index.html"), encoding="utf-8") as f:
        page = f.read()
    blob = json.dumps(doc, ensure_ascii=False).replace("<", "\\u003c")             # no "<" at all: a team name like "<!--<script" cannot open a comment or close the script
    page = page.replace("<script>\n(function(){", "<script>window.__REPORT__=%s;</script>\n<script>\n(function(){" % blob, 1)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    return path


def find_chrome():
    import shutil
    for c in (os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
              shutil.which("google-chrome"), shutil.which("google-chrome-stable"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and os.path.exists(c):
            return c
    return None


def write_images(html_path, out_dir, week=None, season=False, chrome=None):
    """PNGs of the page in static mode (no week strip or buttons), drawn by headless Chrome at device scale 1.5: roto.png, stats.png and allplay.png of one
    week (default: the current week; `week` picks another), or season-<board>.png for every season board with `season`. The page height is measured first
    (the bottom of the .sheet, after the fonts have loaded) so each image is exactly as tall as its sheet. Needs Google Chrome / Chromium."""
    import pathlib
    import subprocess
    chrome = chrome or find_chrome()
    if not chrome:
        raise RotoError("Chrome/Chromium not found: set $CHROME to its path to draw the images (the HTML file works without it)")
    base = ["--headless", "--disable-gpu", "--hide-scrollbars", "--no-sandbox", "--virtual-time-budget=20000"]
    jobs = [("season-%s.png" % b, "season=1&board=%s" % b, SEASON_WIDTH) for b in SEASON_BOARDS] if season else \
           [("%s.png" % f, "view=%s%s" % (v, "&week=%d" % week if week else ""), w) for v, f, w in IMAGES]
    paths = []
    for fname, query, width in jobs:
        url = "%s?static=1&%s" % (pathlib.Path(html_path).resolve().as_uri(), query)
        dom = subprocess.run([chrome] + base + ["--window-size=%d,1000" % width, "--dump-dom", url], capture_output=True, text=True, timeout=120).stdout
        m = re.search(r'name="report-height"[^>]*content="(\d+)"|content="(\d+)"[^>]*name="report-height"', dom)
        if not m:
            raise RotoError("could not measure %s (Chrome printed no document)" % fname)
        if 'data-fonts="1"' not in dom:
            print("note: fonts were not confirmed loaded for %s (offline?); system fonts may be used" % fname, file=sys.stderr)
        height = int(m.group(1) or m.group(2))
        path = os.path.join(out_dir, fname)
        subprocess.run([chrome] + base + ["--force-device-scale-factor=%s" % SCALE, "--window-size=%d,%d" % (width, height), "--screenshot=" + path, url],
                       capture_output=True, timeout=120)
        if not os.path.exists(path):
            raise RotoError("Chrome did not write %s" % path)
        paths.append(path)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("league", help="the Yahoo league id (the number in the league's URL)")
    ap.add_argument("--week", type=int, help="one week only (with --report --png: the week to draw, default the current week)")
    ap.add_argument("--through", type=int, help="season roto through this week")
    ap.add_argument("--sport", default="nba", choices=sorted(SPORTS), help="default nba (categories and pages are verified for NBA only)")
    ap.add_argument("--cache", help="directory to keep fetched pages in")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests (default 1.5)")
    ap.add_argument("--champion", help="the defending champion (team name or team id) to mark with a crown; default: leagues.json \"champions\"")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", metavar="DIR", help="write DIR/report.json and a self-contained DIR/index.html (all weeks, all three views)")
    ap.add_argument("--png", action="store_true", help="with --report: also draw DIR/roto.png, stats.png, allplay.png of the current week (needs Chrome); --week N for another week")
    ap.add_argument("--season", action="store_true", help="with --png: draw the season boards (DIR/season-<board>.png) instead")
    a = ap.parse_args(argv)
    try:
        if a.report:
            doc = report(a.league, a.cache, a.delay, a.sport, champion=a.champion)
            path = write_html(doc, a.report)
            print("wrote %s and report.json (weeks %s, week %d in progress)" % (path, ", ".join(map(str, doc["weeks"])), doc["inProgressWeek"]))
            if a.png:
                for p in write_images(os.path.abspath(path), a.report, a.week, a.season):
                    print("wrote", p)
            return 0
        doc = run(a.league, a.week, a.through, a.cache, a.delay, a.sport)
    except RotoError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=1, ensure_ascii=False) if a.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
