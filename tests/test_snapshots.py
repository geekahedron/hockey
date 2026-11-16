"""Intra-day list snapshots. No live Tims calls and no pick submission."""
import json
import os

import features
from job.clone_attach import set_method_picks
from job.grade import apply_grade
from job.publish import assert_public, publish_day
from job.run_daily import run
from job.snapshots import merge_lists, note_seen, open_slate, same_lists


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = "2026-11-16T03:00:00-05:00"
T1 = "2026-11-16T15:30:00-05:00"
T2 = "2026-11-16T18:00:00-05:00"
T3 = "2026-11-16T19:30:00-05:00"


def _player(pid, name, prob, team="EDM", opp="SJS"):
    return {
        "pid": pid,
        "name": name,
        "team": team,
        "opp": opp,
        "home": 1,
        "position": "C",
        "probability": {"model": prob},
        "pick": False,
        "scored": None,
        "goals": None,
    }


def _group(gid, players):
    ordered = sorted(players, key=lambda row: (-row["probability"]["model"], row["pid"]))
    for player in ordered:
        player["pick"] = False
    pick = None
    if ordered:
        best = ordered[0]["probability"]["model"]
        tied = [player for player in ordered if player["probability"]["model"] == best]
        for player in tied:
            player["pick"] = True
        pick = {
            "pids": [player["pid"] for player in tied],
            "name": " / ".join(player["name"] for player in tied),
            "team": tied[0]["team"],
            "opp": tied[0]["opp"],
            "home": tied[0]["home"],
            "probability": best,
        }
    return {
        "id": gid,
        "status": "pending",
        "players": ordered,
        "pick": pick,
        "hit": None,
        "top3_hits": None,
        "random": None,
        "n": None,
        "scorers": None,
        "method_picks": {
            "model": {
                "pids": list((pick or {}).get("pids") or []),
                "name": None if pick is None else pick["name"],
                "team": None if pick is None else pick["team"],
                "opp": None if pick is None else pick["opp"],
                "home": None if pick is None else pick["home"],
                "probability": None if pick is None else pick["probability"],
                "top3": [player["pid"] for player in ordered[:3]],
                "hit": None,
                "top3_hits": None,
            }
        },
    }


def _shell(groups, when):
    return {
        "schema": 1,
        "date": "2026-11-16",
        "status": "pending",
        "generated_at": when,
        "season": "2026-27",
        "model": "logistic",
        "methods": [{
            "id": "model",
            "label": "Logistic model (player form + matchup)",
            "kind": "probability",
        }],
        "groups": groups,
        "skipped": [],
    }


def _opened(groups, when=T0):
    return open_slate(_shell(groups, when), when)


def _by_pid(group):
    return {player["pid"]: player for player in group["players"]}


def _final(scorers):
    return {"games": [{
        "gameType": 2,
        "gameState": "OFF",
        "homeTeam": {"abbrev": "EDM"},
        "awayTeam": {"abbrev": "SJS"},
        "goals": [
            {"playerId": pid, "periodDescriptor": {"periodType": "REG"}}
            for pid in scorers
        ],
    }]}


def test_stamp_converts_the_server_clock_to_toronto():
    from datetime import datetime, timezone
    from job.snapshots import stamp_toronto
    # 20:30 UTC on this date is 15:30 in Toronto (EST).
    text = stamp_toronto(datetime(2026, 11, 16, 20, 30, tzinfo=timezone.utc))
    assert text.startswith("2026-11-16T15:30:00")
    assert text.endswith("-05:00")


def test_same_list_updates_last_seen_without_a_snapshot():
    first = _opened([_group(1, [_player(1, "Star", 0.5), _player(2, "Depth", 0.2)])])
    again = note_seen(first, T1)
    assert again["snapshots"] == []
    assert again["morning"]["at"] == T0
    assert again["morning"]["groups"][0]["pick"]["pids"] == [1]
    star = _by_pid(again["groups"][0])[1]
    assert star["first_seen"] == T0
    assert star["last_seen"] == T1
    assert star["available"] is True
    assert again["lists"]["groups"][0]["players"][0]["pid"] == 1
    assert same_lists(first, _shell([_group(1, [_player(1, "Star", 0.5), _player(2, "Depth", 0.2)])], T1))


def test_union_tracks_everyone_and_current_pick_ignores_removed():
    first = _opened([_group(1, [_player(1, "Star", 0.5), _player(2, "Depth", 0.4)])])
    second = merge_lists(
        first,
        _shell([_group(1, [_player(2, "Depth", 0.4), _player(3, "New", 0.6)])], T1),
        T1,
    )
    third = merge_lists(
        second,
        _shell([_group(1, [_player(3, "New", 0.6), _player(4, "Late", 0.2)])], T2),
        T2,
    )
    brought_back = merge_lists(
        third,
        _shell([_group(1, [_player(1, "Star", 0.5), _player(3, "New", 0.6)])], T3),
        T3,
    )
    assert [snap["time"] for snap in third["snapshots"]] == [T1, T2]
    assert third["snapshots"][0]["removed"] == [{"group": 1, "pid": 1, "name": "Star"}]
    assert third["snapshots"][0]["added"] == [{"group": 1, "pid": 3, "name": "New"}]
    assert third["snapshots"][1]["removed"] == [{"group": 1, "pid": 2, "name": "Depth"}]
    assert third["snapshots"][1]["added"] == [{"group": 1, "pid": 4, "name": "Late"}]

    seen = _by_pid(third["groups"][0])
    assert set(seen) == {1, 2, 3, 4}
    assert seen[1]["available"] is False
    assert seen[1]["first_seen"] == T0
    assert seen[1]["last_seen"] == T0
    assert seen[1]["removed_at"] == T1
    assert seen[1]["pick"] is False
    assert seen[2]["available"] is False
    assert seen[2]["first_seen"] == T0
    assert seen[2]["last_seen"] == T1
    assert seen[2]["removed_at"] == T2
    assert seen[3]["available"] is True
    assert seen[3]["first_seen"] == T1
    assert seen[3]["last_seen"] == T2
    assert seen[4]["first_seen"] == T2
    assert third["groups"][0]["pick"]["pids"] == [3]
    assert [row["pid"] for row in third["lists"]["groups"][0]["players"]] == [3, 4]
    assert third["morning"]["groups"][0]["pick"]["pids"] == [1]

    back = _by_pid(brought_back["groups"][0])[1]
    assert back["available"] is True
    assert back["first_seen"] == T0
    assert back["last_seen"] == T3
    assert "removed_at" not in back
    assert brought_back["groups"][0]["pick"]["pids"] == [3]


def test_grade_uses_current_pick_and_keeps_morning_as_reference(tmp_path):
    day = _opened([_group(1, [_player(1, "Star", 0.5), _player(2, "Depth", 0.4)])])
    day = merge_lists(
        day,
        _shell([_group(1, [_player(2, "Depth", 0.4), _player(3, "New", 0.2)])], T1),
        T1,
    )
    apply_grade(day, _final([1]))
    group = day["groups"][0]
    removed = _by_pid(group)[1]
    assert removed["available"] is False
    assert removed["scored"] == 1
    assert removed["goals"] == 1
    assert group["pick"]["pids"] == [2]
    assert group["hit"] == 0
    assert group["n"] == 2
    assert group["random"] == 0
    assert group["top3_hits"] == 0
    assert group["scorers"] == []
    morning = day["morning"]["groups"][0]
    assert morning["hit"] == 1
    assert morning["status"] == "graded"
    assert morning["method_picks"]["model"]["hit"] == 1
    assert group["method_picks"]["model"]["hit"] == 0
    assert_public(day)

    publish = tmp_path / "publish"
    publish_day(str(publish), day, as_today=True)
    season = json.load(open(publish / "season.json"))
    assert season["summary"]["picks"] == 1
    assert season["summary"]["hits"] == 0
    assert "morning" not in season["summary"]


def test_removed_player_does_not_take_top3_or_the_hit():
    gone = _player(1, "Star", 0.9)
    gone["available"] = False
    gone["pick"] = True
    stay = _player(2, "Depth", 0.2)
    stay["pick"] = True
    day = _shell([{
        "id": 1,
        "status": "pending",
        "players": [gone, stay],
        "pick": {
            "pids": [2], "name": "Depth", "team": "EDM", "opp": "SJS", "home": 1, "probability": 0.2,
        },
        "hit": None,
        "top3_hits": None,
        "random": None,
        "n": None,
        "scorers": None,
        "method_picks": {
            "model": {
                "pids": [2], "name": "Depth", "team": "EDM", "opp": "SJS", "home": 1,
                "probability": 0.2, "top3": [2], "hit": None, "top3_hits": None,
            }
        },
    }], T1)
    apply_grade(day, _final([1]))
    group = day["groups"][0]
    assert group["hit"] == 0
    assert group["top3_hits"] == 0
    assert group["n"] == 1
    assert group["random"] == 0
    assert group["players"][0]["scored"] == 1


def test_method_picks_skip_players_who_left_the_list():
    group = {
        "players": [
            {
                "pid": 1, "name": "Gone", "team": "EDM", "opp": "SJS", "home": 1,
                "probability": {"model": 0.9, "ddh_style": 0.9},
                "rank": {"hch_style": 1}, "style": {"goals_per_game": 1.2},
                "available": False, "pick": False,
            },
            {
                "pid": 2, "name": "Stay", "team": "EDM", "opp": "SJS", "home": 1,
                "probability": {"model": 0.2, "ddh_style": 0.2},
                "rank": {"hch_style": 2}, "style": {"goals_per_game": 0.1},
                "available": True, "pick": True,
            },
        ],
        "pick": {
            "pids": [2], "name": "Stay", "team": "EDM", "opp": "SJS", "home": 1, "probability": 0.2,
        },
        "hit": None,
        "top3_hits": None,
    }
    set_method_picks(group)
    assert group["method_picks"]["model"]["pids"] == [2]
    assert group["method_picks"]["ddh_style"]["pids"] == [2]
    assert group["method_picks"]["hch_style"]["pids"] == [2]
    assert 1 not in group["method_picks"]["model"]["top3"]
    assert 1 not in group["method_picks"]["hch_style"]["top3"]


def test_already_graded_group_is_not_rewritten():
    day = _opened([_group(1, [_player(1, "Star", 0.5), _player(2, "Depth", 0.4)])])
    apply_grade(day, _final([1]))
    assert day["status"] == "graded"
    assert day["groups"][0]["hit"] == 1
    changed = merge_lists(
        day,
        _shell([_group(1, [_player(2, "Depth", 0.4)])], T1),
        T1,
        frozen_ids=[1],
    )
    assert changed["groups"][0]["hit"] == 1
    assert changed["groups"][0]["pick"]["pids"] == [1]
    assert _by_pid(changed["groups"][0])[1]["available"] is True
    assert changed["snapshots"][0]["removed"][0]["name"] == "Star"
    assert changed["morning"]["groups"][0]["hit"] == 1


def test_page_shows_removed_players_and_morning_picks():
    script = open(os.path.join(ROOT, "web", "app.js")).read()
    style = open(os.path.join(ROOT, "web", "style.css")).read()
    assert "Removed from the Tims list at " in script
    assert "List changes" in script
    assert "Morning pick" in script
    assert "Current pick" in script
    assert "player.removed" in style


def _write_raw(raw):
    os.makedirs(raw)
    games = []
    dates = ["2025-10-08", "2025-10-10", "2025-10-12", "2025-10-15"]
    for index, date in enumerate(dates):
        games.append({
            "id": 2025020001 + index,
            "date": date,
            "home": "EDM",
            "away": "SJS",
            "hs": 3,
            "as": 1,
            "lastPeriod": "REG",
            "sk": [
                [1, "EDM", "C", 1 if index < 3 else 0, 5, 1200, 1, 20, "Star"],
                [2, "EDM", "C", 0, 1, 700, 0, 12, "Depth"],
                [3, "SJS", "C", 1 if index == 0 else 0, 3, 1000, 0, 16, "Other"],
                [4, "SJS", "D", 0, 1, 1100, 0, 18, "Dee"],
            ],
            "gk": [
                [9001, "EDM", 1, 30, 27, 3600, "G1"],
                [9002, "SJS", 1, 28, 26, 3600, "G2"],
            ],
        })
    with open(os.path.join(raw, "box_2025.jsonl"), "w") as handle:
        for game in games:
            handle.write(json.dumps(game) + "\n")
    toi = {}
    for game in games:
        for row in game["sk"]:
            toi["%s_%s" % (game["id"], row[0])] = [60, row[5] - 60, 0]
    with open(os.path.join(raw, "toi_2025.json"), "w") as handle:
        json.dump(toi, handle)


def _groups(path, drop=()):
    players = [
        {"nhlPlayerId": 1, "fullName": "Star", "team": "EDM", "opponent": "SJS",
         "homeAway": "AWAY", "position": "C"},
        {"nhlPlayerId": 2, "fullName": "Depth", "team": "EDM", "opponent": "SJS",
         "homeAway": "AWAY", "position": "C"},
    ]
    players = [row for row in players if row["nhlPlayerId"] not in drop]
    doc = {
        "date": "2026-11-14",
        "groups": [
            {"id": 1, "players": players},
            {"id": 2, "players": [
                {"nhlPlayerId": 3, "fullName": "Other", "team": "SJS", "opponent": "EDM",
                 "homeAway": "HOME", "position": "C"},
            ]},
            {"id": 3, "players": [
                {"nhlPlayerId": 4, "fullName": "Dee", "team": "SJS", "opponent": "EDM",
                 "homeAway": "HOME", "position": "D"},
            ]},
        ],
    }
    with open(path, "w") as handle:
        json.dump(doc, handle)


def _feed(final=False, scorers=()):
    def get_json(url):
        if "/stats/rest/" in url:
            return {"data": []}
        if not url.endswith("/score/2026-11-14"):
            return {"games": []}
        state = "OFF" if final else "FUT"
        goals = [
            {"playerId": pid, "periodDescriptor": {"periodType": "REG"}}
            for pid in scorers
        ]
        return {"games": [{
            "id": 2026020200,
            "gameType": 2,
            "gameState": state,
            "homeTeam": {"abbrev": "EDM", "score": 2 if final else 0},
            "awayTeam": {"abbrev": "SJS", "score": 1 if final else 0},
            "goals": goals if final else [],
        }]}
    return get_json


def test_run_grades_the_latest_list_and_leaves_a_graded_day_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    publish = str(tmp_path / "publish")
    groups = str(tmp_path / "groups.json")
    _write_raw(raw)
    _groups(groups)
    old = features.RAW
    try:
        code = run([
            "--date", "2026-11-14",
            "--groups", groups,
            "--publish", publish,
            "--raw", raw,
            "--no-refresh",
            "--no-grade",
        ], get_json=_feed(final=False))
        assert code == 0
        first = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
        assert first["snapshots"] == []
        assert first["morning"]["groups"][0]["pick"]["pids"] == first["groups"][0]["pick"]["pids"]
        morning_pids = list(first["groups"][0]["pick"]["pids"])
        assert first["groups"][0]["players"][0]["first_seen"]
        assert_public(first)
        drop = list(morning_pids)
        if drop == [1, 2] or drop == [2, 1]:
            drop = drop[:1]

        _groups(groups, drop=tuple(drop))
        code = run([
            "--date", "2026-11-14",
            "--groups", groups,
            "--publish", publish,
            "--raw", raw,
            "--no-refresh",
        ], get_json=_feed(final=True, scorers=tuple(drop)))
        assert code == 0
        changed = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
        assert changed["status"] == "graded"
        assert changed["groups"][0]["hit"] == 0
        for pid in drop:
            assert pid not in changed["groups"][0]["pick"]["pids"]
        scored_morning = sum(1 for pid in morning_pids if pid in drop)
        assert changed["morning"]["groups"][0]["hit"] == round(
            scored_morning / float(len(morning_pids)), 4
        )
        assert changed["morning"]["groups"][0]["pick"]["pids"] == morning_pids
        for pid in drop:
            gone = [row for row in changed["groups"][0]["players"] if row["pid"] == pid][0]
            assert gone["available"] is False
            assert gone["scored"] == 1
            assert gone["first_seen"] == first["generated_at"]
            assert gone["last_seen"] == first["current_at"]
            assert gone["removed_at"]
            assert pid not in [row["pid"] for row in changed["lists"]["groups"][0]["players"]]
        assert {row["pid"] for row in changed["snapshots"][0]["removed"]} == set(drop)
        season = json.load(open(os.path.join(publish, "season.json")))
        assert season["summary"]["hits"] == round(sum(group["hit"] for group in changed["groups"]), 4)
        assert changed["groups"][0]["hit"] == 0

        frozen_hit = changed["groups"][0]["hit"]
        frozen_pick = list(changed["groups"][0]["pick"]["pids"])
        snap_count = len(changed["snapshots"])
        _groups(groups)
        code = run([
            "--date", "2026-11-14",
            "--groups", groups,
            "--publish", publish,
            "--raw", raw,
            "--no-refresh",
        ], get_json=_feed(final=True, scorers=tuple(drop)))
        assert code == 0
        kept = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
        assert kept["groups"][0]["hit"] == frozen_hit
        assert kept["groups"][0]["pick"]["pids"] == frozen_pick
        assert len(kept["snapshots"]) == snap_count
        assert kept["morning"]["groups"][0]["pick"]["pids"] == morning_pids
    finally:
        features.RAW = old
