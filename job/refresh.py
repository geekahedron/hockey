"""Incremental NHL refresh into model/raw (or another raw directory).

Uses fetch_boxscores.compact / fetch_boxscores.get and fetch_pptoi.window.
Finished regular-season games dated strictly before ``before`` are appended.
Feature rows are rebuilt from those files later by features.load(); this
module does not compute features and does not change that math.

Prior seasons are backfilled once when their box file is missing, then
marked complete so the daily run does not walk an empty summer. The
current season is always scanned from the last stored game through
``before``.
"""
import datetime as dt
import json
import os
import sys

_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model")
if _MODEL not in sys.path:
    sys.path.insert(0, _MODEL)


class RefreshError(Exception):
    pass


def season_year(when):
    """NHL season start year. July and earlier belong to the previous season."""
    when = _as_date(when)
    return when.year if when.month >= 8 else when.year - 1


def season_years(when):
    year = season_year(when)
    return [year - 2, year - 1, year]


def _as_date(when):
    if isinstance(when, dt.datetime):
        return when.date()
    if isinstance(when, dt.date):
        return when
    return dt.date.fromisoformat(str(when)[:10])


def _season_start(year):
    return dt.date(year, 9, 20)


def _season_end(year):
    """Day after the last regular-season date we are willing to request."""
    return dt.date(year + 1, 6, 20)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        return json.load(handle)


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(obj, handle)
        handle.write("\n")
    os.replace(tmp, path)


def _last_game_date(path):
    last = None
    ids = set()
    if not os.path.exists(path):
        return None, ids
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            game = json.loads(line)
            ids.add(game["id"])
            stamp = game.get("date")
            if stamp and (last is None or stamp > last):
                last = stamp
    return (dt.date.fromisoformat(last) if last else None), ids


def _default_get(url):
    import fetch_boxscores
    return fetch_boxscores.get(url)


def _default_window(args):
    import fetch_pptoi
    return fetch_pptoi.window(args)


def refresh(before, raw_dir, get_json=None, toi_window=None, seasons=None, log=None):
    """Append finished games with date < ``before``. Returns the number of new games.

    ``get_json(url)`` returns a decoded object, or None when the request failed.
    ``toi_window((year, start_iso, end_iso))`` returns the pptoi map.
    """
    import fetch_boxscores

    before = _as_date(before)
    get_json = get_json or _default_get
    toi_window = toi_window or _default_window
    log = log or (lambda msg: None)
    years = list(seasons) if seasons is not None else season_years(before)
    os.makedirs(raw_dir, exist_ok=True)
    added = 0
    for year in years:
        added += _refresh_season(
            year, before, raw_dir, get_json, toi_window, fetch_boxscores.compact, log
        )
    return added


def _refresh_season(year, before, raw_dir, get_json, toi_window, compact, log):
    box_path = os.path.join(raw_dir, "box_%d.jsonl" % year)
    scan_path = os.path.join(raw_dir, "scan_%d.json" % year)
    state = _read_json(scan_path, {})
    current = season_year(before) == year
    if state.get("complete") and not current:
        log("refresh %d: already complete" % year)
        return 0

    stop = min(before, _season_end(year))
    last, have = _last_game_date(box_path)
    if last is None:
        start = _season_start(year)
    else:
        start = last - dt.timedelta(days=1)
    if start < _season_start(year):
        start = _season_start(year)
    if start >= stop:
        if not current and stop >= _season_end(year):
            state["complete"] = True
            _atomic_json(scan_path, state)
        log("refresh %d: nothing to scan" % year)
        return 0

    new_lines = []
    day = start
    while day < stop:
        url = "https://api-web.nhle.com/v1/score/%s" % day.isoformat()
        payload = get_json(url)
        if payload is None:
            raise RefreshError("score feed failed for %s" % day.isoformat())
        for game in payload.get("games") or []:
            if game.get("gameType") not in (2, "2"):
                continue
            if game.get("gameState") not in ("OFF", "FINAL"):
                continue
            gid = game.get("id")
            if gid in have:
                continue
            box = get_json(
                "https://api-web.nhle.com/v1/gamecenter/%s/boxscore" % gid
            )
            if box is None:
                raise RefreshError("boxscore failed for game %s" % gid)
            compact_game = compact(box)
            if not compact_game:
                continue
            new_lines.append(json.dumps(compact_game) + "\n")
            have.add(compact_game["id"])
        day += dt.timedelta(days=1)

    if new_lines:
        with open(box_path, "a") as handle:
            for line in new_lines:
                handle.write(line)
    span_end = stop - dt.timedelta(days=1)
    if span_end >= start:
        toi_path = os.path.join(raw_dir, "toi_%d.json" % year)
        toi = _read_json(toi_path, {})
        fresh = toi_window((year, start.isoformat(), span_end.isoformat())) or {}
        toi.update(fresh)
        _atomic_json(toi_path, toi)
    if not current and stop >= _season_end(year):
        state["complete"] = True
        _atomic_json(scan_path, state)
    log("refresh %d: +%d games" % (year, len(new_lines)))
    return len(new_lines)
