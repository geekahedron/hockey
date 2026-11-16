"""Intra-day Tims list snapshots.

The first scored lists of a day are the morning picks. Later checks compare
the available players. When that set changes, the day stores a snapshot
``{time, added, removed, started}`` and the current lists. Anyone missing
from a check is off the list. A player is also off the list once their
team's NHL start time has passed, even if Tims still lists them. Neither
can be picked. The graded pick is whoever the list said at the moment that
player's game started. A scratch before that start moves the pick to whoever
is still available. If every candidate was scratched before a game, the
group has no graded pick.

Grading of the published result uses the current picks. Morning picks are
graded only into ``day["morning"]``, which the season totals do not read.
A day that is already graded is not passed back through here.
"""
import copy
import datetime as dt
import json
import os


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


def _as_dt(value):
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


# Tims drops a player when the puck drops. A postponed game has not started,
# even if the original start time is already in the past.
_POSTPONED = {"PPD", "POSTPONED", "CNCL", "CANCELLED", "CANCELED", "SUSP", "SUSPENDED"}
_UNDER_WAY = {"LIVE", "CRIT", "OVER", "FINAL", "OFF"}


def game_board(payload):
    """Map team abbrev to start time, schedule state, and game state.

    ``payload`` is an NHL ``/v1/score/DATE`` document, the same one the
    runner already fetched for home/away and grading.
    """
    board = {}
    if not isinstance(payload, dict):
        return board
    for game in payload.get("games") or []:
        if game.get("gameType") not in (None, 2, "2"):
            continue
        state = str(game.get("gameState") or "").upper()
        schedule = str(game.get("gameScheduleState") or "").upper()
        info = {
            "start": _as_dt(game.get("startTimeUTC") or game.get("startTime")),
            "postponed": schedule in _POSTPONED or state in _POSTPONED,
            "state": state,
        }
        for side in ("homeTeam", "awayTeam"):
            abbrev = (game.get(side) or {}).get("abbrev")
            if abbrev:
                board[abbrev] = info
    return board


def game_has_started(team, when, board):
    """True when ``team``'s game is under way, or the clock is at or past the start.

    A missing game, a postponed game, or a start still in the future is not
    started. A disappearance then counts as a removal.
    """
    info = (board or {}).get(team)
    if not info or info.get("postponed"):
        return False
    if info.get("state") in _UNDER_WAY:
        return True
    start = info.get("start")
    moment = _as_dt(when)
    if start is None or moment is None:
        return False
    return moment >= start


def _buckets(day):
    found = {}
    for group in (day or {}).get("groups") or []:
        bucket = {}
        for player in group.get("players") or []:
            if _available(player):
                bucket[_pid(player)] = player
        found[group.get("id")] = bucket
    return found


def _by_sort(items):
    items.sort(key=lambda item: (item["group"] is None, str(item["group"]), item["name"], item["pid"]))
    return items


def classify_changes(previous, current, when, board):
    """Split a Tims diff into adds, real removals, and game-start drops.

    A player who was already marked ``game_started`` is not listed again.
    """
    old = _buckets(previous)
    new = _buckets(current)
    added = []
    removed = []
    started = []
    keys = set(list(old) + list(new))
    for gid in sorted(keys, key=lambda value: (value is None, value)):
        old_ids = set(old.get(gid) or {})
        new_ids = set(new.get(gid) or {})
        for pid in sorted(new_ids - old_ids):
            added.append(_entry(gid, new[gid][pid]))
        for pid in sorted(old_ids - new_ids):
            player = old[gid][pid]
            if player.get("game_started"):
                continue
            if game_has_started(player.get("team"), when, board):
                started.append(_entry(gid, player))
            else:
                removed.append(_entry(gid, player))
    return _by_sort(added), _by_sort(removed), _by_sort(started)


def diff_rosters(previous, current, when=None, board=None):
    """Players added or removed since ``previous``, by group and player id.

    Game-start drops are not removals. Pass ``when`` and ``board`` to tell
    those apart; without them every disappearance is a removal.
    """
    added, removed, _started = classify_changes(previous, current, when, board or {})
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
    if block.get("start"):
        copied["start"] = block["start"]
    return copied


def _slim_player(player):
    row = {
        "pid": _pid(player),
        "name": player.get("name") or "",
        "team": player.get("team"),
        "opp": player.get("opp"),
        "home": player.get("home"),
    }
    if player.get("start"):
        row["start"] = player["start"]
    return row


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
            row = {"pid": _pid(player), "name": player.get("name") or "", "team": player.get("team")}
            if player.get("start"):
                row["start"] = player["start"]
            rows.append(row)
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


def open_slate(day, when, schedule=None):
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
    apply_timeline(day, when, schedule)
    return day


def note_seen(existing, when, schedule=None):
    """Lists matched. Game starts since the last check still take players off."""
    day = copy.deepcopy(existing)
    if not isinstance(day.get("morning"), dict):
        day["morning"] = morning_from(day, day.get("generated_at") or when)
    for group in day.get("groups") or []:
        _touch_players(group, when)
    day.setdefault("snapshots", [])
    apply_timeline(day, when, schedule)
    return day


def _model_prob(player):
    value = (player.get("probability") or {}).get("model")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _retie(players):
    """Set the model pick from players still eligible. Returns the pick block."""
    eligible = [player for player in players if _available(player)]
    for player in players:
        if not _available(player):
            player["pick"] = False
    ranked = [player for player in eligible if _model_prob(player) is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda player: (-_model_prob(player), player.get("name") or "", _pid(player)))
    best = _model_prob(ranked[0])
    tied = [player for player in ranked if _model_prob(player) == best]
    tied_ids = set(_pid(player) for player in tied)
    for player in eligible:
        player["pick"] = _pid(player) in tied_ids
    eligible.sort(key=lambda player: (
        _model_prob(player) is None,
        -(_model_prob(player) if _model_prob(player) is not None else 0),
        player.get("name") or "",
        _pid(player),
    ))
    players[:] = eligible + [player for player in players if not _available(player)]
    return {
        "pids": [_pid(player) for player in tied],
        "name": " / ".join(player.get("name") or "" for player in tied),
        "team": tied[0].get("team"),
        "opp": tied[0].get("opp"),
        "home": tied[0].get("home"),
        "probability": best,
    }


def _rerank_goals(players):
    """Re-rank eligible players by the goals-per-game already stored on them.

    Skipped unless every eligible player has that figure, so a partial set
    cannot invent a new order.
    """
    eligible = [player for player in players if _available(player)]
    for player in eligible:
        value = (player.get("style") or {}).get("goals_per_game")
        if not isinstance(value, (int, float)):
            return
    eligible.sort(key=lambda player: (
        -player["style"]["goals_per_game"], _pid(player)
    ))
    for place, player in enumerate(eligible, 1):
        player.setdefault("rank", {})
        player["rank"]["hch_style"] = place


def _mark_off_list(player, when, board, because_game):
    """A player who cannot be picked. ``because_game`` is not a separate eligibility."""
    player["available"] = False
    player["pick"] = False
    if not player.get("removed_at"):
        player["removed_at"] = when
    info = (board or {}).get(player.get("team")) or {}
    start = info.get("start")
    if start is not None and not info.get("postponed") and not player.get("start"):
        player["start"] = start.isoformat()
    if because_game:
        player["game_started"] = True
        player["unavailable_reason"] = "game_started"
        if player.get("start"):
            player["game_started_at"] = player["start"]
        elif not player.get("game_started_at"):
            player["game_started_at"] = when
    else:
        player["game_started"] = False
        player["unavailable_reason"] = "removed"


def _touch_listed(group, fresh_ids, when):
    for player in group.get("players") or []:
        if not _available(player) or _pid(player) not in fresh_ids:
            continue
        if not player.get("first_seen"):
            player["first_seen"] = when
        player["last_seen"] = when
        if player.get("game_started"):
            player["game_started"] = False
            if "game_started_at" in player:
                del player["game_started_at"]
    return group


def _mark_started(group, started_ids, when, board):
    for player in group.get("players") or []:
        if _pid(player) not in started_ids:
            continue
        _mark_off_list(player, when, board, True)
    return group


def _rebuild_group(previous, fresh, when, board):
    """New Tims list, plus locked game-start players, minus real scratches.

    The pick is computed again from whoever is still eligible. Game-start
    players keep the probabilities stored on the previous row.
    """
    history = {}
    if previous:
        for player in previous.get("players") or []:
            history[_pid(player)] = player
    players = []
    seen = set()
    for player in (fresh or {}).get("players") or []:
        pid = _pid(player)
        if pid in seen:
            continue
        seen.add(pid)
        row = copy.deepcopy(player)
        prior = history.get(pid)
        row["available"] = True
        row["game_started"] = False
        row["first_seen"] = (prior or {}).get("first_seen") or when
        row["last_seen"] = when
        if "removed_at" in row:
            del row["removed_at"]
        if "game_started_at" in row:
            del row["game_started_at"]
        players.append(row)
    if previous:
        for player in previous.get("players") or []:
            pid = _pid(player)
            if pid in seen:
                continue
            seen.add(pid)
            row = copy.deepcopy(player)
            if not _available(player):
                row["pick"] = False
                players.append(row)
                continue
            if player.get("game_started") or game_has_started(player.get("team"), when, board):
                _mark_off_list(row, when, board, True)
                players.append(row)
                continue
            _mark_off_list(row, when, board, False)
            players.append(row)
    group = {
        "id": (fresh or previous or {}).get("id"),
        "status": "pending",
        "players": players,
        "pick": None,
        "hit": None,
        "top3_hits": None,
        "random": None,
        "n": None,
        "scorers": None,
        "method_picks": {},
    }
    group["pick"] = _retie(group["players"])
    _rerank_goals(group["players"])
    from job.clone_attach import set_method_picks
    set_method_picks(group)
    return group


def merge_lists(existing, scored, when, frozen_ids=None, force=False, schedule=None):
    """Apply ``scored`` onto ``existing``.

    Groups in ``frozen_ids`` were already graded before this run and stay
    as stored. A game-start drop does not change picks. A real add or
    removal does, and the new pick still includes players whose games have
    started. ``schedule`` is the NHL score document for this date.
    """
    frozen_ids = set(frozen_ids or [])
    board = game_board(schedule)
    added, removed, started = classify_changes(existing, scored, when, board)
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
        g_added, g_removed, g_started = classify_changes(
            {"groups": [previous]} if previous else None,
            {"groups": [fresh]} if fresh else None,
            when,
            board,
        )
        if previous is not None and not g_added and not g_removed and (g_started or not force):
            fresh_ids = set(_pid(player) for player in (fresh or {}).get("players") or [])
            _touch_listed(previous, fresh_ids, when)
            _mark_started(previous, set(item["pid"] for item in g_started), when, board)
            merged.append(previous)
            continue
        if previous is None and fresh is None:
            continue
        merged.append(_rebuild_group(previous, fresh or {"id": gid, "players": []}, when, board))
    day["groups"] = merged
    if "skipped" in scored:
        day["skipped"] = list(scored.get("skipped") or [])
    if scored.get("methods"):
        day["methods"] = scored["methods"]
    if added or removed or started:
        snaps = list(day.get("snapshots") or [])
        snaps.append({
            "time": when,
            "added": added,
            "removed": removed,
            "started": started,
        })
        day["snapshots"] = snaps
    else:
        day.setdefault("snapshots", [])
    apply_timeline(day, when, schedule)
    return day


def _stamp_starts(day, board):
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            info = (board or {}).get(player.get("team")) or {}
            start = info.get("start")
            if start is not None and not info.get("postponed") and not player.get("start"):
                player["start"] = start.isoformat()


def _on_list_at(player, moment, include_same_instant=False):
    """On the Tims list at ``moment``.

    A removal at exactly ``moment`` still counts when locking a game that
    starts then. It does not count for the pick after the check.
    """
    first = _as_dt(player.get("first_seen"))
    if first is not None and moment < first:
        return False
    left = _as_dt(player.get("removed_at"))
    if left is None:
        return True
    if include_same_instant:
        return moment <= left
    return moment < left


def _pickable_at(player, moment, at_whistle=False):
    """Eligible to be chosen at ``moment``.

    ``at_whistle`` includes a player whose game starts at that exact moment,
    which is the last instant they can still be the pick.
    """
    if moment is None or not _on_list_at(player, moment, include_same_instant=at_whistle):
        return False
    start = _as_dt(player.get("start"))
    if start is None:
        return True
    if at_whistle:
        return moment <= start
    return moment < start


def _method_value(player, method_id):
    if method_id == "hch_style":
        value = (player.get("rank") or {}).get("hch_style")
        if isinstance(value, int):
            return value
        return None
    field = "model" if method_id == "model" else method_id
    value = (player.get("probability") or {}).get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _order_method(players, method_id):
    ranked = []
    for player in players:
        if _method_value(player, method_id) is not None:
            ranked.append(player)
    if method_id == "hch_style":
        ranked.sort(key=lambda player: (_method_value(player, method_id), _pid(player)))
    else:
        ranked.sort(key=lambda player: (
            -_method_value(player, method_id), player.get("name") or "", _pid(player)
        ))
    return ranked


def _leaders(players, method_id):
    ranked = _order_method(players, method_id)
    if not ranked:
        return []
    best = _method_value(ranked[0], method_id)
    return [player for player in ranked if _method_value(player, method_id) == best]


def _pick_block(leaders, method_id, top, locked, locked_at):
    if not leaders:
        return {
            "pids": [],
            "name": None,
            "team": None,
            "opp": None,
            "home": None,
            "probability": None,
            "top3": [_pid(player) for player in top],
            "hit": None,
            "top3_hits": None,
            "locked": False,
            "locked_at": None,
            "top3_locked": False,
        }
    first = leaders[0]
    block = {
        "pids": [_pid(player) for player in leaders],
        "name": " / ".join(player.get("name") or "" for player in leaders),
        "team": first.get("team"),
        "opp": first.get("opp"),
        "home": first.get("home"),
        "probability": None if method_id == "hch_style" else _method_value(first, method_id),
        "top3": [_pid(player) for player in top],
        "hit": None,
        "top3_hits": None,
        "locked": bool(locked),
        "locked_at": locked_at,
        "top3_locked": bool(locked),
    }
    if first.get("start"):
        block["start"] = first["start"]
    if method_id == "hch_style":
        block["rank"] = _method_value(first, method_id)
        block["goals_per_game"] = (first.get("style") or {}).get("goals_per_game")
        block["probability"] = None
    return block


def _replay_method(players, method_id, starts, when):
    """Lock the pick and the top three at each player's game start.

    Until that start, the choice follows whoever is still available. A
    scratch before the start simply drops that player. After the lock,
    later list changes do not move it.
    """
    locked = None
    locked_at = None
    locked_top = []
    moment = _as_dt(when)
    for start in starts:
        if moment is not None and start > moment:
            break
        eligible = [player for player in players if _pickable_at(player, start, at_whistle=True)]
        leaders = _leaders(eligible, method_id)
        if locked is None and any(_as_dt(player.get("start")) == start for player in leaders):
            locked = leaders
            locked_at = start.isoformat()
        top = _order_method(eligible, method_id)[:3]
        for player in top:
            if _as_dt(player.get("start")) != start:
                continue
            pid = _pid(player)
            if pid in locked_top or len(locked_top) >= 3:
                continue
            locked_top.append(pid)
    if locked is not None:
        leaders = locked
        top_players = []
        by_pid = dict((_pid(player), player) for player in players)
        for pid in locked_top:
            if pid in by_pid:
                top_players.append(by_pid[pid])
        return _pick_block(leaders, method_id, top_players, True, locked_at), True
    eligible_now = [player for player in players if _pickable_at(player, moment, at_whistle=False)] if moment else list(players)
    leaders = _leaders(eligible_now, method_id)
    top = _order_method(eligible_now, method_id)[:3]
    return _pick_block(leaders, method_id, top, False, None), False


def _mark_availability(player, when):
    moment = _as_dt(when)
    start = _as_dt(player.get("start"))
    left = _as_dt(player.get("removed_at"))
    game = (
        start is not None and moment is not None and moment >= start
        and (left is None or start <= left)
    )
    scratch = left is not None and moment is not None and moment >= left and not game
    if game:
        player["available"] = False
        player["game_started"] = True
        player["unavailable_reason"] = "game_started"
        player["game_started_at"] = player.get("start")
    elif scratch:
        player["available"] = False
        player["game_started"] = False
        player["unavailable_reason"] = "removed"
    else:
        player["available"] = True
        player["game_started"] = False
        if "unavailable_reason" in player:
            player["unavailable_reason"] = None


def apply_timeline(day, when, schedule=None):
    """Drop players whose games have started and lock picks at those starts.

    Safe to run again. Players with no start time keep the ordinary current
    pick, which grading still records.
    """
    board = game_board(schedule)
    _stamp_starts(day, board)
    moment = _as_dt(when)
    for group in day.get("groups") or []:
        players = group.get("players") or []
        for player in players:
            _mark_availability(player, when)
        starts = []
        seen = set()
        for player in players:
            start = _as_dt(player.get("start"))
            if start is None or start in seen:
                continue
            seen.add(start)
            starts.append(start)
        starts.sort()
        methods = {}
        model_block = None
        model_locked = False
        for method_id in ("model", "ddh_style", "hch_style"):
            block, locked = _replay_method(players, method_id, starts, when)
            if method_id == "model":
                model_block = block
                model_locked = locked
            if block.get("pids") or (group.get("method_picks") or {}).get(method_id) or method_id == "model":
                methods[method_id] = block
        if model_block is not None:
            group["pick"] = {
                "pids": list(model_block.get("pids") or []),
                "name": model_block.get("name"),
                "team": model_block.get("team"),
                "opp": model_block.get("opp"),
                "home": model_block.get("home"),
                "probability": model_block.get("probability"),
                "locked": model_locked,
                "locked_at": model_block.get("locked_at"),
            }
            if model_block.get("start"):
                group["pick"]["start"] = model_block["start"]
            group["pick_locked"] = model_locked
            chosen = set(group["pick"]["pids"])
            for player in players:
                player["pick"] = _pid(player) in chosen
        group["method_picks"] = methods
        if moment is not None:
            group["availability_at"] = when
    _write_lists(day, when)
    propagate_starts(day, schedule)
    return day


def _iso_start(info):
    if not info or info.get("postponed"):
        return None
    start = info.get("start")
    if start is None:
        return None
    return start.isoformat()


def propagate_starts(day, schedule=None):
    """Write NHL start times onto the day. Does not change picks or grades.

    ``day["games"]`` maps a team abbreviation to that start. Players, picks,
    the morning block, and list rows get the same ``start`` string.
    """
    board = game_board(schedule)
    games = dict(day.get("games") or {})
    for team, info in board.items():
        iso = _iso_start(info)
        if iso:
            games[team] = iso
    day["games"] = games
    if board:
        _stamp_starts(day, board)

    def stamp(obj):
        if not isinstance(obj, dict) or obj.get("start"):
            return
        team = obj.get("team")
        if team and games.get(team):
            obj["start"] = games[team]

    by_pid = {}
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            stamp(player)
            by_pid[int(player["pid"])] = player
        for obj in [group.get("pick")] + list((group.get("method_picks") or {}).values()):
            stamp(obj)
            if isinstance(obj, dict) and not obj.get("start"):
                pids = obj.get("pids") or []
                if pids and int(pids[0]) in by_pid and by_pid[int(pids[0])].get("start"):
                    obj["start"] = by_pid[int(pids[0])]["start"]
    morning = day.get("morning") if isinstance(day.get("morning"), dict) else {}
    for group in morning.get("groups") or []:
        for player in group.get("players") or []:
            stamp(player)
        for obj in [group.get("pick")] + list((group.get("method_picks") or {}).values()):
            stamp(obj)
    for row in (day.get("lists") or {}).get("groups") or []:
        for entry in row.get("players") or []:
            if not isinstance(entry, dict) or entry.get("start"):
                continue
            player = by_pid.get(int(entry["pid"])) if entry.get("pid") is not None else None
            if player and player.get("start"):
                entry["start"] = player["start"]
            elif entry.get("team") and games.get(entry["team"]):
                entry["start"] = games[entry["team"]]
    return day


def record_fingerprint(day):
    """Picks, grades, and player results. Start times are not part of this."""
    groups = []
    for group in day.get("groups") or []:
        players = []
        for player in group.get("players") or []:
            players.append((
                player.get("pid"),
                player.get("pick"),
                player.get("available"),
                player.get("scored"),
                player.get("goals"),
                (player.get("probability") or {}).get("model"),
            ))
        methods = {}
        for method_id, block in (group.get("method_picks") or {}).items():
            block = block or {}
            methods[method_id] = (
                tuple(block.get("pids") or []),
                block.get("hit"),
                tuple(block.get("top3") or []),
                block.get("locked"),
                block.get("top3_hits"),
            )
        pick = group.get("pick") or {}
        groups.append((
            group.get("id"),
            group.get("status"),
            group.get("hit"),
            group.get("top3_hits"),
            group.get("random"),
            group.get("n"),
            tuple(group.get("scorers") or []),
            tuple(pick.get("pids") or []),
            group.get("pick_locked"),
            tuple(players),
            tuple(sorted(methods.items())),
        ))
    morning_hits = []
    morning = day.get("morning") if isinstance(day.get("morning"), dict) else {}
    for group in morning.get("groups") or []:
        morning_hits.append((group.get("id"), group.get("hit"), (group.get("pick") or {}).get("pids")))
    return (day.get("date"), day.get("status"), tuple(groups), tuple(morning_hits))


def publish_start_paths(publish_dir):
    """Day files only. ``seasons/`` is never listed."""
    paths = []
    today = os.path.join(publish_dir, "today.json")
    if os.path.isfile(today):
        paths.append(today)
    days = os.path.join(publish_dir, "days")
    if not os.path.isdir(days):
        return paths
    for name in sorted(os.listdir(days)):
        if len(name) == 15 and name.endswith(".json") and name[4] == "-" and name[7] == "-":
            paths.append(os.path.join(days, name))
    return paths


def backfill_starts(publish_dir, getter, log):
    """Add NHL start times to published days. Picks and grades stay as they are.

    Reads ``today.json`` and ``days/YYYY-MM-DD.json`` only. A second run
    leaves an already filled file unchanged. A feed failure leaves that
    date unchanged.
    """
    from job.publish import _atomic_write

    by_date = {}
    for path in publish_start_paths(publish_dir):
        with open(path) as handle:
            doc = json.load(handle)
        iso = doc.get("date")
        if not iso:
            log("starts skipped %s: no date" % path)
            continue
        by_date.setdefault(iso, []).append((path, doc))
    failed = 0
    updated = 0
    for iso in sorted(by_date):
        payload = getter("https://api-web.nhle.com/v1/score/%s" % iso)
        if payload is None:
            log("starts skipped %s: score feed failed" % iso)
            failed += 1
            continue
        for path, doc in by_date[iso]:
            before = record_fingerprint(doc)
            propagate_starts(doc, payload)
            if record_fingerprint(doc) != before:
                log("starts refused %s: records changed" % os.path.basename(path))
                failed += 1
                continue
            _atomic_write(path, doc)
            updated += 1
            log("starts %s %s" % (iso, os.path.basename(path)))
    log("starts updated %d, failed %d" % (updated, failed))
    return failed


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
