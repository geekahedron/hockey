"""Grading from an NHL score document: hits, top-3, random, shootouts, pending."""
import json
import os
import sys

from job.grade import apply_grade, goal_counts
from job.publish import build_season, publish_day
from job.score import _pending_group

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def _day(date, groups):
    docs = []
    for index, players in enumerate(groups, 1):
        players = sorted(players, key=lambda row: (-row["probability"]["model"], row["name"]))
        docs.append(_pending_group(index, players))
    return {
        "schema": 1,
        "date": date,
        "status": "pending",
        "generated_at": "2026-11-02T10:00:00-05:00",
        "season": "2026-27",
        "model": "logistic",
        "methods": [{"id": "model", "label": "Model", "description": "logistic"}],
        "groups": docs,
        "skipped": [],
    }


def _final(home, away, scorer_ids, shootout_ids=()):
    goals = []
    for pid in scorer_ids:
        goals.append({"playerId": pid, "periodDescriptor": {"periodType": "REG"}})
    for pid in shootout_ids:
        goals.append({"playerId": pid, "periodDescriptor": {"periodType": "SO"}})
    return {
        "gameType": 2,
        "gameState": "OFF",
        "homeTeam": {"abbrev": home},
        "awayTeam": {"abbrev": away},
        "goals": goals,
    }


def test_goal_counts_ignore_shootout():
    payload = {"games": [_final("EDM", "SJS", [1], shootout_ids=[2])]}
    final, goals = goal_counts(payload)
    assert final == {"EDM": True, "SJS": True}
    assert goals == {1: 1}
    assert 2 not in goals


def test_pending_until_every_team_is_final():
    players = [
        _player(1, "A", 0.4, "EDM", "SJS"),
        _player(2, "B", 0.2, "TOR", "CBJ"),
    ]
    day = _day("2026-11-02", [players])
    payload = {"games": [
        _final("EDM", "SJS", [1]),
        {"gameType": 2, "gameState": "LIVE", "homeTeam": {"abbrev": "TOR"}, "awayTeam": {"abbrev": "CBJ"}, "goals": []},
    ]}
    apply_grade(day, payload)
    assert day["status"] == "pending"
    assert day["groups"][0]["hit"] is None
    assert day["groups"][0]["players"][0]["scored"] is None


def test_hit_top3_random_and_running_rate():
    g1 = [_player(i, "P%d" % i, round(0.5 - i * 0.05, 2), "EDM", "SJS") for i in range(1, 6)]
    g2 = [_player(10 + i, "Q%d" % i, round(0.5 - i * 0.05, 2), "TOR", "CBJ") for i in range(1, 6)]
    g3 = [_player(20 + i, "R%d" % i, round(0.5 - i * 0.05, 2), "COL", "ANA") for i in range(1, 6)]
    day = _day("2026-11-02", [g1, g2, g3])
    # Group 1 pick is pid 1. Scorers 1 and 2. top3 = pids 1,2,3 -> 2 hits. random 2/5.
    # Group 2 pick is pid 11. Scorer 13 only. top3 = 11,12,13 -> 1 hit. random 1/5.
    # Group 3 nobody scores.
    payload = {"games": [
        _final("EDM", "SJS", [1, 2]),
        _final("TOR", "CBJ", [13]),
        _final("COL", "ANA", []),
    ]}
    apply_grade(day, payload)
    assert day["status"] == "graded"
    groups = day["groups"]
    assert groups[0]["hit"] == 1
    assert groups[0]["top3_hits"] == 2
    assert groups[0]["random"] == 0.4
    assert groups[0]["scorers"] == ["P1", "P2"]
    assert groups[0]["players"][0]["goals"] == 1
    assert groups[1]["hit"] == 0
    assert groups[1]["top3_hits"] == 1
    assert groups[1]["random"] == 0.2
    assert groups[2]["hit"] == 0
    assert groups[2]["top3_hits"] == 0
    assert groups[2]["random"] == 0

    day2 = _day("2026-11-03", [
        [_player(1, "A", 0.4, "EDM", "SJS"), _player(2, "B", 0.3, "EDM", "SJS"), _player(3, "C", 0.2, "EDM", "SJS")],
        [_player(4, "D", 0.4, "TOR", "CBJ"), _player(5, "E", 0.3, "TOR", "CBJ"), _player(6, "F", 0.2, "TOR", "CBJ")],
        [_player(7, "G", 0.4, "COL", "ANA"), _player(8, "H", 0.3, "COL", "ANA"), _player(9, "I", 0.2, "COL", "ANA")],
    ])
    apply_grade(day2, {"games": [
        _final("EDM", "SJS", [1]),
        _final("TOR", "CBJ", [4]),
        _final("COL", "ANA", [7]),
    ]})
    season = build_season([day, day2])
    # Day 1: hits 1+0+0 = 1 of 3. Day 2: 3 of 3. Running 4/6.
    assert season["days"][0]["hits"] == 1
    assert season["days"][0]["hit_rate"] == 0.3333
    assert season["days"][0]["running_hit_rate"] == 0.3333
    assert season["days"][0]["top3_hits"] == 3
    assert season["days"][0]["random"] == 0.2
    assert season["days"][1]["hits"] == 3
    assert season["days"][1]["running_hits"] == 4
    assert season["days"][1]["running_picks"] == 6
    assert season["days"][1]["running_hit_rate"] == 0.6667
    assert season["summary"]["picks"] == 6
    assert season["summary"]["hits"] == 4
    assert season["summary"]["hit_rate"] == 0.6667
    randoms = [g["random"] for d in (day, day2) for g in d["groups"]]
    assert season["summary"]["random_baseline"] == round(sum(randoms) / float(len(randoms)), 4)


def test_tied_pick_splits_the_hit():
    players = [_player(1, "A", 0.3), _player(2, "B", 0.3), _player(3, "C", 0.1)]
    day = _day("2026-11-04", [players])
    assert day["groups"][0]["pick"]["name"] == "A / B"
    apply_grade(day, {"games": [_final("EDM", "SJS", [1])]})
    assert day["groups"][0]["hit"] == 0.5


def test_two_goals_count_as_one_scorer():
    players = [_player(1, "A", 0.4), _player(2, "B", 0.2)]
    day = _day("2026-11-05", [players])
    game = _final("EDM", "SJS", [1, 1])
    apply_grade(day, {"games": [game]})
    assert day["groups"][0]["players"][0]["goals"] == 2
    assert day["groups"][0]["players"][0]["scored"] == 1
    assert day["groups"][0]["random"] == 0.5


def test_publish_layout_and_refuses_banned_content(tmp_path):
    players = [_player(1, "A", 0.4), _player(2, "B", 0.2), _player(3, "C", 0.1)]
    day = _day("2026-11-02", [players, list(players), list(players)])
    # list() is shallow; rebuild distinct groups
    day = _day("2026-11-02", [
        [_player(1, "A", 0.4), _player(2, "B", 0.2), _player(3, "C", 0.1)],
        [_player(4, "D", 0.4, "TOR", "CBJ"), _player(5, "E", 0.2, "TOR", "CBJ"), _player(6, "F", 0.1, "TOR", "CBJ")],
        [_player(7, "G", 0.4, "COL", "ANA"), _player(8, "H", 0.2, "COL", "ANA"), _player(9, "I", 0.1, "COL", "ANA")],
    ])
    apply_grade(day, {"games": [
        _final("EDM", "SJS", [1]),
        _final("TOR", "CBJ", []),
        _final("COL", "ANA", [7]),
    ]})
    publish_day(str(tmp_path), day, as_today=True)
    for rel in ("today.json", "season.json", "seasons.json", "days/index.json", "days/2026-11-02.json"):
        assert os.path.isfile(tmp_path / rel)
    manifest = json.load(open(tmp_path / "seasons.json"))
    assert [row["id"] for row in manifest] == ["2026-27", "2025-26"]
    assert manifest[1]["backtest"] is True
    assert manifest[1]["base"] == "data/seasons/2025-26/"
    from job.publish import PublishError, assert_public
    dirty = {"pick": "x", "note": "see datadrivenhockey"}
    try:
        assert_public(dirty)
        raised = False
    except PublishError:
        raised = True
    assert raised
    try:
        assert_public({"hch": 1})
        raised = False
    except PublishError:
        raised = True
    assert raised
