"""Per-league addresses for GitHub Pages: writes <id>/index.html (a copy of index.html) for every league in leagues.json, so
https://<owner>.github.io/<repo>/<id>/ opens that league. The page reads the league id from its own path. Run after editing index.html or leagues.json:
    python3 pages.py
tests/test_pages.py fails when the copies are out of date."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def league_ids(root=HERE):
    with open(os.path.join(root, "leagues.json"), encoding="utf-8") as f:
        return [str(x) for x in json.load(f)["leagues"]]


def sync(root=HERE):
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        page = f.read()
    paths = []
    for lid in league_ids(root):
        os.makedirs(os.path.join(root, lid), exist_ok=True)
        path = os.path.join(root, lid, "index.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in sync():
        print("wrote", os.path.relpath(p, HERE))
