"""Per-league addresses for GitHub Pages: writes <id>/index.html (a copy of index.html) for every league in leagues.json, so
https://<owner>.github.io/<repo>/<id>/ opens that league. The page reads the league id from its own path. Run after editing index.html or leagues.json:
    python3 pages.py
tests/test_pages.py fails when the copies are out of date."""
import html as _html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def league_ids(root=HERE):
    with open(os.path.join(root, "leagues.json"), encoding="utf-8") as f:
        return [str(x) for x in json.load(f)["leagues"]]


def league_names(root=HERE):
    with open(os.path.join(root, "leagues.json"), encoding="utf-8") as f:
        return {str(k): v for k, v in json.load(f).get("names", {}).items()}


def league_cups(root=HERE):
    """The leagues that are cups (leagues.json "cups"): their own copy of the page gets the cup skin and its font from the first byte."""
    with open(os.path.join(root, "leagues.json"), encoding="utf-8") as f:
        return {str(k) for k in (json.load(f).get("cups") or {})}


CUP_FONT = "&family=Manrope:wght@500;600;700;800"


def render(page, name=None, cup=False):
    """The page for one league: its own <title>, description and link-preview tags (chat apps read these without running any JavaScript)."""
    if cup:
        page = page.replace('<div class="wrap">', '<div class="wrap cup">', 1)
        page = page.replace('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&family=Geist+Mono:wght@500;600;700&display=swap"',
                            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&family=Geist+Mono:wght@500;600;700%s&display=swap"' % CUP_FONT, 1)
    if not name:
        return page
    n = _html.escape(name, quote=True)
    desc = "Roto points, raw category totals, an all-play matrix, luck and power rank for %s." % n
    block = ('<!--meta--><title>%s \u00b7 Roto standings</title>\n<meta name="description" content="%s">\n'
             '<meta property="og:type" content="website"><meta property="og:title" content="%s"><meta property="og:description" content="%s"><meta name="twitter:card" content="summary"><!--/meta-->'
             % (n, desc, n, desc))
    return re.sub(r"<!--meta-->.*?<!--/meta-->", lambda m: block, page, count=1, flags=re.S)


def sync(root=HERE):
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        page = f.read()
    names = league_names(root)
    cups = league_cups(root)
    paths = []
    for lid in league_ids(root):
        os.makedirs(os.path.join(root, lid), exist_ok=True)
        path = os.path.join(root, lid, "index.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(page, names.get(lid), lid in cups))
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in sync():
        print("wrote", os.path.relpath(p, HERE))
