"""Attach the two public-NHL methods to a day the logistic model already scored.

Nothing here refits the logistic model or rewrites its probabilities, its
pick, or the stored player order. The estimate is a probability in the same
0-1 units as the model. The ranking is this season's goals per game.

Feature rows come from ``clones.live_features`` (public NHL APIs, capped at
the day before the slate) or from a caller-supplied list in tests.
"""
import json
import os

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARAMS_PATH = os.path.join(_ROOT, "clones", "ddh_clone_params.json")
_SKIP = {"date", "team", "opp", "name", "pos"}

# First morning the public page has a slate to backfill.
BACKFILL_FROM = "2026-11-02"


class CloneError(Exception):
    pass


def load_params(path=None):
    with open(path or _PARAMS_PATH) as handle:
        fitted = json.load(handle)
    params = fitted.get("params")
    if not isinstance(params, dict):
        raise CloneError("fitted parameters are missing")
    return params


def load_cache(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_cache(path, cache):
    if not path:
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(cache, handle)
        handle.write("\n")
    os.replace(tmp, path)


def cache_path(raw_dir):
    return os.path.join(raw_dir, "clone_prev_seasons.json")


def players_for_fetch(day):
    """One row per published player, using the slate's team, opponent, and home."""
    rows = []
    seen = set()
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            pid = int(player["pid"])
            if pid in seen:
                continue
            seen.add(pid)
            rows.append({
                "pid": pid,
                "team": player.get("team"),
                "opp": player.get("opp"),
                "home": player.get("home"),
                "name": player.get("name"),
            })
    return rows


def _number(value):
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _columns(rows):
    keys = []
    for row in rows:
        for key, value in row.items():
            if key in _SKIP or key in keys:
                continue
            if key != "pid" and isinstance(value, str):
                continue
            keys.append(key)
    if "pid" not in keys:
        keys.append("pid")
    columns = {}
    for key in keys:
        columns[key] = np.array([_number(row.get(key)) for row in rows], dtype=float)
    return columns


def _merge(player, features):
    row = dict(features)
    row["pid"] = int(player["pid"])
    if player.get("team"):
        row["team"] = player["team"]
    if player.get("opp"):
        row["opp"] = player["opp"]
    if player.get("home") is not None:
        row["home"] = int(player["home"])
    if player.get("name"):
        row["name"] = player["name"]
    if player.get("position") == "D":
        row["is_d"] = 1
    elif player.get("position"):
        row["is_d"] = 0
    return row


def _finite_probability(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < 0 or number > 1:
        return None
    return round(number, 4)


def score_rows(rows, params=None):
    """Map pid to a rounded probability. Ranking is per set, not here."""
    if not rows:
        return {}
    from clones import ddh_clone
    params = params or load_params()
    probabilities = ddh_clone.prob(params, _columns(rows))
    out = {}
    for row, probability in zip(rows, probabilities):
        number = _finite_probability(probability)
        if number is None:
            continue
        out[int(row["pid"])] = number
    return out


def set_method_picks(group):
    """Record each method's pick. The model pick is copied, not recomputed.

    Players no longer on the Tims list (``available`` false) are not eligible.
    """
    players = [
        player for player in (group.get("players") or [])
        if player.get("available", True) is not False
    ]
    picks = {}
    stored = group.get("pick")
    if stored:
        picks["model"] = {
            "pids": list(stored.get("pids") or []),
            "name": stored.get("name"),
            "team": stored.get("team"),
            "opp": stored.get("opp"),
            "home": stored.get("home"),
            "probability": stored.get("probability"),
            "top3": [player["pid"] for player in players[:3]],
            "hit": group.get("hit"),
            "top3_hits": group.get("top3_hits"),
        }
    estimated = [
        player for player in players
        if isinstance((player.get("probability") or {}).get("ddh_style"), (int, float))
    ]
    estimated.sort(key=lambda player: (
        -player["probability"]["ddh_style"], player["name"], player["pid"]
    ))
    if estimated:
        best = estimated[0]["probability"]["ddh_style"]
        tied = [player for player in estimated if player["probability"]["ddh_style"] == best]
        picks["ddh_style"] = {
            "pids": [player["pid"] for player in tied],
            "name": " / ".join(player["name"] for player in tied),
            "team": tied[0]["team"],
            "opp": tied[0]["opp"],
            "home": tied[0]["home"],
            "probability": best,
            "top3": [player["pid"] for player in estimated[:3]],
            "hit": None,
            "top3_hits": None,
        }
    ranked = [
        player for player in players
        if isinstance((player.get("rank") or {}).get("hch_style"), int)
    ]
    ranked.sort(key=lambda player: (player["rank"]["hch_style"], player["pid"]))
    if ranked:
        top = ranked[0]
        style = top.get("style") or {}
        picks["hch_style"] = {
            "pids": [top["pid"]],
            "name": top["name"],
            "team": top["team"],
            "opp": top["opp"],
            "home": top["home"],
            "probability": None,
            "rank": top["rank"]["hch_style"],
            "goals_per_game": style.get("goals_per_game"),
            "top3": [player["pid"] for player in ranked[:3]],
            "hit": None,
            "top3_hits": None,
        }
    group["method_picks"] = picks
    return picks


def attach_day(day, features, params=None):
    """Add estimate and ranking fields. Model numbers on ``day`` stay put.

    ``features`` is the list returned by ``live_features.build`` for this
    morning. Players with no row keep their model fields and are left out of
    the two extra picks.
    """
    from clones import hch_clone
    from job.inputs import estimate_inputs
    from job.score import METHODS

    by_pid = {}
    for row in features or []:
        by_pid[int(row["pid"])] = row
    day["methods"] = [dict(item) for item in METHODS]
    prepared = {}
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            pid = int(player["pid"])
            if pid in prepared or pid not in by_pid:
                continue
            prepared[pid] = _merge(player, by_pid[pid])
    probabilities = score_rows(list(prepared.values()), params=params)
    for group in day.get("groups") or []:
        rows = []
        for player in group.get("players") or []:
            pid = int(player["pid"])
            if pid in prepared:
                rows.append(prepared[pid])
        ranks = hch_clone.rank(rows) if rows else {}
        for player in group.get("players") or []:
            pid = int(player["pid"])
            if pid not in prepared:
                continue
            player.setdefault("probability", {})
            if pid in probabilities:
                player["probability"]["ddh_style"] = probabilities[pid]
            if pid in ranks:
                player.setdefault("rank", {})
                player["rank"]["hch_style"] = int(ranks[pid])
                player["style"] = hch_clone.data_points(prepared[pid])
            stored = player.get("inputs")
            if not isinstance(stored, dict):
                stored = {}
                player["inputs"] = stored
            stored["estimate"] = estimate_inputs(prepared[pid])
        set_method_picks(group)
        if group.get("status") == "graded":
            from job.grade import fill_method_hits
            fill_method_hits(group)
    return day


def model_snapshot(day):
    """Fields the backfill is not allowed to change."""
    groups = []
    for group in day.get("groups") or []:
        players = []
        for player in group.get("players") or []:
            players.append({
                "pid": player.get("pid"),
                "model": (player.get("probability") or {}).get("model"),
                "pick": player.get("pick"),
                "name": player.get("name"),
                "team": player.get("team"),
                "opp": player.get("opp"),
                "home": player.get("home"),
                "scored": player.get("scored"),
                "goals": player.get("goals"),
            })
        groups.append({
            "id": group.get("id"),
            "status": group.get("status"),
            "pick": group.get("pick"),
            "hit": group.get("hit"),
            "top3_hits": group.get("top3_hits"),
            "random": group.get("random"),
            "n": group.get("n"),
            "scorers": group.get("scorers"),
            "players": players,
        })
    return {
        "date": day.get("date"),
        "status": day.get("status"),
        "model": day.get("model"),
        "groups": groups,
    }
