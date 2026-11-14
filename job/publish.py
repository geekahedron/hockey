"""Write the static JSON the public page reads.

Layout of the publish directory (rsynced to public_html/tools/hockey/data/):

    today.json
    season.json
    days/index.json
    days/YYYY-MM-DD.json

Secrets never belong in this tree. assert_public refuses documents that
carry another site's pick brand, a credential key, or a TIMS_ secret.
"""
import json
import os
import re

_BANNED_SUBSTRINGS = (
    "datadrivenhockey",
    "hockeychallengehelper",
)
_BANNED_WORDS = ("ddh", "hch")
_WORD = re.compile(r"[a-z0-9]+")
_SECRET_KEYS = {
    "authorization", "cookie", "token", "password", "secret",
    "tims_bearer", "tims_cookie", "tims_env",
}


class PublishError(Exception):
    pass


def assert_public(obj):
    """Raise PublishError if ``obj`` would publish a secret or a banned brand."""
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                _check_text(str(key), "key")
                if str(key).lower() in _SECRET_KEYS:
                    raise PublishError("refusing to publish a secret field")
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            _check_text(node, "value")
    def _check_text(text, kind):
        low = text.lower()
        for banned in _BANNED_SUBSTRINGS:
            if banned in low:
                raise PublishError("refusing to publish banned content")
        words = set(_WORD.findall(low))
        for banned in _BANNED_WORDS:
            if banned in words:
                raise PublishError("refusing to publish banned content")
    walk(obj)


def _atomic_write(path, obj):
    assert_public(obj)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def _check_date(iso):
    if not isinstance(iso, str) or len(iso) != 10 or iso[4] != "-" or iso[7] != "-":
        raise PublishError("bad slate date")
    year, month, day = iso.split("-")
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        raise PublishError("bad slate date")
    return iso


def day_path(publish_dir, iso):
    return os.path.join(publish_dir, "days", _check_date(iso) + ".json")


def load_day(publish_dir, iso):
    path = day_path(publish_dir, iso)
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def list_days(publish_dir):
    folder = os.path.join(publish_dir, "days")
    if not os.path.isdir(folder):
        return []
    days = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == "index.json":
            continue
        with open(os.path.join(folder, name)) as handle:
            days.append(json.load(handle))
    days.sort(key=lambda day: day.get("date") or "")
    return days


def publish_day(publish_dir, day, as_today=False):
    """Write days/DATE.json and rebuild the index and season tracker.

    When ``as_today`` is set, also replace today.json with this slate.
    """
    iso = _check_date(day.get("date"))
    _atomic_write(day_path(publish_dir, iso), day)
    if as_today:
        _atomic_write(os.path.join(publish_dir, "today.json"), day)
    return rebuild(publish_dir)


def _round(value, places=4):
    if value is None:
        return None
    return round(float(value), places)


def build_season(days):
    """Per-day picks plus a running hit rate, top-3 hits, and a random baseline.

    Pending groups are listed and do not move the running totals. The running
    hit rate is cumulative hits over cumulative graded picks. A tied pick
    contributes its fractional hit (1, 0, or in between).
    """
    running_hits = 0.0
    running_picks = 0
    running_top3 = 0
    running_top3_slots = 0
    running_random_sum = 0.0
    running_random_n = 0
    season_name = None
    out_days = []
    for day in days:
        if season_name is None and day.get("season"):
            season_name = day["season"]
        graded_groups = []
        listed = []
        for group in day.get("groups") or []:
            pick = group.get("pick") or {}
            row = {
                "id": group.get("id"),
                "pick": pick.get("name"),
                "pid": (pick.get("pids") or [None])[0],
                "pids": pick.get("pids") or [],
                "team": pick.get("team"),
                "opp": pick.get("opp"),
                "home": pick.get("home"),
                "probability": pick.get("probability"),
                "hit": group.get("hit"),
                "top3_hits": group.get("top3_hits"),
                "random": group.get("random"),
                "n": group.get("n"),
                "scorers": group.get("scorers"),
                "status": group.get("status"),
            }
            listed.append(row)
            if group.get("status") == "graded" and group.get("hit") is not None:
                graded_groups.append(group)
        day_picks = len(graded_groups)
        day_hits = sum(g["hit"] for g in graded_groups) if graded_groups else None
        day_top3 = sum(g["top3_hits"] for g in graded_groups) if graded_groups else None
        day_slots = 0
        for group in graded_groups:
            day_slots += min(3, len(group.get("players") or []))
        randoms = [g["random"] for g in graded_groups if g.get("random") is not None]
        day_random = (sum(randoms) / float(len(randoms))) if randoms else None
        if graded_groups:
            running_hits += day_hits
            running_picks += day_picks
            running_top3 += day_top3
            running_top3_slots += day_slots
            running_random_sum += sum(randoms)
            running_random_n += len(randoms)
        # A day with nothing graded yet does not extend the running series.
        show_running = bool(graded_groups)
        point = {
            "date": day.get("date"),
            "status": day.get("status"),
            "picks": day_picks,
            "hits": _round(day_hits),
            "hit_rate": _round(day_hits / day_picks) if day_picks else None,
            "top3_hits": day_top3,
            "top3_slots": day_slots if graded_groups else None,
            "random": _round(day_random),
            "running_hits": _round(running_hits) if show_running else None,
            "running_picks": running_picks if show_running else None,
            "running_hit_rate": _round(running_hits / running_picks) if show_running else None,
            "running_top3_hits": running_top3 if show_running else None,
            "running_top3_slots": running_top3_slots if show_running else None,
            "running_top3_rate": (
                _round(running_top3 / float(running_top3_slots))
                if show_running and running_top3_slots else None
            ),
            "running_random": (
                _round(running_random_sum / float(running_random_n))
                if show_running and running_random_n else None
            ),
            "groups": listed,
        }
        out_days.append(point)
    summary = {
        "days": sum(1 for d in out_days if d["picks"]),
        "picks": running_picks,
        "hits": _round(running_hits),
        "hit_rate": _round(running_hits / running_picks) if running_picks else None,
        "top3_hits": running_top3,
        "top3_slots": running_top3_slots,
        "top3_rate": (
            _round(running_top3 / float(running_top3_slots)) if running_top3_slots else None
        ),
        "random_baseline": (
            _round(running_random_sum / float(running_random_n)) if running_random_n else None
        ),
    }
    return {
        "schema": 1,
        "season": season_name,
        "method": "model",
        "methods": [{"id": "model", "label": "Model"}],
        "summary": summary,
        "days": out_days,
    }


def build_index(days, today):
    rows = []
    for day in days:
        hits = 0.0
        picks = 0
        for group in day.get("groups") or []:
            if group.get("status") == "graded" and group.get("hit") is not None:
                hits += group["hit"]
                picks += 1
        rows.append({
            "date": day.get("date"),
            "status": day.get("status"),
            "groups": len(day.get("groups") or []),
            "picks": picks,
            "hits": round(hits, 4) if picks else None,
        })
    rows.sort(key=lambda row: row["date"] or "", reverse=True)
    updated = None
    for day in days:
        stamp = day.get("graded_at") or day.get("generated_at")
        if stamp and (updated is None or stamp > updated):
            updated = stamp
    return {
        "schema": 1,
        "updated": updated,
        "today": today,
        "season": (days[-1].get("season") if days else None),
        "days": rows,
    }


def rebuild(publish_dir):
    days = list_days(publish_dir)
    today = None
    today_path = os.path.join(publish_dir, "today.json")
    if os.path.exists(today_path):
        with open(today_path) as handle:
            today = json.load(handle).get("date")
    if today is None and days:
        today = days[-1].get("date")
    season = build_season(days)
    index = build_index(days, today)
    _atomic_write(os.path.join(publish_dir, "season.json"), season)
    _atomic_write(os.path.join(publish_dir, "days", "index.json"), index)
    return season, index
