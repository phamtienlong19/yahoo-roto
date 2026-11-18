#!/usr/bin/env python3
"""Safe publishing of the orphan `data` branch (used by .github/workflows/roto-live.yml).

The live workflow keeps its state (finished weeks, odds, and later the append-only game-count history) on the
`data` branch and replaces that branch every pass. This module makes that safe:

  restore  fetch the branch, prove the copy is complete (manifest and blob ids), validate the policed files
  publish  refuse any publish that would lose or alter protected history, then push with a compare-and-swap lease
  alert    open (or comment on) one issue, annotate the run, write the step summary

Exit codes. restore: 0 restored or branch absent (prints BASE=<sha or empty>), 3 transient, 4 integrity.
publish: 0 pushed (prints BASE=<new sha>), 3 transient, 4 policy violation, 5 lease rejected (remote moved).
Standard library only. The remote URL (it carries the token) is redacted from everything printed.
"""
import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

FORMATS = {"games": 1, "chain": 1}          # data formats this code writes; a writer older than the branch is refused
CHAIN = "sha256/20"
WRITER = "_cache/_writer.json"
STRICT, WEEK, PERSIST, JSON_OK, STAMP = "strict_chain", "week", "persist", "valid_json", "writer_stamp"
KEEP = (STRICT, WEEK, PERSIST)               # policies under which a file may never disappear
POLICIES = [                                 # first match wins; a path that matches nothing carries no constraint
    (WRITER, STAMP),
    ("_cache/*-games.json", STRICT), ("_cache/*-forecast-log.json", STRICT),
    ("_cache/*-week-*.json", WEEK),
    ("_cache/*-odds-history.json", JSON_OK), ("_cache/*-schedule.json", JSON_OK), ("_cache/*-odds.json", JSON_OK),
    ("_cache/*-corrections.json", JSON_OK), ("status.json", JSON_OK),
]
TITLE = "Roto publish blocked"


# ---- the hash chain (append-only files) ---------------------------------------------------------------------
def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_id(prev_id, row):
    body = {k: v for k, v in row.items() if k != "id"}
    return hashlib.sha256(((prev_id or "") + "\n" + canonical(body)).encode("utf-8")).hexdigest()[:20]


def chain_error(doc):
    """None when `doc` is a well-formed chain whose ids and head all recompute, else why not."""
    if not isinstance(doc, dict) or doc.get("v") != 1 or doc.get("chain") != CHAIN or not isinstance(doc.get("rows"), list):
        return "not a v1 %s chain" % CHAIN
    prev = ""
    for i, row in enumerate(doc["rows"]):
        if not isinstance(row, dict) or row.get("id") != row_id(prev, row):
            return "row %d does not continue the chain" % i
        prev = row["id"]
    return None if doc.get("head") == prev else "head is not the last row id"


def chain_extends(old, new):
    """None when `new` keeps every row of `old` in the same order (equal ids imply equal contents), else why not."""
    n = len(old["rows"])
    if len(new["rows"]) < n:
        return "lost %d row(s)" % (n - len(new["rows"]))
    return None if [r["id"] for r in new["rows"][:n]] == [r["id"] for r in old["rows"]] else "an earlier row changed or moved"


# ---- policies -----------------------------------------------------------------------------------------------
def files(root):
    out = set()
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        out.update(os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/") for n in names)
    return out


def policy_of(rel, leagues):
    m = re.fullmatch(r"(\d+)/report\.json", rel)
    if m and m.group(1) in leagues:
        return PERSIST
    for pat, pol in POLICIES:
        if fnmatch.fnmatchcase(rel, pat):
            return pol
    return None


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as e:
        return None, "unreadable (%s)" % str(e)[:80]


def validate(path, pol):
    """None when the file is acceptable under its own policy, else why not."""
    doc, err = read_json(path)
    if err:
        return err
    if pol == STRICT:
        return chain_error(doc)
    if pol == WEEK and not (isinstance(doc, dict) and doc.get("v") in (2, 3)):
        return "week file with an unknown format version"
    if pol == STAMP and not (isinstance(doc, dict) and isinstance(doc.get("formats"), dict)
                             and all(isinstance(v, int) for v in doc["formats"].values())):
        return "writer stamp without integer formats"
    return None


def invalid(tree, leagues, skip=None):
    """Every policed file in `tree` (except `skip`) that fails its own policy, as 'path: why'."""
    out = []
    for rel in sorted(files(tree)):
        pol = policy_of(rel, leagues)
        why = pol and rel != skip and validate(os.path.join(tree, rel), pol)
        if why:
            out.append("%s: %s" % (rel, why))
    return out


def load_leagues(path):
    doc, err = read_json(path)
    return {str(x) for x in doc.get("leagues", [])} if not err and isinstance(doc, dict) else set()


def check(prev, out, leagues, exempt=()):
    """Every way publishing `out` over `prev` would break a policy; empty when it is safe."""
    bad = []
    for rel in sorted(files(prev) | files(out)):
        pol = policy_of(rel, leagues)
        if rel in exempt or not pol:
            continue
        p, o = os.path.join(prev, rel), os.path.join(out, rel)
        if os.path.exists(o) and validate(o, pol):
            bad.append("%s: new copy invalid: %s" % (rel, validate(o, pol)))
            continue
        if not os.path.exists(p):
            continue
        if validate(p, pol):
            bad.append("%s: prior copy invalid: %s" % (rel, validate(p, pol)))
        elif not os.path.exists(o):
            if pol in KEEP:
                bad.append("%s: present before, missing now" % rel)
        elif pol == STRICT:
            why = chain_extends(read_json(p)[0], read_json(o)[0])
            if why:
                bad.append("%s: history not preserved: %s" % (rel, why))
        elif pol == STAMP:
            old, new = read_json(p)[0]["formats"], read_json(o)[0]["formats"]
            for k, v in old.items():
                if new.get(k, -1) < v:
                    bad.append("%s: writer is older than the branch (format %s: %s < %s)" % (rel, k, new.get(k), v))
    return bad


# ---- git plumbing -------------------------------------------------------------------------------------------
def run(cmd, cwd=None, data=None):
    return subprocess.run(cmd, cwd=cwd, input=data, capture_output=True)


def secrets(remote):
    return [s for s in (os.environ.get("GITHUB_TOKEN"), remote if remote and "@" in remote else None) if s and len(s) > 3]


def say(msg, remote=None):
    for s in secrets(remote):
        msg = msg.replace(s, "***")
    print(msg, file=sys.stderr)


def tail(r):
    return (r.stderr or b"").decode("utf-8", "replace").strip()[-300:]


def manifest(sha):
    """[(path, blob id, size)] of every file in the commit; None when something other than a plain file is in it."""
    r = run(["git", "ls-tree", "-r", "-l", "-z", sha])
    if r.returncode:
        return None
    out = []
    for ent in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if not ent:
            continue
        meta, path = ent.split("\t", 1)
        mode, kind, oid, size = meta.split()
        if kind != "blob" or mode == "120000" or "\n" in path:
            return None
        out.append((path, oid, int(size)))
    return out


def verify(tree, entries):
    """Why the extracted tree is not exactly the commit's, or None. Same paths, sizes and blob ids."""
    if files(tree) != {p for p, _, _ in entries}:
        return "the file list differs from the commit's"
    for p, _, size in entries:
        if os.path.getsize(os.path.join(tree, p)) != size:
            return "size differs: " + p
    base = os.path.abspath(tree)       # absolute: inside a checkout git would resolve relative paths against the top level
    r = run(["git", "hash-object", "--no-filters", "--stdin-paths"], data=("\n".join(os.path.join(base, p) for p, _, _ in entries) + "\n").encode("utf-8", "surrogateescape"))
    got = r.stdout.decode().split()
    if r.returncode or got != [o for _, o, _ in entries]:
        return "a blob id differs from the commit's"
    return None


def swap(src, dst):
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    os.replace(src, dst)


def cmd_restore(a):
    remote = a.remote or os.environ.get("DATA_REMOTE") or "origin"
    ls = run(["git", "ls-remote", "--exit-code", "--heads", remote, a.branch])
    if ls.returncode == 2:                      # the branch genuinely does not exist yet
        for d in (a.prev, os.path.join(a.cache, "_cache")):
            os.makedirs(d, exist_ok=True)
        print("BASE=")
        return 0
    if ls.returncode or run(["git", "fetch", "-q", "--depth=1", remote, a.branch]).returncode:
        say("restore: could not read the %s branch (transient): %s" % (a.branch, tail(ls)), remote)
        return 3
    sha = run(["git", "rev-parse", "FETCH_HEAD"]).stdout.decode().strip()
    entries = manifest(sha)
    tmp = tempfile.mkdtemp(prefix=".restore-", dir=os.path.dirname(os.path.abspath(a.prev)) or ".")
    try:
        arc = run(["git", "archive", sha])
        if entries is None or arc.returncode:
            say("restore: cannot list or archive %s" % sha)
            return 4
        try:
            with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as t:
                t.extractall(tmp, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        except (tarfile.TarError, OSError) as e:
            say("restore: the archive did not unpack: %s" % e)
            return 4
        why = verify(tmp, entries)
        bad = [] if why else invalid(tmp, load_leagues(a.leagues), a.quarantine)
        if why or bad:
            say("restore: INTEGRITY FAILURE on %s: %s" % (sha, why or "; ".join(bad)))
            return 4
        cdir = tmp + ".cache"
        if os.path.isdir(os.path.join(tmp, "_cache")):
            shutil.copytree(os.path.join(tmp, "_cache"), cdir)
        else:
            os.makedirs(cdir)
        swap(cdir, os.path.join(a.cache, "_cache"))
        swap(tmp, a.prev)
        print("BASE=" + sha)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_publish(a):
    leagues = load_leagues(a.leagues)
    exempt = set()
    if a.quarantine:                            # manual repair: keep the prior bytes under _quarantine/, start that file afresh
        exempt.add(a.quarantine)
        src = os.path.join(a.prev, a.quarantine)
        if os.path.exists(src):
            dst = os.path.join(a.out, "_quarantine", "%s-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.path.basename(src)))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        for root in (a.out, a.cache):
            if root and os.path.exists(os.path.join(root, a.quarantine)):
                os.remove(os.path.join(root, a.quarantine))
    os.makedirs(os.path.join(a.out, "_cache"), exist_ok=True)
    with open(os.path.join(a.out, WRITER), "w", encoding="utf-8") as f:
        json.dump({"code": os.environ.get("GITHUB_SHA", ""), "formats": FORMATS}, f, sort_keys=True)
    bad = check(a.prev, a.out, leagues, exempt)
    if bad:
        say("publish: BLOCKED, nothing pushed:\n  " + "\n  ".join(bad))
        return 4
    remote = a.remote or os.environ.get("DATA_REMOTE")
    if not remote and os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        remote = "https://x-access-token:%s@github.com/%s.git" % (os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    if not remote:
        say("publish: no remote (set DATA_REMOTE, or GITHUB_TOKEN and GITHUB_REPOSITORY)")
        return 3
    g = ["git", "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
    ref = "refs/heads/" + a.branch
    steps = [["git", "init", "-q", "-b", a.branch], ["git", "add", "-A"], g + ["commit", "-q", "-m", "roto " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())]]
    for s in steps:
        r = run(s, cwd=a.out)
        if r.returncode:
            say("publish: %s failed: %s" % (s[-1], tail(r)), remote)
            return 3
    r = run(["git", "push", "-q", "--force-with-lease=%s:%s" % (ref, a.base), remote, "HEAD:" + ref], cwd=a.out)
    if r.returncode:
        stale = b"stale info" in r.stderr or b"[rejected]" in r.stderr
        say("publish: %s: %s" % ("LEASE REJECTED, the %s branch moved since it was restored" % a.branch if stale else "push failed (transient)", tail(r)), remote)
        return 5 if stale else 3
    print("BASE=" + run(["git", "rev-parse", "HEAD"], cwd=a.out).stdout.decode().strip())
    return 0


def cmd_alert(a):
    why = " ".join(a.message)
    url = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"), os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", ""))
    print("::error title=%s::%s" % (TITLE, why))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        try:
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("### %s\n\n%s\n\n[run log](%s)\n" % (TITLE, why, url))
        except OSError:
            pass
    body = "%s\n\nThe live workflow stopped publishing the data branch, so the public reports stop updating. Nothing was overwritten.\n\nRun: %s" % (why, url)
    try:
        r = run(["gh", "issue", "list", "--state", "open", "--search", "%s in:title" % TITLE, "--json", "number", "--jq", ".[0].number // empty"])
        n = r.stdout.decode().strip()
        run(["gh", "issue", "comment", n, "--body", body] if n else ["gh", "issue", "create", "--title", TITLE, "--body", body])
    except OSError:
        say("alert: gh is not available")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("restore", "publish"):
        s = sub.add_parser(name)
        s.add_argument("--branch", default="data")
        s.add_argument("--remote")
        s.add_argument("--leagues", default="leagues.json")
        s.add_argument("--quarantine")
        s.add_argument("--prev", required=True)
        s.add_argument("--cache", required=(name == "restore"), default=None)
        if name == "publish":
            s.add_argument("--out", required=True)
            s.add_argument("--base", default="")
    sub.add_parser("alert").add_argument("message", nargs="+")
    a = p.parse_args(argv)
    if getattr(a, "branch", None) is not None and not re.fullmatch(r"[A-Za-z0-9._/-]{1,60}", a.branch):
        sys.exit("bad branch name")
    if getattr(a, "quarantine", None) and not re.fullmatch(r"_cache/[A-Za-z0-9._-]+", a.quarantine):
        sys.exit("quarantine must be a file directly under _cache/")
    return {"restore": cmd_restore, "publish": cmd_publish, "alert": cmd_alert}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
