"""Injury designations and games missed sit beside the frozen picks."""
import json
import os

from job.injury import (
    RETURNING_MIN,
    absence_for,
    annotate,
    apply_absence,
    apply_injuries,
    backfill_absence,
    badge_code,
    load_report,
    normalize_name,
    parse_report,
)
from job.snapshots import record_fingerprint


def _report():
    return {
        "injuries": [
            {
                "displayName": "Colorado Avalanche",
                "injuries": [
                    {
                        "status": "Out",
                        "date": "2026-11-14T17:37Z",
                        "shortComment": "Makar (lower body) is out.",
                        "type": {"abbreviation": "O"},
                        "details": {
                            "type": "Lower Body",
                            "fantasyStatus": {"abbreviation": "OUT"},
                        },
                        "athlete": {
                            "displayName": "Cale Makar",
                            "team": {"abbreviation": "COL"},
                        },
                    },
                    {
                        "status": "Injured Reserve",
                        "date": "2026-11-01T12:00Z",
                        "shortComment": "see datadrivenhockey",
                        "type": {"abbreviation": "IR"},
                        "details": {
                            "type": "Knee",
                            "fantasyStatus": {"abbreviation": "IR-LT"},
                        },
                        "athlete": {
                            "displayName": "Josh Manson",
                            "team": {"abbreviation": "COL"},
                        },
                    },
                ],
            },
            {
                "displayName": "Chicago Blackhawks",
                "injuries": [
                    {
                        "status": "Day-To-Day",
                        "date": "2026-11-15T00:03Z",
                        "shortComment": "",
                        "type": {"abbreviation": "DD"},
                        "details": {
                            "type": "Undisclosed",
                            "fantasyStatus": {"abbreviation": "Day-To-Day"},
                        },
                        "athlete": {
                            "displayName": "Tyler Bertuzzi",
                            "team": {"abbreviation": "CHI"},
                        },
                    }
                ],
            },
        ]
    }


def _player(pid, name, team, prob=0.2):
    return {
        "pid": pid,
        "name": name,
        "team": team,
        "probability": {"model": prob},
        "pick": pid == 1,
        "available": True,
        "scored": None,
        "goals": None,
    }


def _day():
    return {
        "date": "2026-11-16",
        "status": "pending",
        "groups": [{
            "id": 1,
            "status": "pending",
            "hit": None,
            "players": [
                _player(1, "Cale Makar", "COL", 0.4),
                _player(2, "Tyler Bertuzzi", "CHI", 0.3),
                _player(3, "Connor McDavid", "EDM", 0.5),
                _player(4, "Josh Manson", "COL", 0.1),
            ],
        }],
    }


def _write_boxes(raw):
    os.makedirs(raw)
    games = [
        {"id": 1, "date": "2026-11-02", "home": "COL", "away": "DAL",
         "sk": [[1, "COL", "D", 0, 1, 1000, 0, 10, "Cale Makar"],
                [4, "COL", "D", 0, 1, 900, 0, 10, "Josh Manson"]]},
        {"id": 2, "date": "2026-11-04", "home": "EDM", "away": "COL",
         "sk": [[3, "EDM", "C", 1, 4, 1100, 0, 12, "Connor McDavid"]]},
        {"id": 3, "date": "2026-11-06", "home": "COL", "away": "SJS", "sk": []},
        {"id": 4, "date": "2026-11-08", "home": "COL", "away": "ANA", "sk": []},
        {"id": 5, "date": "2026-11-10", "home": "VGK", "away": "COL", "sk": []},
        {"id": 6, "date": "2026-11-12", "home": "COL", "away": "DAL", "sk": []},
        {"id": 7, "date": "2026-11-14", "home": "COL", "away": "MIN", "sk": []},
        {"id": 8, "date": "2026-11-16", "home": "COL", "away": "EDM",
         "sk": [[1, "COL", "D", 1, 3, 1000, 0, 10, "Cale Makar"]]},
    ]
    with open(os.path.join(raw, "box_2026.jsonl"), "w") as handle:
        for game in games:
            handle.write(json.dumps(game) + "\n")


def test_badge_codes_cover_the_public_statuses():
    assert badge_code("Day-To-Day", "Day-To-Day", "DD") == "DTD"
    assert badge_code("Out", "OUT", "O") == "OUT"
    assert badge_code("Injured Reserve", "IR", "IR") == "IR"
    assert badge_code("Injured Reserve", "IR-LT", "IR") == "LTIR"
    assert badge_code("Questionable", "Q", "Q") == "Q"
    assert badge_code("Game Time Decision", "GTD", "GTD") == "GTD"
    assert normalize_name("Tyler Bertuzzi Jr.") == "tyler bertuzzi"


def test_report_matches_name_and_team_without_changing_the_pick():
    rows = parse_report(_report())
    day = _day()
    before = record_fingerprint(day)
    assert apply_injuries(day, rows) == 3
    players = {player["name"]: player for player in day["groups"][0]["players"]}
    assert players["Cale Makar"]["injury"]["status"] == "OUT"
    assert players["Cale Makar"]["injury"]["detail"] == "Makar (lower body) is out."
    assert players["Cale Makar"]["injury"]["updated"] == "2026-11-14"
    assert players["Cale Makar"]["injury"]["source"] == "espn"
    assert players["Tyler Bertuzzi"]["injury"]["status"] == "DTD"
    assert players["Tyler Bertuzzi"]["injury"]["detail"] == "Undisclosed"
    assert players["Josh Manson"]["injury"]["status"] == "LTIR"
    assert "datadrivenhockey" not in players["Josh Manson"]["injury"]["detail"]
    assert "injury" not in players["Connor McDavid"]
    assert players["Cale Makar"]["probability"]["model"] == 0.4
    assert record_fingerprint(day) == before
    apply_injuries(day, [])
    assert "injury" not in players["Cale Makar"]


def test_absence_counts_team_games_after_the_last_one(tmp_path):
    raw = str(tmp_path / "raw")
    _write_boxes(raw)
    day = _day()
    assert apply_absence(day, raw) == 3
    players = {player["name"]: player for player in day["groups"][0]["players"]}
    # Nov 2, then six COL games before Nov 16. The Nov 16 game is the slate.
    assert players["Cale Makar"]["absence"] == {
        "missed_team_games": 6,
        "last_played": "2026-11-02",
    }
    assert players["Josh Manson"]["absence"]["missed_team_games"] == 6
    assert players["Connor McDavid"]["absence"]["missed_team_games"] == 0
    assert "absence" not in players["Tyler Bertuzzi"]
    assert RETURNING_MIN == 3


def test_feed_failure_keeps_a_same_day_cache_and_does_not_raise(tmp_path):
    raw = str(tmp_path / "raw")
    os.makedirs(raw)
    rows = load_report(lambda url: _report(), raw, "2026-11-16", lambda message: None)
    assert rows and rows[0]["status"] == "OUT"
    again = load_report(lambda url: None, raw, "2026-11-16", lambda message: None)
    assert again[0]["name"] == "Cale Makar"
    assert load_report(lambda url: None, raw, "2026-11-15", lambda message: None) is None
    day = _day()
    day["groups"][0]["players"][0]["injury"] = {"status": "DTD", "detail": "kept", "updated": None, "source": "espn"}

    def boom(url):
        raise OSError("down")

    annotate(day, boom, raw, "2026-11-15", lambda message: None, designations=True)
    assert day["groups"][0]["players"][0]["injury"]["status"] == "DTD"
    assert day["groups"][0]["players"][0]["probability"]["model"] == 0.4


def test_old_slate_does_not_receive_todays_designations(tmp_path):
    raw = str(tmp_path / "raw")
    _write_boxes(raw)
    day = _day()
    day["date"] = "2026-11-10"
    annotate(day, lambda url: _report(), raw, "2026-11-16", lambda message: None, designations=False)
    assert "injury" not in day["groups"][0]["players"][0]
    # Last played Nov 2; COL played Nov 4, 6, 8 before this slate.
    assert day["groups"][0]["players"][0]["absence"]["missed_team_games"] == 3


def test_backfill_absence_leaves_records_and_skips_seasons(tmp_path):
    raw = str(tmp_path / "raw")
    _write_boxes(raw)
    publish = str(tmp_path / "publish")
    day = _day()
    day["groups"][0]["hit"] = 1
    fingerprint = record_fingerprint(day)
    days = os.path.join(publish, "days")
    os.makedirs(days)
    with open(os.path.join(days, "2026-11-16.json"), "w") as handle:
        json.dump(day, handle)
    with open(os.path.join(publish, "today.json"), "w") as handle:
        json.dump(day, handle)
    seasons = os.path.join(publish, "seasons", "2024-25")
    os.makedirs(seasons)
    with open(os.path.join(seasons, "season.json"), "w") as handle:
        handle.write('{"keep": true}\n')
    failed = backfill_absence(publish, raw, lambda message: None)
    assert failed == 0
    saved = json.load(open(os.path.join(days, "2026-11-16.json")))
    assert record_fingerprint(saved) == fingerprint
    assert saved["groups"][0]["hit"] == 1
    assert saved["groups"][0]["players"][0]["absence"]["missed_team_games"] == 6
    assert "injury" not in saved["groups"][0]["players"][0]
    assert open(os.path.join(seasons, "season.json")).read() == '{"keep": true}\n'
    again = backfill_absence(publish, raw, lambda message: None)
    assert again == 0
    second = json.load(open(os.path.join(days, "2026-11-16.json")))
    assert second["groups"] == saved["groups"]
