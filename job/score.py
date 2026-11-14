"""Score one day's normalized pick groups with the frozen logistic model.

Probabilities come from model/logistic_json.py (numpy only). The joblib
pipeline is not loaded. Feature construction is features.FeatureBuilder;
this module does not change those formulas.

Published players carry a probability object keyed by method id so a later
method can add a column without a new file format. Only "model" is filled in.
"""
import datetime as dt
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "model")
if _MODEL not in sys.path:
    sys.path.insert(0, _MODEL)

from job.refresh import season_year

# Plug-in list. The page renders one column per entry. A future method is
# another object here plus a number under player["probability"][id].
# Do not put another site's percentages, ranks, or picks in this list.
class ScoreError(Exception):
    pass


METHODS = [
    {
        "id": "model",
        "label": "Model",
        "description": (
            "Logistic regression on shrunk NHL rates. "
            "Probability of at least one non-shootout goal."
        ),
    },
]


def _as_date(when):
    if isinstance(when, dt.datetime):
        return when.date()
    if isinstance(when, dt.date):
        return when
    return dt.date.fromisoformat(str(when)[:10])


def _stamp():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def season_label(when):
    year = season_year(when)
    return "%d-%02d" % (year, (year + 1) % 100)


def schedule_map(payload):
    """Map team abbrev -> 1 home, 0 away, from an NHL score document."""
    out = {}
    if not isinstance(payload, dict):
        return out
    for game in payload.get("games") or []:
        if game.get("gameType") not in (None, 2, "2"):
            continue
        home = (game.get("homeTeam") or {}).get("abbrev")
        away = (game.get("awayTeam") or {}).get("abbrev")
        if home:
            out[home] = 1
        if away:
            out[away] = 0
    return out


def _round_prob(value):
    return round(float(value), 4)


def score_groups(when, groups, schedule):
    """Return a pending day document. ``schedule`` is abbrev -> 1/0.

    Players marked unavailable are left out. A player with no team or
    opponent is skipped and named in ``skipped`` (names only).
    """
    import pandas as pd
    import features
    import logistic_json

    when = _as_date(when)
    ds = when.isoformat()
    year = season_year(when)
    skaters, teams, goalies = features.load()
    if len(skaters) == 0:
        raise ScoreError("no NHL box scores in raw/; refresh before scoring")
    builder = features.FeatureBuilder(skaters, teams, goalies)

    rows = []
    meta = []
    skipped = []
    for group in groups.get("groups") or []:
        for player in group.get("players") or []:
            if player.get("unavailable"):
                continue
            team = player.get("team")
            opponent = player.get("opponent")
            if not team or not opponent:
                skipped.append(player.get("fullName") or str(player.get("nhlPlayerId")))
                continue
            if team in schedule:
                home = int(schedule[team])
            else:
                home = 1 if player.get("homeAway") == "HOME" else 0
            position = player.get("position") or "F"
            hint = "D" if position == "D" else "F"
            feat = builder.build(
                int(player["nhlPlayerId"]), team, opponent, home, ds, year, hint
            )
            rows.append(feat)
            meta.append((int(group["id"]), player, home, position))

    probs = []
    if rows:
        frame = pd.DataFrame(rows)
        probs = logistic_json.predict_proba(frame)[:, 1]

    by_group = {}
    for (gid, player, home, position), prob in zip(meta, probs):
        by_group.setdefault(gid, []).append({
            "pid": int(player["nhlPlayerId"]),
            "name": player.get("fullName") or "",
            "team": player.get("team"),
            "opp": player.get("opponent"),
            "home": int(home),
            "position": position,
            "probability": {"model": _round_prob(prob)},
            "pick": False,
            "scored": None,
            "goals": None,
        })

    group_docs = []
    for group in groups.get("groups") or []:
        gid = int(group["id"])
        players = by_group.get(gid, [])
        players.sort(key=lambda row: (-row["probability"]["model"], row["name"], row["pid"]))
        group_docs.append(_pending_group(gid, players))

    day = {
        "schema": 1,
        "date": ds,
        "status": "pending",
        "generated_at": _stamp(),
        "season": season_label(when),
        "model": "logistic",
        "methods": [dict(item) for item in METHODS],
        "groups": group_docs,
        "skipped": skipped,
    }
    return day


def _pending_group(gid, players):
    pick = _pick_block(players)
    return {
        "id": gid,
        "status": "pending",
        "players": players,
        "pick": pick,
        "hit": None,
        "top3_hits": None,
        "random": None,
        "n": None,
        "scorers": None,
    }


def _pick_block(players):
    if not players:
        return None
    best = players[0]["probability"]["model"]
    tied = [p for p in players if p["probability"]["model"] == best]
    for player in players:
        player["pick"] = player in tied
    names = " / ".join(p["name"] for p in tied)
    return {
        "pids": [p["pid"] for p in tied],
        "name": names,
        "team": tied[0]["team"],
        "opp": tied[0]["opp"],
        "home": tied[0]["home"],
        "probability": best,
    }
