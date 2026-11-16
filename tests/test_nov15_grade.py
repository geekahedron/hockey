"""2026-11-15: an empty Tims slate must not abort, and a null hit must be retried.

Tims returned three empty groups at 9pm, so the job exited before it could
lock the picks. Midnight grading then marked the day graded with hit left
null, and later runs skipped it. These tests use fixtures only.
"""
import json
import os

import pytest

import features
from job.grade import apply_grade
from job.groups import GroupsSourceError, hockey_players_to_groups, unwrap_hockey_players
from job.run_daily import _needs_grade, run
from job.snapshots import open_slate
from tests.test_run import _write_raw


HERE = os.path.dirname(os.path.abspath(__file__))
HOCKEY = os.path.join(HERE, "fixtures", "tims_hockey_players.json")
MORNING = "2026-11-15T10:00:00-05:00"
NINE_PM = "2026-11-15T21:00:00-05:00"
AFTER_MIDNIGHT = "2026-11-16T01:00:00-05:00"


def _board(early="FUT", late="FUT", scorers=()):
    goals = [
        {"playerId": pid, "periodDescriptor": {"periodType": "REG"}}
        for pid in scorers
    ]
    return {"games": [
        {
            "gameType": 2,
            "gameState": early,
            "startTimeUTC": "2026-11-16T00:00:00Z",
            "homeTeam": {"abbrev": "EDM"},
            "awayTeam": {"abbrev": "SJS"},
            "goals": goals if early in ("OFF", "FINAL") else [],
        },
        {
            "gameType": 2,
            "gameState": late,
            "startTimeUTC": "2026-11-16T03:00:00Z",
            "homeTeam": {"abbrev": "TOR"},
            "awayTeam": {"abbrev": "CBJ"},
            "goals": [],
        },
    ]}


def _player(pid, name, prob, team, opp, start):
    return {
        "pid": pid,
        "name": name,
        "team": team,
        "opp": opp,
        "home": 1,
        "position": "C",
        "probability": {"model": prob},
        "pick": pid == 1,
        "available": True,
        "start": start,
        "first_seen": MORNING,
        "scored": None,
        "goals": None,
    }


def _broken_midnight_day():
    """What apply_grade left when the pick had starts but was never locked."""
    players = [
        _player(1, "Early", 0.6, "EDM", "SJS", "2026-11-16T00:00:00+00:00"),
        _player(2, "Late", 0.2, "TOR", "CBJ", "2026-11-16T03:00:00+00:00"),
    ]
    return {
        "schema": 1,
        "date": "2026-11-15",
        "status": "graded",
        "generated_at": MORNING,
        "season": "2026-27",
        "model": "logistic",
        "methods": [{"id": "model", "label": "Logistic model (player form + matchup)", "kind": "probability"}],
        "groups": [{
            "id": 1,
            "status": "graded",
            "players": players,
            "pick": {"pids": [1], "name": "Early", "team": "EDM", "opp": "SJS", "home": 1, "probability": 0.6},
            "hit": None,
            "top3_hits": None,
            "random": None,
            "n": None,
            "scorers": None,
            "method_picks": {
                "model": {
                    "pids": [1],
                    "name": "Early",
                    "team": "EDM",
                    "opp": "SJS",
                    "home": 1,
                    "probability": 0.6,
                    "top3": [1, 2],
                    "hit": None,
                    "top3_hits": None,
                    "locked": False,
                    "top3_locked": False,
                }
            },
        }],
        "skipped": [],
    }


def _feed(board):
    def get_json(url):
        if "/score/2026-11-15" in url:
            return board
        return {"data": []}
    return get_json


class _EmptyLists(object):
    def fetch(self, date):
        iso = date.isoformat() if hasattr(date, "isoformat") else str(date)
        return {
            "date": iso,
            "groups": [
                {"id": 1, "players": []},
                {"id": 2, "players": []},
                {"id": 3, "players": []},
            ],
        }


class _Unused(object):
    def fetch(self, date):
        raise AssertionError("graded day must not ask Tims for a new list")


def _publish(path, day):
    days = os.path.join(path, "days")
    os.makedirs(days)
    text = json.dumps(day)
    with open(os.path.join(days, day["date"] + ".json"), "w") as handle:
        handle.write(text)
    with open(os.path.join(path, "today.json"), "w") as handle:
        handle.write(text)


def test_needs_grade_retries_a_null_official_hit_and_stops_without_a_pick():
    broken = _broken_midnight_day()
    assert _needs_grade(broken) is True
    pending = _broken_midnight_day()
    pending["status"] = "pending"
    pending["groups"][0]["status"] = "pending"
    assert _needs_grade(pending) is True
    done = _broken_midnight_day()
    done["groups"][0]["hit"] = 0
    assert _needs_grade(done) is False
    empty = _broken_midnight_day()
    empty["groups"][0]["pick"] = {"pids": []}
    empty["groups"][0]["method_picks"]["model"]["pids"] = []
    empty["groups"][0]["players"][0]["pick"] = False
    assert _needs_grade(empty) is False


def test_final_games_grade_the_stored_pick_when_it_was_never_locked():
    day = _broken_midnight_day()
    apply_grade(day, _board(early="OFF", late="OFF", scorers=(1,)))
    group = day["groups"][0]
    assert group["status"] == "graded"
    assert group["hit"] == 1
    assert group["method_picks"]["model"]["hit"] == 1
    assert group["players"][0]["goals"] == 1
    assert _needs_grade(day) is False


def test_final_games_with_no_stored_pick_leave_the_hit_empty():
    day = _broken_midnight_day()
    group = day["groups"][0]
    group["pick"] = {"pids": [], "name": None}
    group["method_picks"]["model"]["pids"] = []
    group["method_picks"]["model"]["locked"] = False
    for player in group["players"]:
        player["pick"] = False
    apply_grade(day, _board(early="OFF", late="OFF"))
    assert group["status"] == "graded"
    assert group["hit"] is None
    assert _needs_grade(day) is False


def test_regrade_locks_the_nov15_pick_and_fills_the_hit(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    monkeypatch.setattr("job.run_daily.stamp_toronto", lambda now=None: AFTER_MIDNIGHT)
    publish = str(tmp_path / "publish")
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    _publish(publish, _broken_midnight_day())
    monkeypatch.setattr(features, "RAW", raw)

    code = run([
        "--date", "2026-11-15",
        "--publish", publish,
        "--raw", raw,
        "--no-refresh",
    ], get_json=_feed(_board(early="OFF", late="OFF", scorers=(1,))), tims_source=_Unused())

    assert code == 0
    day = json.load(open(os.path.join(publish, "days", "2026-11-15.json")))
    group = day["groups"][0]
    assert day["status"] == "graded"
    assert group["hit"] == 1
    assert group["method_picks"]["model"]["locked"] is True
    assert group["method_picks"]["model"]["pids"] == [1]
    assert group["pick"]["pids"] == [1]
    assert _needs_grade(day) is False


def test_nine_pm_empty_tims_slate_locks_started_picks(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    monkeypatch.setattr("job.run_daily.stamp_toronto", lambda now=None: NINE_PM)
    publish = str(tmp_path / "publish")
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    monkeypatch.setattr(features, "RAW", raw)
    shell = {
        "schema": 1,
        "date": "2026-11-15",
        "status": "pending",
        "generated_at": MORNING,
        "season": "2026-27",
        "model": "logistic",
        "methods": [{"id": "model", "label": "Logistic model (player form + matchup)", "kind": "probability"}],
        "groups": [{
            "id": 1,
            "status": "pending",
            "players": [
                _player(1, "Early", 0.6, "EDM", "SJS", "2026-11-16T00:00:00+00:00"),
                _player(2, "Late", 0.2, "TOR", "CBJ", "2026-11-16T03:00:00+00:00"),
            ],
            "pick": {"pids": [1], "name": "Early", "team": "EDM", "opp": "SJS", "home": 1, "probability": 0.6},
            "hit": None,
            "method_picks": {
                "model": {
                    "pids": [1], "name": "Early", "probability": 0.6,
                    "top3": [1, 2], "locked": False, "top3_locked": False, "hit": None,
                }
            },
        }],
        "skipped": [],
    }
    opened = open_slate(shell, MORNING, schedule=_board())
    _publish(publish, opened)

    code = run([
        "--date", "2026-11-15",
        "--publish", publish,
        "--raw", raw,
        "--no-refresh",
    ], get_json=_feed(_board()), tims_source=_EmptyLists())

    assert code == 0
    day = json.load(open(os.path.join(publish, "days", "2026-11-15.json")))
    group = day["groups"][0]
    by_pid = {player["pid"]: player for player in group["players"]}
    assert group["pick"]["pids"] == [1]
    assert group["pick_locked"] is True
    assert group["method_picks"]["model"]["locked"] is True
    assert by_pid[1]["unavailable_reason"] == "game_started"
    assert by_pid[1]["pick"] is True
    assert by_pid[2]["unavailable_reason"] == "removed"
    assert by_pid[2]["pick"] is False
    assert group["status"] == "pending"
    assert group["hit"] is None


def test_all_three_empty_groups_are_a_completed_list_check():
    payload = json.load(open(HOCKEY))
    data = unwrap_hockey_players(payload)
    for raw in data["sets"]:
        raw["players"] = []

    def roster_get(url):
        raise AssertionError(url)

    doc = hockey_players_to_groups(data, roster_get, "2026-11-14")
    assert doc["date"] == "2026-11-14"
    assert [group["id"] for group in doc["groups"]] == [1, 2, 3]
    assert [group["players"] for group in doc["groups"]] == [[], [], []]


def test_one_empty_group_is_still_an_error():
    payload = json.load(open(HOCKEY))
    data = unwrap_hockey_players(payload)
    data["sets"][1]["players"] = []
    with pytest.raises(GroupsSourceError) as exc:
        hockey_players_to_groups(data, lambda url: {"forwards": [], "defensemen": [], "goalies": []}, "2026-11-14")
    assert "group 2 is empty" in str(exc.value)
