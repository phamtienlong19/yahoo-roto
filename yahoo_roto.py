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
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from fractions import Fraction
from html.parser import HTMLParser

BASE = "https://basketball.fantasysports.yahoo.com/nba/{league}"
SPORTS = {"nba": "basketball.fantasysports.yahoo.com/nba", "nfl": "football.fantasysports.yahoo.com/f1", "mlb": "baseball.fantasysports.yahoo.com/b1",
          "nhl": "hockey.fantasysports.yahoo.com/hockey"}
LOWER_IS_BETTER = {"TO", "PF", "DQ", "GA", "GAA", "ERA", "WHIP", "BB"}
UA = "yahoo-roto/1.0 (read-only; public pages)"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class RotoError(RuntimeError):
    pass


# ------------------------------------------------------------------ fetching
class Fetcher:
    def __init__(self, delay=1.5, cache=None, out=print):
        self.delay, self.cache, self.out, self.last = delay, cache, out, 0.0
        if cache:
            os.makedirs(cache, exist_ok=True)

    def get(self, url, keep=False):
        path = os.path.join(self.cache, hashlib.sha1(url.encode()).hexdigest() + ".html") if self.cache and keep else None
        if path and os.path.exists(path):
            return open(path, encoding="utf-8").read()
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body, final = r.read().decode("utf-8", "replace"), r.geturl()
        except urllib.error.HTTPError as e:
            raise RotoError("%s answered HTTP %s" % (url, e.code))
        except urllib.error.URLError as e:
            raise RotoError("could not reach %s (%s)" % (url, e.reason))
        finally:
            self.last = time.time()
        if "login.yahoo.com" in final or "/login" in final.split("?")[0]:
            raise RotoError("this league is not publicly viewable (Yahoo asked for a sign-in). Only public leagues can be read; "
                            "a commissioner can turn on 'Make League Publicly Viewable' in the league settings.")
        if path and keep:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        return body


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
    return {"scoring": m.group(1).strip() if m else None, "categories": cats, "public": (pub.group(1) == "Yes") if pub else None,
            "name": nm.group(1).strip() if nm else None}


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


# ------------------------------------------------------------------ the run
def head_to_head(a, b, specs):
    w = l = t = 0
    for sp in specs:
        x, y = cat_value(a, sp), cat_value(b, sp)
        if x is None or y is None:
            continue
        if x == y:
            t += 1
        elif (x < y) == sp["lower"]:
            w += 1
        else:
            l += 1
    return [w, l, t]


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


def _cache_get(cache, league, week):
    p = _cache_path(cache, league, week)
    if p and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("v") != 2:                                             # an older file without Score / matchups: fetch again
            return None
        return {"week": week, "matchups": d["matchups"],
                "teams": {int(t): {"name": r["name"], "score": _dec(r["score"]), "cols": {h: _dec(v) for h, v in r["cols"].items()}} for t, r in d["teams"].items()}}
    return None


def _cache_put(cache, league, wk):
    p = _cache_path(cache, league, wk["week"])
    if p:
        os.makedirs(cache, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"v": 2, "matchups": wk.get("matchups", []),
                       "teams": {str(t): {"name": r["name"], "score": _enc(r.get("score")), "cols": {h: _enc(v) for h, v in r["cols"].items()}}
                                 for t, r in wk["teams"].items()}}, f)


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
    return {"week": week, "teams": got, "matchups": pairs}


def has_data(wk):
    return any(v is not None for rec in wk["teams"].values() for v in rec["cols"].values())


def load(league, cache=None, delay=1.5, sport="nba", only_week=None, through=None):
    """-> (settings, teams {id: name}, weeks_data [{week, teams}], in_progress_week or None). Weeks are read in order and the walk stops at the first
    week with no stats. A week is kept in the cache only once a later week has stats (it is then final); the newest week is always fetched again."""
    base = "https://%s/%s" % (SPORTS[sport], league)
    fx = Fetcher(delay=delay)
    st = parse_settings(fx.get(base + "/settings"))
    if st["scoring"] is None and not st["categories"]:
        raise RotoError("could not read league %s's public settings: it does not exist or it is not publicly viewable (Yahoo shows a generic "
                        "error page). Only public leagues can be read; a commissioner can turn on 'Make League Publicly Viewable' in the settings." % league)
    if st["scoring"] and "Head-to-Head" not in st["scoring"]:
        raise RotoError("this league's scoring type is %r; only head-to-head leagues (weekly matchup pages) are supported" % st["scoring"])
    teams = parse_teams(fx.get(base + "?lhst=stand"), league)
    if len(teams) < 2:
        raise RotoError("could not read the teams from the standings page")
    ids = sorted(teams)
    first = parse_week(fx.get("%s/matchup?date=totals&week=1&mid1=%d" % (base, ids[0])), league)
    all_weeks = first["weeks"] or [1]
    limit = min(only_week or 10 ** 6, through or 10 ** 6)
    weeks_data = []
    for w in [x for x in all_weeks if x <= limit]:
        wk = _cache_get(cache, league, w) or collect_week(fx, league, w, ids, base)
        if not has_data(wk):
            break
        weeks_data.append(wk)
    for wk in weeks_data[:-1]:
        _cache_put(cache, league, wk)                                   # final: a later week already has stats
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


def _stdev(xs):
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5            # population standard deviation


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
                                              "winPct": _plain(win_pct(c["rec"][t])), "score": _plain(sc), "opp": o, "result": result}
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
    real = {}
    for t in ids:
        rec, exp = [0, 0, 0], Fraction(0)
        for w in weeks:
            wv = weekly[str(t)][str(w)]
            if wv["result"] is None:
                continue
            rec["WLT".index(wv["result"])] += 1
            exp += win_pct(wv["allPlay"]) or 0
        games = sum(rec)
        wins = Fraction(2 * rec[0] + rec[2], 2)
        real[t] = {"record": rec, "games": games, "realWins": wins, "expectedWins": exp, "luck": wins - exp, "pct": win_pct(rec) if games else None}
    rk = comp_rank({t: real[t]["pct"] for t in ids})
    realRecord = {str(t): {"record": real[t]["record"], "winPct": _plain(real[t]["pct"]), "realWins": _plain(real[t]["realWins"]),
                           "expectedWins": _plain(real[t]["expectedWins"]), "luck": _plain(real[t]["luck"]), "rank": rk[t]} for t in ids}
    realRank = rk
    # 5 category kings: the season leader and the best single week, per category
    kings = {}
    for sp in specs:
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
    # 6 boom / bust
    bb = {}
    for t in ids:
        tots = [(weekly[str(t)][str(w)]["total"], w) for w in weeks]
        sd = round(_stdev([x for x, _ in tots]), 9)
        bb[t] = {"best": {"week": max(tots, key=lambda x: (x[0], -x[1]))[1], "total": max(tots)[0]},
                 "worst": {"week": min(tots, key=lambda x: (x[0], x[1]))[1], "total": min(tots)[0]}, "stdev": sd}
    rk = comp_rank({t: bb[t]["stdev"] for t in ids}, high=False)
    boomBust = {str(t): dict(bb[t], rank=rk[t]) for t in ids}
    # 7 power rank: the plain average of the ranks on boards 1-4 (real record is ranked by its win%)
    comp = {t: {"seasonRoto": seasonRoto[str(t)]["rank"], "weeklyRoto": weeklyRoto[str(t)]["rank"], "seasonAllPlay": seasonAllPlay[str(t)]["rank"],
                "realRecord": realRank[t]} for t in ids}
    avg = {}
    for t in ids:
        got = [v for v in comp[t].values() if v is not None]
        avg[t] = Fraction(sum(got), len(got)) if got else None
    rk = comp_rank(avg, high=False)
    power = {str(t): {"ranks": comp[t], "avg": _plain(avg[t]), "rank": rk[t]} for t in ids}
    return {"weeks": weeks, "weekly": weekly, "seasonRoto": seasonRoto, "weeklyRoto": weeklyRoto, "seasonAllPlay": seasonAllPlay, "realRecord": realRecord,
            "categoryKings": kings, "boomBust": boomBust, "power": power}


def _wval(cores, week, t, sp):
    c = next(c for c in cores if c["week"] == week)
    return _plain(cat_value(c["tot"][t], sp))


def report(league, cache=None, delay=1.5, sport="nba", now=None):
    """The whole report: one view for the season and one per week that has stats, plus the season composites (what the page and the PNGs are drawn from)."""
    import datetime
    st, teams, weeks_data, _base = load(league, cache, delay, sport)
    headers = list(next(iter(weeks_data[0]["teams"].values()))["cols"])
    cats = st["categories"] or [h for h in headers if h and not h.endswith("M/A*")]
    specs, skipped = plan(cats, headers)
    if not specs:
        raise RotoError("none of the league's categories (%s) can be computed from the matchup pages" % ", ".join(cats))
    names = {t: teams.get(t) or next((wk["teams"][t]["name"] for wk in weeks_data if t in wk["teams"]), str(t)) for t in teams}
    ids = sorted(teams)
    cores = [_core(wk, specs) for wk in weeks_data]
    views = {"season": _season_view(cores, weeks_data, specs, ids)}
    for wk, c in zip(weeks_data, cores):
        views["w%d" % wk["week"]] = _week_view(c, wk, specs, ids)
    when = now or datetime.datetime.now(datetime.timezone.utc)
    return {"schema": "yahoo-roto-report/2", "league": str(league), "leagueName": st.get("name"), "sport": sport, "scoring": st["scoring"], "asOf": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inProgressWeek": weeks_data[-1]["week"], "categories": [{"cat": sp["cat"], "lower": sp["lower"], "pct": sp["kind"] == "pct"} for sp in specs],
            "skipped": skipped, "teams": {str(t): names[t] for t in names}, "weeks": [wk["week"] for wk in weeks_data], "views": views,
            "composites": composites(weeks_data, cores, specs, ids, views["season"])}


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
IMAGES = (("roto", 720), ("raw", 720), ("allplay", 1040))          # (view, css width); drawn at device scale 2.5


def write_html(doc, out_dir):
    """index.html = the page template with the report inlined: opens anywhere, offline, no server. Returns the path."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "index.html"), encoding="utf-8") as f:
        page = f.read()
    blob = json.dumps(doc, ensure_ascii=False).replace("</", "<\\/")
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


def write_images(html_path, out_dir, week=None, chrome=None):
    """Three PNGs (roto, raw stats, all-play) by screenshotting the page in headless Chrome at device scale 2.5. The page height is measured first so
    each image is exactly as tall as its table. Needs Google Chrome / Chromium; fonts come from Google Fonts (system fonts are used if offline)."""
    import subprocess
    chrome = chrome or find_chrome()
    if not chrome:
        raise RotoError("Chrome/Chromium not found: set $CHROME to its path to draw the images (the HTML file works without it)")
    base = ["--headless", "--disable-gpu", "--hide-scrollbars", "--no-sandbox", "--virtual-time-budget=20000"]
    paths = []
    for view, width in IMAGES:
        url = "file://%s?static=1&view=%s%s" % (html_path, view, "&week=%d" % week if week else "")
        dom = subprocess.run([chrome] + base + ["--window-size=%d,1000" % width, "--dump-dom", url], capture_output=True, text=True, timeout=120).stdout
        m = re.search(r'name="report-height"[^>]*content="(\d+)"|content="(\d+)"[^>]*name="report-height"', dom)
        if not m:
            raise RotoError("could not measure the %s page (Chrome printed no document)" % view)
        height = int(m.group(1) or m.group(2)) + 8
        path = os.path.join(out_dir, "%s.png" % view)
        subprocess.run([chrome] + base + ["--force-device-scale-factor=2.5", "--window-size=%d,%d" % (width, height), "--screenshot=" + path, url],
                       capture_output=True, timeout=120)
        if not os.path.exists(path):
            raise RotoError("Chrome did not write %s" % path)
        paths.append(path)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("league", help="the Yahoo league id (the number in the league's URL)")
    ap.add_argument("--week", type=int, help="one week only")
    ap.add_argument("--through", type=int, help="season roto through this week")
    ap.add_argument("--sport", default="nba", choices=sorted(SPORTS), help="default nba (categories and pages are verified for NBA only)")
    ap.add_argument("--cache", help="directory to keep fetched pages in")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests (default 1.5)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", metavar="DIR", help="write DIR/report.json and a self-contained DIR/index.html (all weeks, all three views)")
    ap.add_argument("--png", action="store_true", help="with --report: also draw DIR/roto.png, raw.png, allplay.png (needs Chrome)")
    a = ap.parse_args(argv)
    try:
        if a.report:
            doc = report(a.league, a.cache, a.delay, a.sport)
            path = write_html(doc, a.report)
            print("wrote %s and report.json (weeks %s, week %d in progress)" % (path, ", ".join(map(str, doc["weeks"])), doc["inProgressWeek"]))
            if a.png:
                for p in write_images(os.path.abspath(path), a.report, a.week):
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
