"""A made-up 18-team league pushed through the real pipeline (settings, standings and matchup pages -> report), for tests that need realistic multi-week data.
The pages are generated, not recorded; they only follow the shape Yahoo's pages have."""
import os
import random
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import yahoo_roto as yr  # noqa: E402

NAMES = ["Cuckoo", "Chicken Wings", "Angry Bird", "Dial Square", "Tiến Delay", "Under Armour", "sup fam", "DonTrick DevilTeam", "TO KINH", "ecstasy", "bounce island",
         "J1nple", "Abcxyz", "MNQA", "Rip City Remix", "Run and Gun", "Clutch City Rockets", "Seattle SuperSonics"]
SETTINGS = ("<html><body>League Name: Test League League Logo: x Scoring Type: Head-to-Head - Categories Max Acquisitions for Entire Season: No maximum "
            "Make League Publicly Viewable: Yes Stat Categories: Field Goal Percentage (FG%), Free Throw Percentage (FT%), 3-point Shots Made (3PTM), Points Scored (PTS), "
            "Total Rebounds (REB), Assists (AST), Steals (ST), Blocks (BLK), Turnovers (TO) Stat Modifiers: none Roster Positions: PG</body></html>")


class FakeFetcher(yr.Fetcher):
    def __init__(self, pages):
        super().__init__(delay=0)
        self.pages = pages

    def get(self, url, ttl=None):
        for k, v in self.pages.items():
            if url.endswith(k):
                return v
        raise yr.RotoError("unexpected " + url)


def build_pages(n=18, weeks=4, seed=7, regular=None, divisions=False, spots=6):
    """Pages for a league with stats in `weeks` weeks (the last one counts as in progress) and one empty week after it. With `regular` the settings page also
    states a playoff (`spots` teams from week regular+1) and the empty weeks run up to the end of the regular season; `divisions` splits the standings page in East / West."""
    rnd = random.Random(seed)
    strength = [rnd.gauss(0, 1) for _ in range(n)]
    names = (NAMES * 3)[:n]

    def stats(i):
        s = strength[i]
        fgm = rnd.randint(280, 330)
        fga = int(fgm / (0.46 + 0.01 * s + rnd.gauss(0, 0.015)))
        ftm = rnd.randint(70, 95)
        fta = int(ftm / (0.80 + rnd.gauss(0, 0.03)))
        return ["%d/%d" % (fgm, fga), "%.3f" % (fgm / fga), "%d/%d" % (ftm, fta), "%.3f" % (ftm / fta), str(int(rnd.gauss(40 + 4 * s, 8))), str(int(rnd.gauss(450 + 30 * s, 25))),
                str(int(rnd.gauss(110 + 10 * s, 12))), str(int(rnd.gauss(65 + 5 * s, 9))), str(int(rnd.gauss(18 + 2 * s, 4))), str(int(rnd.gauss(14 + 2 * s, 4))), str(int(rnd.gauss(35, 6)))]

    last = max(weeks + 1, (regular or 0) + 3)

    def page(week, pair, data):
        opts = "".join('<option value="x?module=matchup&week=%d"%s>%d</option>' % (w, " selected" if w == week else "", w) for w in range(1, last + 1))
        rows = "".join('<tr><td><a href="/nba/9/%d">%s</a></td>%s<td>%s</td></tr>' % (t + 1, names[t], "".join("<td>%s</td>" % x for x in data[t]["v"]), data[t]["sc"]) for t in pair)
        return ("<select>%s</select><table><tr><th>Team</th><th>FGM/A*</th><th>FG%%</th><th>FTM/A*</th><th>FT%%</th><th>3PTM</th><th>PTS</th><th>REB</th><th>AST</th><th>ST</th>"
                "<th>BLK</th><th>TO</th><th></th></tr>%s</table>" % (opts, rows))

    settings = SETTINGS if not regular else SETTINGS.replace("Stat Modifiers", "Playoffs: %d teams - Week %d, %d and %d Playoff Seeding Options: Division winners advance but seeded by overall standings Lock Benched Players: No Stat Modifiers" % (spots, regular + 1, regular + 2, regular + 3))
    if divisions:
        rows = "".join(('<tr><td><h4>%s</h4></td></tr>' % d if i in (0, n // 2) else "") + '<tr><td><a href="/nba/9/%d">%s</a></td></tr>' % (i + 1, names[i]) for i, d in ((i, "East" if i < n // 2 else "West") for i in range(n)))
    else:
        rows = "".join('<tr><td><a href="/nba/9/%d">%s</a></td></tr>' % (i + 1, names[i]) for i in range(n))
    pages = {"settings": settings}
    record = [[0, 0, 0] for _ in range(n)]                                  # category W-L-T over the finished weeks: what Yahoo's own standings table shows
    for w in range(1, last + 1):
        order = list(range(n))
        random.Random(w).shuffle(order)
        pairs = [order[i:i + 2] for i in range(0, n, 2)]
        data = {t: {"v": (["-/-", "-", "-/-", "-", "-", "-", "-", "-", "-", "-", "-"] if w > weeks else stats(t)), "sc": "-"} for t in range(n)}
        if w <= weeks:
            for a, b in pairs:
                wins = sum(1 for i in (1, 3, 4, 5, 6, 7, 8, 9) if float(data[a]["v"][i]) > float(data[b]["v"][i])) + (1 if float(data[a]["v"][10]) < float(data[b]["v"][10]) else 0)
                data[a]["sc"], data[b]["sc"] = str(wins), str(9 - wins)
                if w < weeks:
                    won = [(float(data[a]["v"][i]) > float(data[b]["v"][i])) - (float(data[a]["v"][i]) < float(data[b]["v"][i])) for i in (1, 3, 4, 5, 6, 7, 8, 9)]
                    won.append((float(data[a]["v"][10]) < float(data[b]["v"][10])) - (float(data[a]["v"][10]) > float(data[b]["v"][10])))
                    for t, sign in ((a, 1), (b, -1)):
                        for r in won:
                            record[t][0 if r * sign > 0 else 1 if r * sign < 0 else 2] += 1
        for a, b in pairs:
            for t in (a, b):
                pages["week=%d&mid1=%d" % (w, t + 1)] = page(w, [a, b], data)
    pct = [(r[0] + r[2] / 2) / max(1, sum(r)) for r in record]
    for i in range(n):                                                      # the records go into the standings rows
        rank = 1 + sum(1 for p in pct if p > pct[i])
        rows = rows.replace('<tr><td><a href="/nba/9/%d">%s</a></td></tr>' % (i + 1, names[i]),
                            '<tr><td>%d</td><td><a href="/nba/9/%d">%s</a></td><td>%d-%d-%d</td></tr>' % ((rank, i + 1, names[i]) + tuple(record[i])))
    pages["lhst=stand"] = "<table><tr><th>Rank</th><th>Team</th><th>W-L-T</th></tr>" + rows + "</table>"
    return pages


def build_report(n=18, weeks=4, seed=7, champion="sup fam", cache=None, drop=(), fast=True, **kw):
    """`fast` runs the playoff simulation with fewer seasons (tests that check the real settings pass fast=False)."""
    saved = (yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS)
    if fast:
        yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS = 10000, 500, 2000
    try:
        return _build_report(n, weeks, seed, champion, cache, drop, **kw)
    finally:
        yr.SIMS, yr.STRENGTH_DRAWS, yr.HIST_SIMS = saved


def _build_report(n, weeks, seed, champion, cache, drop, **kw):
    pages = build_pages(n, weeks, seed, **kw)
    for k in [k for k in pages if any(k.startswith("week=%d&" % w) for w in drop)]:         # weeks whose pages cannot be read
        del pages[k]
    fx, orig = FakeFetcher(pages), yr.Fetcher
    yr.Fetcher = lambda **k: fx
    try:
        return yr.report("9", champion=champion, cache=cache)
    finally:
        yr.Fetcher = orig
