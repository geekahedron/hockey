"""Grade published days from an NHL score document.

A group is graded only when every team on that group's slate has a final
game (gameState OFF or FINAL). Non-shootout goals count. Shootout goals
(periodType SO) do not.

The recorded pick is the one stored on the group: the current pick. Players
with ``available`` false stayed on an earlier list and are not in that pick,
the top three, or the random baseline. Their scored flags are still filled
when their game is final. Morning picks, when the day has them, are graded
onto ``day["morning"]`` only. Grading does not rescore and does not attach
any other site's picks.

random is the share of the group's players who scored, which is the hit
rate of picking one of them at random. top3_hits counts how many of the
first three (model order, as stored) scored. A tie for the published pick
splits the hit: the fraction of the tied players who scored.
"""
import datetime as dt


def _stamp():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def goal_counts(payload):
    """Return (final_by_team, goals_by_pid) from an NHL /v1/score/DATE body.

    final_by_team maps abbrev -> True when that team's game is OFF or FINAL,
    False when the game is listed but not over. Teams that are not on the
    board are absent.
    """
    final = {}
    goals = {}
    if not isinstance(payload, dict):
        return final, goals
    for game in payload.get("games") or []:
        if game.get("gameType") not in (None, 2, "2"):
            continue
        done = game.get("gameState") in ("OFF", "FINAL")
        for side in ("homeTeam", "awayTeam"):
            abbrev = (game.get(side) or {}).get("abbrev")
            if abbrev:
                final[abbrev] = done
        if not done:
            continue
        for goal in game.get("goals") or []:
            period = (goal.get("periodDescriptor") or {}).get("periodType")
            if period == "SO":
                continue
            pid = goal.get("playerId")
            if pid is None:
                continue
            pid = int(pid)
            goals[pid] = goals.get(pid, 0) + 1
    return final, goals


def fill_method_hits(group):
    """Fill hit and top-3 for each stored method pick.

    The model block copies the hit ``apply_grade`` already computed from
    ``player["pick"]``. Other methods use the pids stored when the day was
    scored. This does not choose a new pick.
    """
    picks = group.get("method_picks") or {}
    if not picks:
        return
    players = group.get("players") or []
    by_pid = {}
    for player in players:
        by_pid[int(player["pid"])] = player
    model = picks.get("model")
    if model is not None:
        model["hit"] = group.get("hit")
        model["top3_hits"] = group.get("top3_hits")
    graded = group.get("status") == "graded"
    for method_id, block in picks.items():
        if method_id == "model":
            continue
        if not graded:
            block["hit"] = None
            block["top3_hits"] = None
            continue
        pids = [int(pid) for pid in (block.get("pids") or [])]
        tied = [by_pid[pid] for pid in pids if pid in by_pid]
        if tied and all(player.get("scored") is not None for player in tied):
            block["hit"] = round(
                sum(player["scored"] for player in tied) / float(len(tied)), 4
            )
        else:
            block["hit"] = None
        top_ids = [int(pid) for pid in (block.get("top3") or [])]
        top = [by_pid[pid] for pid in top_ids if pid in by_pid]
        if top and all(player.get("scored") is not None for player in top):
            block["top3_hits"] = int(sum(player["scored"] for player in top))
        else:
            block["top3_hits"] = 0
    return group


def _on_current_list(player):
    return player.get("available", True) is not False


def apply_grade(day, payload):
    """Fill hit / scorers / random on ``day``. Pending groups stay pending.

    Returns the same day dict. The hit is the current pick. Players no longer
    on the Tims list still receive scored and goals for reference.
    """
    final, goals = goal_counts(payload)
    for group in day.get("groups") or []:
        players = group.get("players") or []
        if not players:
            group["status"] = "graded"
            group["hit"] = None
            group["top3_hits"] = 0
            group["random"] = None
            group["n"] = 0
            group["scorers"] = []
            continue
        eligible = [player for player in players if _on_current_list(player)]
        team_source = eligible if eligible else players
        teams = []
        for player in team_source:
            if player.get("team") and player["team"] not in teams:
                teams.append(player["team"])
        ready = all(final.get(team) is True for team in teams) if teams else True
        if not ready:
            group["status"] = "pending"
            group["hit"] = None
            group["top3_hits"] = None
            group["random"] = None
            group["n"] = None
            group["scorers"] = None
            for player in players:
                player["scored"] = None
                player["goals"] = None
            continue
        for player in players:
            team = player.get("team")
            if team and final.get(team) is not True:
                player["scored"] = None
                player["goals"] = None
                continue
            count = int(goals.get(int(player["pid"]), 0))
            player["goals"] = count
            player["scored"] = 1 if count else 0
        scorers = []
        for player in eligible:
            if player.get("scored"):
                scorers.append(player["name"])
        n = len(eligible)
        scored_n = sum(player["scored"] for player in eligible)
        tied = [player for player in eligible if player.get("pick")]
        if tied:
            hit = sum(player["scored"] for player in tied) / float(len(tied))
        else:
            hit = None
        top = eligible[:3]
        group["status"] = "graded"
        group["hit"] = None if hit is None else round(hit, 4)
        group["top3_hits"] = int(sum(player["scored"] for player in top)) if top else 0
        group["random"] = round(scored_n / float(n), 4) if n else None
        group["n"] = n
        group["scorers"] = scorers
    for group in day.get("groups") or []:
        fill_method_hits(group)
    statuses = [g.get("status") for g in day.get("groups") or []]
    if statuses and all(s == "graded" for s in statuses):
        day["status"] = "graded"
    elif any(s == "graded" for s in statuses):
        day["status"] = "partial"
    else:
        day["status"] = "pending"
    day["graded_at"] = _stamp()
    from job.snapshots import grade_morning
    grade_morning(day, final, goals)
    return day
