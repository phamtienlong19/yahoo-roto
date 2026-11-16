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


def build_pages(n=18, weeks=4, seed=7):
    """Pages for a league with stats in `weeks` weeks (the last one counts as in progress) and one empty week after it."""
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

    def page(week, pair, data):
        opts = "".join('<option value="x?module=matchup&week=%d"%s>%d</option>' % (w, " selected" if w == week else "", w) for w in range(1, weeks + 2))
        rows = "".join('<tr><td><a href="/nba/9/%d">%s</a></td>%s<td>%s</td></tr>' % (t + 1, names[t], "".join("<td>%s</td>" % x for x in data[t]["v"]), data[t]["sc"]) for t in pair)
        return ("<select>%s</select><table><tr><th>Team</th><th>FGM/A*</th><th>FG%%</th><th>FTM/A*</th><th>FT%%</th><th>3PTM</th><th>PTS</th><th>REB</th><th>AST</th><th>ST</th>"
                "<th>BLK</th><th>TO</th><th></th></tr>%s</table>" % (opts, rows))

    pages = {"settings": SETTINGS, "lhst=stand": "<table><tr><th>Team</th></tr>" + "".join('<tr><td><a href="/nba/9/%d">%s</a></td></tr>' % (i + 1, names[i]) for i in range(n)) + "</table>"}
    for w in range(1, weeks + 2):
        order = list(range(n))
        random.Random(w).shuffle(order)
        pairs = [order[i:i + 2] for i in range(0, n, 2)]
        data = {t: {"v": (["-/-", "-", "-/-", "-", "-", "-", "-", "-", "-", "-", "-"] if w > weeks else stats(t)), "sc": "-"} for t in range(n)}
        if w <= weeks:
            for a, b in pairs:
                wins = sum(1 for i in (1, 3, 4, 5, 6, 7, 8, 9) if float(data[a]["v"][i]) > float(data[b]["v"][i])) + (1 if float(data[a]["v"][10]) < float(data[b]["v"][10]) else 0)
                data[a]["sc"], data[b]["sc"] = str(wins), str(9 - wins)
        for a, b in pairs:
            for t in (a, b):
                pages["week=%d&mid1=%d" % (w, t + 1)] = page(w, [a, b], data)
    return pages


def build_report(n=18, weeks=4, seed=7, champion="sup fam"):
    fx, orig = FakeFetcher(build_pages(n, weeks, seed)), yr.Fetcher
    yr.Fetcher = lambda **k: fx
    try:
        return yr.report("9", champion=champion)
    finally:
        yr.Fetcher = orig
