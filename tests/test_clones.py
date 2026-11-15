"""The two extra methods sit beside the frozen logistic model.

Sample features here are made up. Nothing in this file is another site's
published percentage, rank, or history.
"""
import json
import os

import pytest

import features
from job.clone_attach import attach_day, model_snapshot
from job.grade import apply_grade
from job.publish import PublishError, assert_public, build_season, publish_day
from job.run_daily import run
from job.score import score_groups
from clones import hch_clone, live_features


def _row(pid, goals, games=10, home=1, is_d=0, shots=None):
    row = {
        "pid": pid,
        "team": "EDM",
        "opp": "SJS",
        "home": home,
        "is_d": is_d,
        "rest_t": 2,
        "opp_ga_pg": 3.1,
        "lg_ga_pg": 3.0,
        "name": "P%d" % pid,
    }
    for prefix in ("cur", "prev", "prev2", "prev3"):
        for field in ("gp", "g", "sog", "toi", "pptoi", "ppg"):
            row["%s_%s" % (prefix, field)] = 0
    row["cur_gp"] = games
    row["cur_g"] = goals
    row["cur_sog"] = goals * 4 if shots is None else shots
    row["cur_toi"] = 16.0 * games
    row["cur_pptoi"] = 2.0 * games
    row["cur_ppg"] = 0
    return row


def _player(pid, name, prob, team="EDM", opp="SJS", position="C"):
    return {
        "nhlPlayerId": pid,
        "fullName": name,
        "team": team,
        "opponent": opp,
        "homeAway": "HOME",
        "position": position,
    }


def _groups():
    return {
        "date": "2026-11-14",
        "groups": [
            {"id": 1, "players": [
                _player(1, "Low", 0),
                _player(2, "High", 0),
                _player(3, "Mid", 0),
            ]},
            {"id": 2, "players": [_player(4, "Only", 0, "SJS", "EDM", "D")]},
            {"id": 3, "players": [_player(5, "Third", 0, "SJS", "EDM")]},
        ],
    }


def _write_raw(raw):
    os.makedirs(raw)
    games = []
    for index, date in enumerate(["2025-10-08", "2025-10-10", "2025-10-12", "2025-10-15"]):
        games.append({
            "id": 2025020001 + index,
            "date": date,
            "home": "EDM",
            "away": "SJS",
            "hs": 3,
            "as": 1,
            "lastPeriod": "REG",
            "sk": [
                [1, "EDM", "C", 0, 2, 900, 0, 18, "Low"],
                [2, "EDM", "C", 2, 6, 1100, 1, 20, "High"],
                [3, "EDM", "C", 1, 4, 1000, 0, 19, "Mid"],
                [4, "SJS", "D", 0, 1, 1200, 0, 22, "Only"],
                [5, "SJS", "C", 1, 3, 1000, 0, 18, "Third"],
            ],
            "gk": [[9001, "EDM", 1, 30, 27, 3600, "G1"], [9002, "SJS", 1, 28, 26, 3600, "G2"]],
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


def _features():
    return [
        _row(1, 1),
        _row(2, 9),
        _row(3, 4),
        _row(4, 2, is_d=1),
        _row(5, 3),
    ]


def test_ranking_breaks_ties_toward_the_lower_player_id():
    rows = [
        _row(30, 5),
        _row(10, 5),
        _row(20, 2),
    ]
    # 1 goal in 3 games and 2 in 6 are both 0.33, so the lower id leads.
    rows[0]["cur_gp"], rows[0]["cur_g"] = 6, 2
    rows[1]["cur_gp"], rows[1]["cur_g"] = 3, 1
    places = hch_clone.rank(rows)
    assert places[10] == 1
    assert places[30] == 2
    assert places[20] == 3
    assert hch_clone.data_points(rows[1])["goals_per_game"] == 0.33
    assert hch_clone.data_points(rows[0])["goals_per_game"] == 0.33


def test_estimate_rises_with_goals_and_home(tmp_path):
    quiet = _row(1, 0, home=0)
    loud = _row(2, 25, home=0)
    home = _row(3, 25, home=1)
    from job.clone_attach import score_rows
    scored = score_rows([quiet, loud, home])
    assert 0 < scored[1] < scored[2] < scored[3] < 1


def test_attach_does_not_change_the_model(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    old = features.RAW
    features.RAW = raw
    try:
        schedule = {"EDM": 1, "SJS": 0}
        plain = score_groups("2026-11-14", _groups(), schedule)
        cloned = score_groups(
            "2026-11-14", _groups(), schedule, clone_fetch=lambda date, players: _features()
        )
        for plain_group, cloned_group in zip(plain["groups"], cloned["groups"]):
            assert [p["probability"]["model"] for p in plain_group["players"]] == [
                p["probability"]["model"] for p in cloned_group["players"]
            ]
            assert [p["pid"] for p in plain_group["players"]] == [p["pid"] for p in cloned_group["players"]]
            assert plain_group["pick"] == cloned_group["pick"]
            assert cloned_group["method_picks"]["hch_style"]["pids"] == [
                max(
                    cloned_group["players"],
                    key=lambda player: (
                        (player.get("style") or {}).get("goals_per_game") or 0,
                        -player["pid"],
                    ),
                )["pid"]
            ]
        # High has 9 goals in 10, so the ranking pick is not the logistic pick
        # unless the model happens to agree. The estimate pick follows goals.
        group = cloned["groups"][0]
        assert group["method_picks"]["hch_style"]["name"] == "High"
        assert group["method_picks"]["ddh_style"]["name"] == "High"
        apply_grade(cloned, {"games": [{
            "gameType": 2,
            "gameState": "OFF",
            "homeTeam": {"abbrev": "EDM"},
            "awayTeam": {"abbrev": "SJS"},
            "goals": [{"playerId": 2, "periodDescriptor": {"periodType": "REG"}}],
        }]})
        # Group 2 is SJS, which is the away team of the final game above, so it grades too.
        graded = {group["id"]: group for group in cloned["groups"]}
        assert graded[1]["status"] == "graded"
        assert graded[1]["method_picks"]["hch_style"]["hit"] == 1
        assert graded[1]["method_picks"]["ddh_style"]["hit"] == 1
        if graded[1]["pick"]["pids"] != [2]:
            assert graded[1]["hit"] == 0
        season = build_season([cloned])
        assert season["summary"] == season["by_method"]["model"]["summary"]
        assert season["by_method"]["hch_style"]["summary"]["picks"] >= 1
        assert season["by_method"]["ddh_style"]["summary"]["hits"] >= 1
        assert_public(cloned)
        assert_public(season)
    finally:
        features.RAW = old


def test_public_copy_allows_the_method_labels_only():
    assert_public({"label": "DDH-style estimate", "id": "ddh_style"})
    assert_public({"label": "HCH-style", "id": "hch_style"})
    with pytest.raises(PublishError):
        assert_public({"hch": 1})
    with pytest.raises(PublishError):
        assert_public({"note": "ddh says 40"})
    with pytest.raises(PublishError):
        assert_public({"note": "see datadrivenhockey"})


def test_backfill_adds_columns_without_rescoring_the_model(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    publish = str(tmp_path / "publish")
    _write_raw(raw)
    old = features.RAW
    features.RAW = raw
    try:
        day = score_groups("2026-11-08", _groups(), {"EDM": 1, "SJS": 0})
        before = json.loads(json.dumps(model_snapshot(day)))
        publish_day(publish, day, as_today=True)

        def getter(url):
            if "/stats/rest/" in url:
                return {"data": []}
            return {"games": []}

        code = run([
            "--publish", publish,
            "--raw", raw,
            "--backfill-clones",
            "--backfill-from", "2026-11-02",
            "--backfill-to", "2026-11-08",
            "--no-refresh",
        ], get_json=getter)
        assert code == 0
        saved = json.load(open(os.path.join(publish, "days", "2026-11-08.json")))
        assert model_snapshot(saved) == before
        assert saved["methods"][1]["label"] == "DDH-style estimate"
        assert saved["groups"][0]["players"][0]["probability"]["ddh_style"] > 0
        assert "hch_style" in saved["groups"][0]["players"][0]["rank"]
        assert saved["groups"][0]["pick"] == before["groups"][0]["pick"]
        season = json.load(open(os.path.join(publish, "season.json")))
        assert "ddh_style" in season["by_method"]
        assert "hch_style" in season["by_method"]
    finally:
        features.RAW = old


def test_feature_fetch_stops_at_the_morning_before_the_slate():
    seen = []

    def fetch(url):
        seen.append(url)
        if "/score/" in url:
            return {"games": []}
        return {"data": []}

    live_features.build("2026-11-14", [{"pid": 7, "team": "EDM", "home": 1}], cache={}, fetch=fetch)
    joined = "\n".join(seen)
    assert "2026-11-13" in joined
    assert "gameTypeId" in joined
    assert "api.nhle.com/stats/rest" in joined
    assert "api-web.nhle.com" in joined
