"""Injury badges and games missed, beside the frozen probabilities.

Designations come from ESPN's public NHL injury report. No account and no
key. The NHL web API does not publish a league injury list. This module
does not read another site's picks or ratings.

A failed feed does not fail the job. A report cached earlier the same
Toronto day is reused. Otherwise players keep whatever designation was
already stored, and new players get none.

Games missed come from the local box-score archive: how many of this
team's games were played after the player's last game and before the
slate. The badge threshold is three. The count is stored either way.
"""
import datetime as dt
import glob
import json
import os
import re

ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
CACHE_NAME = "injury_report.json"
RETURNING_MIN = 3

# ESPN abbreviations that are not the NHL scoreboard form.
_TEAM_ALIAS = {"LA": "LAK", "NJ": "NJD", "TB": "TBL", "SJ": "SJS"}
_BANNED_TEXT = ("datadrivenhockey", "hockeychallengehelper")
_BANNED_WORDS = ("ddh", "hch")
_WORD = re.compile(r"[a-z0-9]+")
_SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def normalize_name(name):
    text = (name or "").lower().replace("'", "").replace(".", " ")
    text = text.replace("-", " ")
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch.isspace():
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    parts = [part for part in "".join(cleaned).split() if part not in _SUFFIXES]
    return " ".join(parts)


def team_abbrev(value):
    text = (value or "").strip().upper()
    return _TEAM_ALIAS.get(text, text)


def badge_code(status, fantasy, type_abbr):
    """Short tile label, or None when this row is not a designation."""
    kind = " ".join((status or "").lower().replace("-", " ").split())
    mark = (fantasy or "").upper().replace(" ", "")
    code = (type_abbr or "").upper()
    if mark in ("IR-LT", "LTIR") or "long term" in kind or "ltir" in kind:
        return "LTIR"
    if "game time decision" in kind or mark == "GTD" or code == "GTD":
        return "GTD"
    if kind in ("questionable",) or mark == "Q":
        return "Q"
    if kind in ("out",) or mark == "OUT" or code == "O":
        return "OUT"
    if "day to day" in kind or mark in ("DD", "DTD") or code == "DD":
        return "DTD"
    if kind in ("doubtful",):
        return "DOUBT"
    if kind in ("injured reserve", "ir") or mark in ("IR", "IR-NR") or code == "IR":
        return "IR"
    return None


def _clean_detail(text, fallback):
    raw = " ".join((text or "").split())
    low = raw.lower()
    words = set(_WORD.findall(low))
    if any(banned in low for banned in _BANNED_TEXT) or any(word in words for word in _BANNED_WORDS):
        raw = " ".join((fallback or "").split())
    if len(raw) > 240:
        raw = raw[:237].rstrip() + "..."
    return raw


def _date_only(value):
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def parse_report(payload):
    """Normalized rows from an ESPN injury document. None if it is not one."""
    if not isinstance(payload, dict) or "injuries" not in payload:
        return None
    teams = payload.get("injuries")
    if not isinstance(teams, list):
        return None
    rows = []
    for team in teams:
        if not isinstance(team, dict):
            continue
        for item in team.get("injuries") or []:
            if not isinstance(item, dict):
                continue
            athlete = item.get("athlete") or {}
            club = athlete.get("team") or {}
            abbrev = team_abbrev(club.get("abbreviation"))
            name = athlete.get("displayName") or ""
            details = item.get("details") or {}
            fantasy = (details.get("fantasyStatus") or {}).get("abbreviation")
            kind = item.get("type") or {}
            status = badge_code(item.get("status"), fantasy, kind.get("abbreviation"))
            if not status or not name:
                continue
            body = details.get("type") or ""
            detail = _clean_detail(item.get("shortComment") or body, body)
            rows.append({
                "name": name,
                "team": abbrev,
                "status": status,
                "detail": detail,
                "updated": _date_only(item.get("date")),
            })
    return rows


def _cache_path(raw_dir):
    return os.path.join(raw_dir, CACHE_NAME)


def _save_cache(raw_dir, today, rows):
    if not raw_dir:
        return
    os.makedirs(raw_dir, exist_ok=True)
    path = _cache_path(raw_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({"date": today, "rows": rows}, handle)
        handle.write("\n")
    os.replace(tmp, path)


def _load_cache(raw_dir):
    path = _cache_path(raw_dir) if raw_dir else ""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def load_report(getter, raw_dir, today, log):
    """Today's designations. None when the feed and the same-day cache miss."""
    payload = None
    try:
        payload = getter(ESPN_INJURIES)
    except Exception as exc:
        log("injury feed failed: %s" % exc)
    rows = parse_report(payload) if payload is not None else None
    if rows is not None:
        try:
            _save_cache(raw_dir, today, rows)
        except OSError as exc:
            log("injury cache not written: %s" % exc)
        return rows
    cached = _load_cache(raw_dir)
    if cached and cached.get("date") == today and isinstance(cached.get("rows"), list):
        log("injury feed failed; using the cache from %s" % today)
        return cached["rows"]
    log("injury feed failed; no injury badges")
    return None


def _index(rows):
    by_team = {}
    by_name = {}
    for row in rows or []:
        name = normalize_name(row.get("name"))
        team = team_abbrev(row.get("team"))
        if not name:
            continue
        if team:
            by_team[(team, name)] = row
        by_name.setdefault(name, []).append(row)
    return by_team, by_name


def match_player(player, rows):
    by_team, by_name = rows if isinstance(rows, tuple) else _index(rows)
    name = normalize_name(player.get("name"))
    team = team_abbrev(player.get("team"))
    if team and (team, name) in by_team:
        return by_team[(team, name)]
    hits = by_name.get(name) or []
    if len(hits) == 1:
        return hits[0]
    return None


def _public_injury(row):
    injury = {
        "status": row["status"],
        "detail": row.get("detail") or "",
        "updated": row.get("updated"),
        "source": "espn",
    }
    if not injury["updated"]:
        injury["updated"] = None
    return injury


def apply_injuries(day, rows):
    """Set or clear ``injury`` from a successful report. Does not touch picks."""
    if rows is None:
        return 0
    index = _index(rows)
    count = 0
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            hit = match_player(player, index)
            if hit:
                player["injury"] = _public_injury(hit)
                count += 1
            elif "injury" in player:
                del player["injury"]
    return count


def _history(raw_dir):
    """pid -> set of game dates, and team -> set of game dates. Skips bad lines."""
    played = {}
    teams = {}
    if not raw_dir or not os.path.isdir(raw_dir):
        return played, teams
    for path in sorted(glob.glob(os.path.join(raw_dir, "box_*.jsonl"))):
        try:
            handle = open(path)
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    game = json.loads(line)
                except ValueError:
                    continue
                date = _date_only(game.get("date"))
                if not date:
                    continue
                for side in ("home", "away"):
                    club = game.get(side)
                    if club:
                        teams.setdefault(club, set()).add(date)
                for bucket in ("sk", "gk"):
                    for row in game.get(bucket) or []:
                        if not isinstance(row, list) or len(row) < 2:
                            continue
                        try:
                            pid = int(row[0])
                        except (TypeError, ValueError):
                            continue
                        played.setdefault(pid, set()).add(date)
    return played, teams


def absence_for(pid, team, slate, played, teams):
    """Games this team played after the player's last game and before the slate.

    Later games in the archive do not count. A backfill of an old day uses
    only games from before that morning.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    club = team_abbrev(team)
    dates = [date for date in played.get(pid, ()) if date < slate]
    if not dates or not club or club not in teams:
        return None
    last = max(dates)
    missed = 0
    for date in teams[club]:
        if last < date < slate:
            missed += 1
    return {"missed_team_games": missed, "last_played": last}


def apply_absence(day, raw_dir):
    """Fill ``absence`` from box scores. Leaves the day alone when none exist."""
    slate = _date_only(day.get("date"))
    if not slate:
        return 0
    played, teams = _history(raw_dir)
    if not teams:
        return 0
    count = 0
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            row = absence_for(player.get("pid"), player.get("team"), slate, played, teams)
            if row is None:
                continue
            player["absence"] = row
            count += 1
    return count


def annotate(day, getter, raw_dir, today, log, designations):
    """Add badges for one day. Probabilities, picks, and grades are not inputs."""
    if designations:
        rows = load_report(getter, raw_dir, today, log)
        if rows is not None:
            count = apply_injuries(day, rows)
            log("injuries %s: %d" % (day.get("date"), count))
    try:
        missed = apply_absence(day, raw_dir)
    except Exception as exc:
        log("absence skipped %s: %s" % (day.get("date"), exc))
        return
    if missed:
        log("absence %s: %d" % (day.get("date"), missed))


def backfill_absence(publish_dir, raw_dir, log):
    """Add games-missed to published days. Does not invent injury designations.

    Reads ``today.json`` and ``days/YYYY-MM-DD.json`` only. ``seasons/`` is
    not opened. A second run writes the same counts. Picks and grades that
    change are not written.
    """
    from job.publish import _atomic_write
    from job.snapshots import publish_start_paths, record_fingerprint

    played, teams = _history(raw_dir)
    if not teams:
        log("absence not recorded: no box scores in %s" % raw_dir)
        return 1
    updated = 0
    failed = 0
    for path in publish_start_paths(publish_dir):
        try:
            with open(path) as handle:
                doc = json.load(handle)
        except (OSError, ValueError) as exc:
            log("absence skipped %s: %s" % (os.path.basename(path), exc))
            failed += 1
            continue
        before = record_fingerprint(doc)
        slate = _date_only(doc.get("date"))
        count = 0
        if slate:
            for group in doc.get("groups") or []:
                for player in group.get("players") or []:
                    row = absence_for(player.get("pid"), player.get("team"), slate, played, teams)
                    if row is None:
                        continue
                    player["absence"] = row
                    count += 1
        if record_fingerprint(doc) != before:
            log("absence refused %s: records changed" % os.path.basename(path))
            failed += 1
            continue
        if not count:
            log("absence unchanged %s" % os.path.basename(path))
            continue
        _atomic_write(path, doc)
        updated += 1
        log("absence %s %s players=%d" % (slate, os.path.basename(path), count))
    log("absence updated %d, failed %d" % (updated, failed))
    return failed
