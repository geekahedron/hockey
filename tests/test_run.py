"""End-to-end daily run against a tiny raw directory and a fake NHL feed."""
import json
import os

import pytest

import features
from job.run_daily import run

CANARY = "canary-secret-value-do-not-leak"


def _write_raw(raw):
    os.makedirs(raw)
    games = []
    dates = ["2025-10-08", "2025-10-10", "2025-10-12", "2025-10-15"]
    for index, date in enumerate(dates):
        gid = 2025020001 + index
        games.append({
            "id": gid,
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


def _groups(path):
    doc = {
        "date": "2026-11-14",
        "groups": [
            {"id": 1, "players": [
                {"nhlPlayerId": 1, "fullName": "Star", "team": "EDM", "opponent": "SJS",
                 "homeAway": "AWAY", "position": "C"},
                {"nhlPlayerId": 2, "fullName": "Depth", "team": "EDM", "opponent": "SJS",
                 "homeAway": "AWAY", "position": "C"},
                {"nhlPlayerId": 99, "fullName": "Scratched", "team": "EDM", "opponent": "SJS",
                 "homeAway": "HOME", "position": "C", "unavailable": True},
            ]},
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


def test_run_scores_and_then_grades(tmp_path, monkeypatch):
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
        today = json.load(open(os.path.join(publish, "today.json")))
        assert today["date"] == "2026-11-14"
        assert today["status"] == "pending"
        assert [m["id"] for m in today["methods"]] == ["model", "ddh_style", "hch_style"]
        assert today["methods"][1]["label"] == "Scoring-rate estimate"
        assert today["methods"][2]["label"] == "Goals per game"
        by_name = {}
        for group in today["groups"]:
            assert group["players"]
            probs = [p["probability"]["model"] for p in group["players"]]
            assert probs == sorted(probs, reverse=True)
            for player in group["players"]:
                assert 0 < player["probability"]["model"] < 1
                assert 0 < player["probability"]["ddh_style"] < 1
                assert player["rank"]["hch_style"] >= 1
                assert "p_base" in player["inputs"]["model"]
                assert "log_p_base" in player["inputs"]["model"]
                assert "log1p_cur_gp" in player["inputs"]["model"]
                assert "role_pp1" not in player["inputs"]["model"]
                assert "cur_gp" in player["inputs"]["estimate"]
                assert "cur_toi" in player["inputs"]["estimate"]
                assert "age" not in player["inputs"]["estimate"]
                by_name[player["name"]] = player
            assert "model" in group["method_picks"]
            assert "ddh_style" in group["method_picks"]
            assert "hch_style" in group["method_picks"]
        assert "Scratched" not in by_name
        # Schedule says EDM is home, so the file's AWAY flag is overridden.
        assert by_name["Star"]["home"] == 1
        assert by_name["Star"]["team"] == "EDM"
        assert by_name["Star"]["position"] == "C"
        assert by_name["Dee"]["position"] == "D"
        assert by_name["Dee"]["inputs"]["estimate"]["is_d"] == 1
        assert by_name["Other"]["home"] == 0
        blob = json.dumps(today).lower()
        assert "datadrivenhockey" not in blob
        assert "hockeychallengehelper" not in blob

        pick = today["groups"][0]["pick"]["pids"][0]
        code = run([
            "--date", "2026-11-14",
            "--groups", groups,
            "--publish", publish,
            "--raw", raw,
            "--no-refresh",
        ], get_json=_feed(final=True, scorers=(pick,)))
        assert code == 0
        graded = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
        assert graded["status"] == "graded"
        assert graded["groups"][0]["hit"] == 1
        assert graded["groups"][0]["random"] is not None
        season = json.load(open(os.path.join(publish, "season.json")))
        assert season["summary"]["picks"] == 3
        assert season["summary"]["hits"] == round(sum(g["hit"] for g in graded["groups"]), 4)
        index = json.load(open(os.path.join(publish, "days", "index.json")))
        assert index["today"] == "2026-11-14"
        assert index["days"][0]["date"] == "2026-11-14"
    finally:
        features.RAW = old


def test_log_and_secrets_stay_out_of_the_publish_dir(tmp_path, monkeypatch):
    publish = tmp_path / "publish"
    publish.mkdir()
    log_path = publish / "daily.log"
    with pytest.raises(SystemExit):
        run([
            "--date", "2026-11-14",
            "--publish", str(publish),
            "--groups", str(tmp_path / "missing.json"),
            "--no-refresh",
            "--log", str(log_path),
        ])

    env_path = tmp_path / "tims.env"
    env_path.write_text(
        "TIMS_CLIENT_ID=app-client\nTIMS_COGNITO_ID=us-east-1:subject\n"
        "TIMS_REFRESH_TOKEN=%s\n" % CANARY
    )
    monkeypatch.setenv("TIMS_ENV", str(env_path))
    yesterday = {"schema": 1, "date": "2026-11-13", "status": "graded", "groups": []}
    (publish / "today.json").write_text(json.dumps(yesterday))
    before = (publish / "today.json").read_text()

    def transport(method, url, body, headers):
        return 400, {"__type": "NotAuthorizedException", "message": "Refresh Token has been revoked"}

    from job.groups import TimsGroupsSource
    source = TimsGroupsSource(
        env_path=str(env_path),
        transport=transport,
        roster_get=lambda url: {},
        publish_dir=str(publish),
    )
    log_path = tmp_path / "logs" / "daily.log"
    code = run([
        "--date", "2026-11-14",
        "--publish", str(publish),
        "--no-refresh",
        "--log", str(log_path),
    ], get_json=lambda url: {"games": [{
        "gameState": "FUT",
        "gameScheduleState": "OK",
        "homeTeam": {"abbrev": "EDM"},
        "awayTeam": {"abbrev": "SJS"},
    }]}, tims_source=source)
    assert code == 1
    text = log_path.read_text()
    assert CANARY not in text
    assert "left unchanged" in text
    assert (publish / "today.json").read_text() == before
    assert not (publish / "days" / "2026-11-14.json").exists()
    for root, dirs, files in os.walk(str(publish)):
        for name in files:
            assert CANARY not in open(os.path.join(root, name)).read()
