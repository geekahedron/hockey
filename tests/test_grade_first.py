"""Today's missing Tims slate must not block grading.

The Tims source here is a stub. Nothing in this file calls the live API
or submits a pick.
"""
import json
import os

from job.groups import GroupsSourceError
from job.run_daily import NOT_READY, run


class _NotReady(object):
    def fetch(self, date):
        raise GroupsSourceError(
            "HockeyPlayers slate is for 2026-11-13, not %s. "
            "Published JSON was left unchanged." % date
        )


class _Revoked(object):
    def fetch(self, date):
        raise GroupsSourceError(
            "Tims refresh token was rejected. Published JSON was left unchanged."
        )


def _pending_yesterday():
    return {
        "schema": 1,
        "date": "2026-11-13",
        "status": "pending",
        "generated_at": "2026-11-13T10:15:00-05:00",
        "season": "2026-27",
        "model": "logistic",
        "methods": [{"id": "model", "label": "Logistic model (player form + matchup)", "kind": "probability"}],
        "groups": [{
            "id": 1,
            "status": "pending",
            "players": [{
                "pid": 1,
                "name": "Star",
                "team": "EDM",
                "opp": "SJS",
                "home": 1,
                "position": "C",
                "probability": {"model": 0.4},
                "pick": True,
                "scored": None,
                "goals": None,
            }],
            "pick": {
                "name": "Star",
                "pids": [1],
                "probability": 0.4,
                "team": "EDM",
                "opp": "SJS",
                "home": 1,
            },
            "hit": None,
            "top3_hits": None,
            "random": None,
            "n": None,
            "scorers": None,
        }],
        "skipped": [],
    }


def _game(state="FUT"):
    return {
        "id": 2026020200,
        "gameType": 2,
        "gameState": state,
        "gameScheduleState": "OK",
        "homeTeam": {"abbrev": "EDM", "score": 0},
        "awayTeam": {"abbrev": "SJS", "score": 0},
        "goals": [],
    }


def _feed(url):
    if url.endswith("/score/2026-11-14"):
        return {"games": [_game()]}
    if not url.endswith("/score/2026-11-13"):
        return {"games": [_game()]}
    return {"games": [{
        "id": 2026020100,
        "gameType": 2,
        "gameState": "OFF",
        "homeTeam": {"abbrev": "EDM", "score": 2},
        "awayTeam": {"abbrev": "SJS", "score": 1},
        "goals": [{"playerId": 1, "periodDescriptor": {"periodType": "REG"}}],
    }]}


def test_missing_slate_grades_yesterday_and_exits_not_ready(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    publish = tmp_path / "publish"
    day = _pending_yesterday()
    (publish / "days").mkdir(parents=True)
    (publish / "days" / "2026-11-13.json").write_text(json.dumps(day))
    (publish / "today.json").write_text(json.dumps(day))
    log_path = tmp_path / "logs" / "daily.log"

    code = run([
        "--date", "2026-11-14",
        "--publish", str(publish),
        "--no-refresh",
        "--log", str(log_path),
    ], get_json=_feed, tims_source=_NotReady())

    assert code == NOT_READY
    assert NOT_READY == 75
    graded = json.load(open(publish / "days" / "2026-11-13.json"))
    assert graded["status"] == "graded"
    assert graded["groups"][0]["hit"] == 1
    visible = json.load(open(publish / "today.json"))
    assert visible["date"] == "2026-11-13"
    assert visible["status"] == "graded"
    assert visible["groups"][0]["hit"] == 1
    assert not (publish / "days" / "2026-11-14.json").exists()
    season = json.load(open(publish / "season.json"))
    assert season["summary"]["picks"] == 1
    assert season["summary"]["hits"] == 1
    text = log_path.read_text()
    assert "not ready" in text
    assert "today.json left unchanged" in text


def test_rejected_token_is_not_the_retry_code(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    publish = tmp_path / "publish"
    day = _pending_yesterday()
    day["status"] = "graded"
    day["groups"][0]["status"] = "graded"
    day["groups"][0]["hit"] = 0
    day["groups"][0]["players"][0]["scored"] = 0
    day["groups"][0]["players"][0]["goals"] = 0
    publish.mkdir()
    before = json.dumps(day)
    (publish / "today.json").write_text(before)
    (publish / "days").mkdir()
    (publish / "days" / "2026-11-13.json").write_text(before)
    log_path = tmp_path / "logs" / "daily.log"

    code = run([
        "--date", "2026-11-14",
        "--publish", str(publish),
        "--no-refresh",
        "--log", str(log_path),
    ], get_json=_feed, tims_source=_Revoked())

    assert code == 1
    assert json.load(open(publish / "today.json"))["date"] == "2026-11-13"
    assert "left unchanged" in log_path.read_text()
    assert not (publish / "days" / "2026-11-14.json").exists()


class _Spy(object):
    def __init__(self):
        self.called = False

    def fetch(self, date):
        self.called = True
        raise GroupsSourceError(
            "HockeyPlayers slate is for 2026-11-13, not %s. "
            "Published JSON was left unchanged." % date
        )


def test_no_nhl_games_publishes_an_empty_day_without_tims(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    publish = tmp_path / "publish"
    day = _pending_yesterday()
    (publish / "days").mkdir(parents=True)
    (publish / "days" / "2026-11-13.json").write_text(json.dumps(day))
    (publish / "today.json").write_text(json.dumps(day))
    log_path = tmp_path / "logs" / "daily.log"
    spy = _Spy()

    def feed(url):
        if url.endswith("/score/2026-11-13"):
            return _feed(url)
        return {"games": []}

    code = run([
        "--date", "2026-11-14",
        "--publish", str(publish),
        "--no-refresh",
        "--log", str(log_path),
    ], get_json=feed, tims_source=spy)

    assert code == 0
    assert spy.called is False
    saved = json.load(open(publish / "days" / "2026-11-14.json"))
    assert saved["status"] == "no_games"
    assert saved["groups"] == []
    assert saved["methods"] == []
    assert saved["games"] == {}
    assert saved["picks"] == []
    visible = json.load(open(publish / "today.json"))
    assert visible["date"] == "2026-11-14"
    assert visible["status"] == "no_games"
    index = json.load(open(publish / "days" / "index.json"))
    row = [item for item in index["days"] if item["date"] == "2026-11-14"][0]
    assert row["status"] == "no_games"
    assert row["picks"] == 0
    assert row["hits"] is None
    season = json.load(open(publish / "season.json"))
    assert season["summary"]["picks"] == 1
    assert season["summary"]["hits"] == 1
    assert all(item["date"] != "2026-11-14" for item in season["days"])
    assert "no games 2026-11-14" in log_path.read_text()


def test_games_after_an_off_day_ask_tims_again(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    publish = tmp_path / "publish"
    (publish / "days").mkdir(parents=True)
    off = {
        "schema": 1,
        "date": "2026-11-14",
        "status": "no_games",
        "groups": [],
        "methods": [],
        "games": {},
        "picks": [],
    }
    (publish / "days" / "2026-11-14.json").write_text(json.dumps(off))
    (publish / "today.json").write_text(json.dumps(off))
    log_path = tmp_path / "logs" / "daily.log"
    spy = _Spy()
    code = run([
        "--date", "2026-11-14",
        "--publish", str(publish),
        "--no-refresh",
        "--log", str(log_path),
    ], get_json=_feed, tims_source=spy)
    assert code == NOT_READY
    assert spy.called is True
    assert json.load(open(publish / "today.json"))["status"] == "no_games"
