"""Intra-day Tims list snapshots.

The first scored lists of a day are the morning picks. Later checks compare
the available players. When that set changes, the day stores a snapshot
``{time, added, removed}`` and the current lists, and the new score replaces
the current picks. Players who drop off stay on the group, marked unavailable,
with the first and last time they were on a list.

Grading of the published result uses the current picks. Morning picks are
graded only into ``day["morning"]``, which the season totals do not read.
A day that is already graded is not passed back through here.
"""
import copy
import datetime as dt


def _available(player):
    return isinstance(player, dict) and player.get("available", True) is not False


def _pid(player):
    if player.get("pid") is not None:
        return int(player["pid"])
    return int(player["nhlPlayerId"])


def stamp_toronto(now=None):
    """ISO time in America/Toronto. ``now`` is a datetime, for tests.

    A naive value is the server clock, not already Toronto. Bluehost stays
    on MST, so the zone is converted rather than relabeled.
    """
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("America/Toronto")
    except Exception:
        zone = None
    if now is None or now.tzinfo is None:
        now = (now or dt.datetime.now()).astimezone()
    if zone is not None:
        now = now.astimezone(zone)
    return now.isoformat(timespec="seconds")


def _membership(day):
    found = {}
    for group in (day or {}).get("groups") or []:
        pids = []
        for player in group.get("players") or []:
            if _available(player):
                pids.append(_pid(player))
        pids.sort()
        found[group.get("id")] = pids
    return found


def same_lists(previous, current):
    """True when each group has the same available player ids."""
    if not previous or not current:
        return False
    return _membership(previous) == _membership(current)


def _entry(group_id, player):
    return {
        "group": group_id,
        "pid": _pid(player),
        "name": player.get("name") or player.get("fullName") or "",
    }


def diff_rosters(previous, current):
    """Players added or removed since ``previous``, by group and player id."""
    old = {}
    new = {}
    for day, dest in ((previous, old), (current, new)):
        for group in (day or {}).get("groups") or []:
            gid = group.get("id")
            bucket = {}
            for player in group.get("players") or []:
                if _available(player):
                    bucket[_pid(player)] = player
            dest[gid] = bucket
    added = []
    removed = []
    keys = set(old) | set(new)
    for gid in sorted(keys, key=lambda value: (value is None, value)):
        old_ids = set((old.get(gid) or {}))
        new_ids = set((new.get(gid) or {}))
        for pid in sorted(new_ids - old_ids):
            added.append(_entry(gid, new[gid][pid]))
        for pid in sorted(old_ids - new_ids):
            removed.append(_entry(gid, old[gid][pid]))
    added.sort(key=lambda item: (item["group"] is None, str(item["group"]), item["name"], item["pid"]))
    removed.sort(key=lambda item: (item["group"] is None, str(item["group"]), item["name"], item["pid"]))
    return added, removed


def _copy_block(block):
    if not block:
        return None
    copied = {
        "pids": list(block.get("pids") or []),
        "name": block.get("name"),
        "team": block.get("team"),
        "opp": block.get("opp"),
        "home": block.get("home"),
        "probability": block.get("probability"),
        "top3": list(block.get("top3") or []),
        "hit": None,
        "top3_hits": None,
    }
    if "rank" in block:
        copied["rank"] = block.get("rank")
    if "goals_per_game" in block:
        copied["goals_per_game"] = block.get("goals_per_game")
    return copied


def _slim_player(player):
    return {
        "pid": _pid(player),
        "name": player.get("name") or "",
        "team": player.get("team"),
        "opp": player.get("opp"),
        "home": player.get("home"),
    }


def morning_from(day, when):
    """Copy the picks on ``day`` into the morning reference block."""
    groups = []
    for group in day.get("groups") or []:
        available = [player for player in (group.get("players") or []) if _available(player)]
        methods = {}
        for method_id, block in (group.get("method_picks") or {}).items():
            methods[method_id] = _copy_block(block)
        groups.append({
            "id": group.get("id"),
            "pick": _copy_block(group.get("pick")),
            "method_picks": methods,
            "top3": [_pid(player) for player in available[:3]],
            "players": [_slim_player(player) for player in available],
            "hit": None,
            "top3_hits": None,
            "status": "pending",
        })
    return {
        "at": when,
        "label": "Morning picks",
        "note": "Reference only. Season results use the current pick.",
        "groups": groups,
    }


def _write_lists(day, when):
    groups = []
    for group in day.get("groups") or []:
        rows = []
        for player in group.get("players") or []:
            if not _available(player):
                continue
            rows.append({"pid": _pid(player), "name": player.get("name") or ""})
        groups.append({"id": group.get("id"), "players": rows})
    day["lists"] = {"at": when, "groups": groups}
    day["current_at"] = when


def _touch_players(group, when):
    for player in group.get("players") or []:
        if not _available(player):
            continue
        if not player.get("first_seen"):
            player["first_seen"] = when
        player["last_seen"] = when
    return group


def _pids(group):
    found = []
    for player in (group or {}).get("players") or []:
        if _available(player):
            found.append(_pid(player))
    found.sort()
    return found


def open_slate(day, when):
    """First publish: these lists are both the morning picks and the current ones."""
    day["generated_at"] = when
    day["snapshots"] = []
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            player["available"] = True
            player["first_seen"] = when
            player["last_seen"] = when
            if "removed_at" in player:
                del player["removed_at"]
    day["morning"] = morning_from(day, when)
    _write_lists(day, when)
    return day


def note_seen(existing, when):
    """Lists matched. Remember that the current players were still available."""
    day = copy.deepcopy(existing)
    if not isinstance(day.get("morning"), dict):
        day["morning"] = morning_from(day, day.get("generated_at") or when)
    for group in day.get("groups") or []:
        _touch_players(group, when)
    day.setdefault("snapshots", [])
    _write_lists(day, when)
    return day


def _drop_group(previous, when):
    group = copy.deepcopy(previous)
    for player in group.get("players") or []:
        if _available(player):
            player["available"] = False
            player["removed_at"] = when
        player["pick"] = False
    group["status"] = "pending"
    group["pick"] = None
    group["method_picks"] = {}
    group["hit"] = None
    group["top3_hits"] = None
    group["random"] = None
    group["n"] = None
    group["scorers"] = None
    return group


def _rebuild_group(previous, fresh, when):
    history = {}
    if previous:
        for player in previous.get("players") or []:
            history[_pid(player)] = player
    players = []
    seen = set()
    for player in fresh.get("players") or []:
        pid = _pid(player)
        if pid in seen:
            continue
        seen.add(pid)
        row = copy.deepcopy(player)
        prior = history.get(pid)
        row["available"] = True
        row["first_seen"] = (prior or {}).get("first_seen") or when
        row["last_seen"] = when
        if "removed_at" in row:
            del row["removed_at"]
        players.append(row)
    if previous:
        for player in previous.get("players") or []:
            pid = _pid(player)
            if pid in seen:
                continue
            seen.add(pid)
            row = copy.deepcopy(player)
            if _available(row):
                row["available"] = False
                row["removed_at"] = when
            row["pick"] = False
            players.append(row)
    return {
        "id": fresh.get("id"),
        "status": "pending",
        "players": players,
        "pick": copy.deepcopy(fresh.get("pick")),
        "hit": None,
        "top3_hits": None,
        "random": None,
        "n": None,
        "scorers": None,
        "method_picks": copy.deepcopy(fresh.get("method_picks") or {}),
    }


def merge_lists(existing, scored, when, frozen_ids=None, force=False):
    """Apply ``scored`` onto ``existing``.

    Groups in ``frozen_ids`` were already graded before this run and stay
    as stored. Other groups keep their players when the available ids match,
    unless ``force`` is set. A membership change appends one snapshot and
    rescores that group from ``scored`` (current picks only).
    """
    frozen_ids = set(frozen_ids or [])
    added, removed = diff_rosters(existing, scored)
    day = copy.deepcopy(existing)
    if not isinstance(day.get("morning"), dict):
        day["morning"] = morning_from(day, day.get("generated_at") or when)
    old_groups = {}
    for group in day.get("groups") or []:
        old_groups[group.get("id")] = group
    new_groups = {}
    for group in scored.get("groups") or []:
        new_groups[group.get("id")] = group
    order = []
    for group in list(day.get("groups") or []) + list(scored.get("groups") or []):
        gid = group.get("id")
        if gid not in order:
            order.append(gid)
    merged = []
    for gid in order:
        previous = old_groups.get(gid)
        fresh = new_groups.get(gid)
        if gid in frozen_ids and previous is not None:
            merged.append(previous)
            continue
        if fresh is None:
            if previous is not None:
                merged.append(_drop_group(previous, when))
            continue
        if previous is not None and _pids(previous) == _pids(fresh) and not force:
            _touch_players(previous, when)
            merged.append(previous)
            continue
        merged.append(_rebuild_group(previous, fresh, when))
    day["groups"] = merged
    if "skipped" in scored:
        day["skipped"] = list(scored.get("skipped") or [])
    if scored.get("methods"):
        day["methods"] = scored["methods"]
    if added or removed:
        snaps = list(day.get("snapshots") or [])
        snaps.append({"time": when, "added": added, "removed": removed})
        day["snapshots"] = snaps
    else:
        day.setdefault("snapshots", [])
    _write_lists(day, when)
    return day


def grade_morning(day, final, goals):
    """Fill morning hit fields from the goal map. Does not read or write group hits."""
    morning = day.get("morning")
    if not isinstance(morning, dict):
        return day
    for block in morning.get("groups") or []:
        players = block.get("players") or []
        teams = []
        for player in players:
            team = player.get("team")
            if team and team not in teams:
                teams.append(team)
        ready = bool(teams) and all(final.get(team) is True for team in teams)
        methods = block.get("method_picks") or {}
        if not ready:
            block["status"] = "pending"
            block["hit"] = None
            block["top3_hits"] = None
            for method in methods.values():
                if isinstance(method, dict):
                    method["hit"] = None
                    method["top3_hits"] = None
            continue
        scored = {}
        for player in players:
            pid = int(player["pid"])
            count = int(goals.get(pid, 0))
            player["goals"] = count
            player["scored"] = 1 if count else 0
            scored[pid] = player["scored"]
        pids = [int(pid) for pid in ((block.get("pick") or {}).get("pids") or [])]
        if pids:
            block["hit"] = round(
                sum(scored.get(pid, 0) for pid in pids) / float(len(pids)), 4
            )
        else:
            block["hit"] = None
        top = [int(pid) for pid in (block.get("top3") or [])]
        block["top3_hits"] = int(sum(scored.get(pid, 0) for pid in top)) if top else 0
        block["status"] = "graded"
        for method in methods.values():
            if not isinstance(method, dict):
                continue
            mpids = [int(pid) for pid in (method.get("pids") or [])]
            if mpids:
                method["hit"] = round(
                    sum(scored.get(pid, 0) for pid in mpids) / float(len(mpids)), 4
                )
            else:
                method["hit"] = None
            mtop = [int(pid) for pid in (method.get("top3") or [])]
            method["top3_hits"] = int(sum(scored.get(pid, 0) for pid in mtop)) if mtop else 0
    return day
