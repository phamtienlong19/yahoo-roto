#!/usr/bin/env python3
"""How long the live workflow should sleep before its next pass. Standard library only.

The old rule was the clock alone (every 4 min in US game hours, every 15 otherwise). This one watches the data instead: when Yahoo's totals changed on the
last pass, games are being played, so stay fast; the longer nothing changes, the longer the sleep, up to hourly in the offseason. The clock only sets a ceiling,
so the first stats of a new game day are still noticed within minutes. Nothing here needs another website: a game feed is an optional extra (`games=`).

    python3 cadence.py record STATE LEAGUE REPORT_JSON    # prints "changed" or "same"; remembers the report's fingerprint
    python3 cadence.py delay STATE                        # prints the seconds to sleep before the next pass
    python3 cadence.py fail STATE LEAGUE MESSAGE...       # a pass for this league failed: count it and remember why
    python3 cadence.py status STATE OUT_JSON              # writes the public status file the page reads when its data looks old
    python3 cadence.py alerts STATE [N]                   # prints the leagues that have now failed N times in a row (once per outage)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

FAST = 180             # seconds between passes while stats are moving (about 12 Yahoo requests per league per pass: stay polite)
SLOW_HOUR = 3600       # the longest sleep, used when nothing has changed for days (offseason, long break)
GAME_HOURS_CAP = 600   # in US game hours (and on weekend afternoons) never sleep longer than this: a tip-off is noticed within 10 minutes
OTHER_CAP = 1800       # outside game hours never sleep longer than this


def fingerprint(doc):
    """A hash of everything in a report except the timestamp, so 'same' means no number moved."""
    d = {k: v for k, v in doc.items() if k != "asOf"}
    return hashlib.sha1(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) and isinstance(s.get("leagues"), dict) else {"leagues": {}}
    except (OSError, ValueError):
        return {"leagues": {}}


def save_state(path, state):
    write_atomic(path, json.dumps(state, separators=(",", ":")))


def write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)                                             # a run killed mid-write must not leave a broken file on the data branch


def record(state, league, doc, now):
    """Remember this report's fingerprint. True when it differs from the last one. A league seen for the first time counts as changed (it starts fast)."""
    fp = fingerprint(doc)
    cur = state["leagues"].setdefault(str(league), {})
    cur.update({"last_ok": now, "fails": 0})                          # a good pass ends any outage
    for k in ("last_error", "fail_since", "alerted"):
        cur.pop(k, None)
    changed = cur.get("fp") != fp
    cur["fp"] = fp
    if changed:
        cur["changed_at"] = now
    return changed


ALERT_AFTER = 5       # passes in a row that failed before someone is told (about 15-60 minutes, depending on the pace)


def note_failure(state, league, error, now):
    cur = state["leagues"].setdefault(str(league), {})
    cur["fails"] = cur.get("fails", 0) + 1
    cur["last_error"] = " ".join(str(error).split())[:300]
    cur.setdefault("fail_since", now)


def public_status(state, now):
    """What the page may show when a report looks old: per league the last good pass, the failure count, since when, and why."""
    return {"updated": int(now), "leagues": {k: {"lastOk": v.get("last_ok"), "fails": v.get("fails", 0), "since": v.get("fail_since"), "error": v.get("last_error")}
                                              for k, v in sorted(state.get("leagues", {}).items())}}


def due_alerts(state, threshold=ALERT_AFTER):
    """Leagues whose failures have reached `threshold` and that nobody was told about yet; marks them so one outage raises one alert."""
    out = []
    for k, v in sorted(state.get("leagues", {}).items()):
        if v.get("fails", 0) >= threshold and not v.get("alerted"):
            v["alerted"] = True
            out.append(k)
    return out


def quiet_for(state, now):
    """Seconds since any league's numbers last moved (a huge number when nothing was ever recorded)."""
    times = [v.get("changed_at") for v in state.get("leagues", {}).values() if v.get("changed_at") is not None]
    return now - max(times) if times else 10 ** 9


def game_hours(hour_utc, weekday):
    """US evening games run roughly 22:00-07:00 UTC; weekend games start earlier (from 16:00 UTC). weekday: Monday=1 ... Sunday=7."""
    return hour_utc >= 22 or hour_utc <= 7 or (hour_utc >= 16 and weekday >= 6)


def delay(quiet, hour_utc, weekday, games=None):
    """Seconds to sleep. `quiet` = seconds since the numbers last moved. `games` (optional) = [{"status": 1|2|3, "start": epoch}] from a game feed:
    a live game means stay fast; a tip-off soon means wake up for it."""
    if games:
        if any(g.get("status") == 2 for g in games):
            return FAST
    if quiet < 20 * 60:
        base = FAST
    elif quiet < 60 * 60:
        base = 300
    elif quiet < 3 * 3600:
        base = 600
    elif quiet < 12 * 3600:
        base = 1800
    else:
        base = SLOW_HOUR
    if quiet > 3 * 86400:
        return SLOW_HOUR                                              # nothing for days: the season is over or paused
    return min(base, GAME_HOURS_CAP if game_hours(hour_utc, weekday) else OTHER_CAP)


def next_delay(state, now=None, games=None):
    now = time.time() if now is None else now
    t = time.gmtime(now)
    return delay(quiet_for(state, now), t.tm_hour, t.tm_wday + 1, games)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["record"] and len(a) == 4:
        state = load_state(a[1])
        try:
            with open(a[3], encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            print("error: cannot read %s (%s)" % (a[3], e), file=sys.stderr)
            return 2
        changed = record(state, a[2], doc, time.time())
        save_state(a[1], state)
        print("changed" if changed else "same")
        return 0
    if a[:1] == ["delay"] and len(a) == 2:
        print(next_delay(load_state(a[1])))
        return 0
    if a[:1] == ["fail"] and len(a) >= 3:
        state = load_state(a[1])
        note_failure(state, a[2], " ".join(a[3:]), time.time())
        save_state(a[1], state)
        return 0
    if a[:1] == ["status"] and len(a) == 3:
        write_atomic(a[2], json.dumps(public_status(load_state(a[1]), time.time()), separators=(",", ":")))
        return 0
    if a[:1] == ["alerts"] and len(a) in (2, 3):
        state = load_state(a[1])
        ids = due_alerts(state, int(a[2]) if len(a) == 3 else ALERT_AFTER)
        save_state(a[1], state)
        print(" ".join(ids))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
