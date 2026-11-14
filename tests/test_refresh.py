"""Incremental NHL refresh writes box scores once and does not rescan a finished season."""
import datetime as dt
import json
import os

import pytest

from job.refresh import RefreshError, refresh


def _boxscore(gid="2025020001", date="2025-10-08"):
    return {
        "gameType": 2,
        "gameState": "OFF",
        "id": int(gid),
        "gameDate": date,
        "homeTeam": {"abbrev": "EDM", "score": 3},
        "awayTeam": {"abbrev": "SJS", "score": 1},
        "gameOutcome": {"lastPeriodType": "REG"},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{
                    "playerId": 8478402, "position": "C", "goals": 1, "sog": 4,
                    "toi": "20:00", "powerPlayGoals": 1, "shifts": 22,
                    "name": {"default": "C. McDavid"},
                }],
                "defense": [],
                "goalies": [{
                    "playerId": 8470001, "starter": True, "shotsAgainst": 25,
                    "saves": 24, "toi": "60:00", "name": {"default": "S. Skinner"},
                }],
            },
            "awayTeam": {
                "forwards": [],
                "defense": [],
                "goalies": [{
                    "playerId": 8470002, "starter": True, "shotsAgainst": 30,
                    "saves": 27, "toi": "60:00", "name": {"default": "G"},
                }],
            },
        },
    }


def test_refresh_appends_a_final_game_once(tmp_path):
    calls = []

    def get_json(url):
        calls.append(url)
        if "/score/" in url:
            day = url.rsplit("/", 1)[-1]
            if day == "2025-10-08":
                return {"games": [{
                    "id": 2025020001, "gameType": 2, "gameState": "OFF",
                    "homeTeam": {"abbrev": "EDM"}, "awayTeam": {"abbrev": "SJS"},
                }]}
            return {"games": []}
        if url.endswith("/boxscore"):
            return _boxscore()
        return None

    def toi_window(args):
        year, start, end = args
        assert year == 2025
        assert start <= "2025-10-08" <= end
        return {"2025020001_8478402": [80, 1120, 0]}

    added = refresh(
        dt.date(2025, 10, 10), str(tmp_path), get_json, toi_window, seasons=[2025]
    )
    assert added == 1
    lines = open(os.path.join(str(tmp_path), "box_2025.jsonl")).read().strip().splitlines()
    assert len(lines) == 1
    game = json.loads(lines[0])
    assert game["id"] == 2025020001
    assert game["home"] == "EDM"
    assert game["sk"][0][0] == 8478402
    toi = json.load(open(os.path.join(str(tmp_path), "toi_2025.json")))
    assert toi["2025020001_8478402"] == [80, 1120, 0]

    calls[:] = []
    added = refresh(
        dt.date(2025, 10, 10), str(tmp_path), get_json, toi_window, seasons=[2025]
    )
    assert added == 0
    lines = open(os.path.join(str(tmp_path), "box_2025.jsonl")).read().strip().splitlines()
    assert len(lines) == 1
    assert any(url.endswith("/boxscore") for url in calls) is False


def test_score_feed_failure_raises(tmp_path):
    def get_json(url):
        return None

    with pytest.raises(RefreshError):
        refresh(dt.date(2025, 10, 10), str(tmp_path), get_json, lambda args: {}, seasons=[2025])
    assert not os.path.exists(os.path.join(str(tmp_path), "scan_2025.json"))


def test_finished_prior_season_is_not_rescanned(tmp_path):
    calls = {"n": 0}

    def get_json(url):
        calls["n"] += 1
        if "/score/" in url:
            return {"games": []}
        return None

    refresh(dt.date(2026, 1, 15), str(tmp_path), get_json, lambda args: {}, seasons=[2024])
    assert calls["n"] > 200
    state = json.load(open(os.path.join(str(tmp_path), "scan_2024.json")))
    assert state["complete"] is True
    calls["n"] = 0
    refresh(dt.date(2026, 1, 15), str(tmp_path), get_json, lambda args: {}, seasons=[2024])
    assert calls["n"] == 0
