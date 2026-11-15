#!/usr/bin/env python3
"""Score one day's sets with the two public-NHL estimates.

Usage (from this directory, or as ``python clones/score.py``):

  python score.py DATE sets.json [out.json]

``sets.json`` may be:

- ``{"sets":[{"id":1,"players":[{"pid":8477934,"team":"EDM","name":"Leon Draisaitl"}]}]}``
  (opp and home are optional; the schedule fills them)
- ``{"groups":[{"id":1,"players":[{"nhlPlayerId","team","fullName","opponent","homeAway"}]}]}``
  the same shape ``job.groups`` returns
- ``{"groups":{"1":[{"nhl_id","team_abbr","nhl_name"}]}}``

The output is local. Do not put it in the publish directory. The daily job
writes its own JSON, with the labels "DDH-style estimate" and "HCH-style".
These are not a third-party site's percentages or ranks.

Requires Python 3.9+ and numpy.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np

try:
    from clones import ddh_clone, hch_clone, live_features
except ImportError:
    import ddh_clone
    import hch_clone
    import live_features


def load_sets(path):
    with open(path) as handle:
        document = json.load(handle)
    if "playerLists" in document:
        sets = []
        for listing in document["playerLists"]:
            players = []
            for player in listing["players"]:
                players.append({
                    "pid": player["nhlPlayerId"],
                    "team": player["team"],
                    "name": player.get("fullName"),
                    "opp": player.get("opponentTeam"),
                    "home": 1 if player.get("homeAway") == "HOME" else 0,
                })
            sets.append({"id": listing["id"], "players": players})
        return sets
    groups = document.get("groups")
    if isinstance(groups, dict):
        sets = []
        for key, listing in groups.items():
            players = []
            for player in listing:
                if not player.get("nhl_id"):
                    continue
                players.append({
                    "pid": player["nhl_id"],
                    "team": player["team_abbr"],
                    "name": player.get("nhl_name") or player.get("name"),
                })
            sets.append({"id": int(key), "players": players})
        return sets
    if isinstance(groups, list):
        sets = []
        for group in groups:
            players = []
            for player in group.get("players") or []:
                if player.get("unavailable"):
                    continue
                pid = player.get("nhlPlayerId") or player.get("pid") or player.get("nhl_id")
                if not pid:
                    continue
                home = player.get("home")
                if home is None and player.get("homeAway"):
                    home = 1 if player.get("homeAway") == "HOME" else 0
                players.append({
                    "pid": pid,
                    "team": player.get("team") or player.get("team_abbr"),
                    "name": player.get("fullName") or player.get("name") or player.get("nhl_name"),
                    "opp": player.get("opponent") or player.get("opp"),
                    "home": home,
                })
            sets.append({"id": group.get("id"), "players": players})
        return sets
    return document["sets"]


def main():
    date, sets_path = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    with open(os.path.join(HERE, "ddh_clone_params.json")) as handle:
        fitted = json.load(handle)
    params = fitted["params"]
    cache_path = os.path.join(HERE, "cache_prev_seasons.json")
    if os.path.exists(cache_path):
        with open(cache_path) as handle:
            cache = json.load(handle)
    else:
        cache = {}
    sets = load_sets(sets_path)
    everyone = [player for slate in sets for player in slate["players"]]
    features = live_features.build(date, everyone, cache)
    with open(cache_path, "w") as handle:
        json.dump(cache, handle)
    by_id = {}
    for row in features:
        by_id.setdefault(row["pid"], row)
    result = {
        "date": date,
        "model_versions": {
            "ddh_clone": fitted.get("fitted_on"),
            "hch_clone": "goals/GP sort",
        },
        "sets": [],
    }
    for slate in sets:
        rows = [by_id[int(player["pid"])] for player in slate["players"]]
        skip = ("date", "team", "opp", "name")
        columns = {}
        for key in rows[0]:
            if key in skip:
                continue
            columns[key] = np.array([row.get(key, 0) or 0 for row in rows], dtype=float)
        probabilities = ddh_clone.prob(params, columns)
        order = np.argsort(-probabilities)
        estimate_rank = {int(rows[index]["pid"]): place + 1 for place, index in enumerate(order)}
        style_rank = hch_clone.rank(rows)
        players = []
        for row, probability in zip(rows, probabilities):
            players.append({
                "pid": row["pid"],
                "name": row.get("name"),
                "team": row["team"],
                "opp": row["opp"],
                "home": row["home"],
                "ddh_clone_pct": round(100 * float(probability), 1),
                "ddh_clone_rank": estimate_rank[int(row["pid"])],
                "hch_clone_rank": style_rank[int(row["pid"])],
                "hch_data": hch_clone.data_points(row),
            })
        players.sort(key=lambda player: player["ddh_clone_rank"])
        result["sets"].append({"id": slate["id"], "players": players})
    text = json.dumps(result, indent=1)
    if out_path:
        with open(out_path, "w") as handle:
            handle.write(text)
            handle.write("\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
