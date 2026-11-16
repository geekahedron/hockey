"""Per-player inputs are published from values the methods already compute.

Backfill may add those inputs. It must not change a probability, a pick,
or a grade, and it must not open seasons/.
"""
import json
import os

import features
import logistic_json
from job.clone_attach import attach_day, model_snapshot
from job.inputs import _attach_estimate, backfill_inputs, estimate_inputs, json_number
from job.publish import assert_public
from job.run_daily import run
from job.score import score_groups
from job.snapshots import record_fingerprint
from tests.test_clones import _features, _groups, _write_raw


def _feed(url):
    if "/score/" in url:
        return {"games": []}
    return {"data": []}


def _none(_url):
    return None


def _write_day(publish, day):
    days = os.path.join(publish, "days")
    os.makedirs(days)
    text = json.dumps(day)
    with open(os.path.join(days, day["date"] + ".json"), "w") as handle:
        handle.write(text)
    with open(os.path.join(publish, "today.json"), "w") as handle:
        handle.write(text)
    seasons = os.path.join(publish, "seasons", "2025-26")
    os.makedirs(seasons)
    with open(os.path.join(seasons, "season.json"), "w") as handle:
        handle.write('{"keep": true}\n')
    with open(os.path.join(publish, "season.json"), "w") as handle:
        handle.write('{"keep": "season"}\n')
    with open(os.path.join(days, "index.json"), "w") as handle:
        handle.write('{"keep": "index"}\n')


def test_json_number_drops_missing_values():
    assert json_number(None) is None
    assert json_number(float("nan")) is None
    assert json_number(True) is None
    assert json_number(4, 0) == 4
    assert json_number(1.23456789, 6) == 1.234568


def test_score_publishes_model_inputs_without_changing_the_probability(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    monkeypatch.setattr(features, "RAW", raw)
    schedule = {"EDM": 1, "SJS": 0}
    plain = score_groups("2026-11-14", _groups(), schedule)
    cloned = score_groups(
        "2026-11-14", _groups(), schedule, clone_fetch=lambda date, players: _features()
    )
    assert model_snapshot(plain) == model_snapshot(cloned)
    keys = set(logistic_json.FEATS) | {"p_base", "log_g60", "log_p_base", "log1p_cur_gp", "log1p_prev_gp"}
    for group in cloned["groups"]:
        for player in group["players"]:
            model = player["inputs"]["model"]
            assert keys <= set(model)
            assert "role_pp1" not in model
            assert "role_l1" not in model
            estimate = player["inputs"]["estimate"]
            assert "cur_gp" in estimate
            assert "cur_g" in estimate
            assert "cur_sog" in estimate
            assert "prev_ppg" in estimate
            assert "opp_ga_pg" in estimate
            assert "age" not in estimate
            assert "ixg" not in estimate
            assert "ev" not in player["inputs"]
            assert 0 < player["probability"]["model"] < 1
    defense = [player for player in cloned["groups"][1]["players"] if player["position"] == "D"][0]
    assert defense["inputs"]["estimate"]["is_d"] == 1
    assert_public(cloned)


def test_attach_keeps_model_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(features, "RAW", str(tmp_path / "raw"))
    _write_raw(features.RAW)
    day = score_groups("2026-11-14", _groups(), {"EDM": 1, "SJS": 0})
    before = model_snapshot(day)
    model = day["groups"][0]["players"][0]["inputs"]["model"]
    attach_day(day, _features())
    assert model_snapshot(day) == before
    player = day["groups"][0]["players"][0]
    assert player["inputs"]["model"] == model
    assert player["inputs"]["estimate"]["cur_gp"] == 10


def test_duplicate_players_each_receive_estimate_inputs():
    players = [
        {"pid": 7, "position": "C", "team": "EDM"},
        {"pid": 7, "position": "D", "team": "EDM"},
    ]
    day = {"groups": [{"players": [players[0]]}, {"players": [players[1]]}]}
    row = {"pid": 7, "cur_gp": 4, "cur_g": 1, "home": 0}
    assert _attach_estimate(day, [row]) == 2
    assert players[0]["inputs"]["estimate"]["is_d"] == 0
    assert players[1]["inputs"]["estimate"]["is_d"] == 1
    assert "age" not in estimate_inputs(row)


def test_backfill_restores_inputs_without_touching_records(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    monkeypatch.setattr(features, "RAW", raw)
    day = score_groups("2026-11-14", _groups(), {"EDM": 1, "SJS": 0})
    original = {}
    for group in day["groups"]:
        for player in group["players"]:
            original[player["pid"]] = player["inputs"]["model"]
            player["probability"]["ddh_style"] = 0.33
            player["rank"] = {"hch_style": 2}
            player["style"] = {"gp": 9, "goals": 4, "goals_per_game": 0.44}
            player.pop("inputs")
    day["groups"][0]["players"][0]["available"] = False
    day["groups"][0]["players"][0]["position"] = "L"
    day["groups"][0]["hit"] = 1
    fingerprint = record_fingerprint(day)
    publish = str(tmp_path / "publish")
    _write_day(publish, day)
    seasons = open(os.path.join(publish, "seasons", "2025-26", "season.json")).read()
    season = open(os.path.join(publish, "season.json")).read()
    index = open(os.path.join(publish, "days", "index.json")).read()

    failed = backfill_inputs(publish, _feed, raw, lambda message: None)
    assert failed == 0
    saved = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    today = json.load(open(os.path.join(publish, "today.json")))
    assert record_fingerprint(saved) == fingerprint
    assert record_fingerprint(today) == fingerprint
    removed = saved["groups"][0]["players"][0]
    assert removed["available"] is False
    assert removed["position"] == "L"
    assert removed["probability"]["model"] == day["groups"][0]["players"][0]["probability"]["model"]
    assert removed["probability"]["ddh_style"] == 0.33
    assert removed["rank"]["hch_style"] == 2
    assert removed["style"]["gp"] == 9
    assert saved["groups"][0]["hit"] == 1
    for group in saved["groups"]:
        for player in group["players"]:
            assert player["inputs"]["model"] == original[player["pid"]]
            assert "cur_gp" in player["inputs"]["estimate"]
            assert "age" not in player["inputs"]["estimate"]
    assert open(os.path.join(publish, "seasons", "2025-26", "season.json")).read() == seasons
    assert open(os.path.join(publish, "season.json")).read() == season
    assert open(os.path.join(publish, "days", "index.json")).read() == index

    again = backfill_inputs(publish, _feed, raw, lambda message: None)
    assert again == 0
    second = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    assert second["groups"] == saved["groups"]


def test_backfill_refuses_to_write_when_a_probability_changes(tmp_path, monkeypatch):
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    publish = str(tmp_path / "publish")
    day = {
        "date": "2026-11-14",
        "status": "pending",
        "groups": [{
            "id": 1,
            "status": "pending",
            "players": [{
                "pid": 1, "name": "Low", "team": "EDM", "opp": "SJS", "home": 1,
                "position": "C", "probability": {"model": 0.42}, "pick": True,
                "available": True, "scored": None, "goals": None,
            }],
        }],
    }
    _write_day(publish, day)
    import job.inputs as inputs

    def bad(player, feat):
        player["probability"]["model"] = 0.01
        return inputs.model_inputs(feat)

    monkeypatch.setattr(inputs, "_store_model", bad)
    failed = backfill_inputs(publish, _feed, raw, lambda message: None)
    assert failed
    saved = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    assert saved["groups"][0]["players"][0]["probability"]["model"] == 0.42
    assert "inputs" not in saved["groups"][0]["players"][0]


def test_stats_feed_failure_still_saves_model_inputs(tmp_path):
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    publish = str(tmp_path / "publish")
    day = {
        "date": "2026-11-14",
        "status": "graded",
        "groups": [{
            "id": 1,
            "status": "graded",
            "hit": 0,
            "players": [{
                "pid": 1, "name": "Low", "team": "EDM", "opp": "SJS", "home": 1,
                "position": "L", "probability": {"model": 0.42}, "pick": False,
                "available": False, "scored": 0, "goals": 0,
            }],
        }],
    }
    _write_day(publish, day)
    failed = backfill_inputs(publish, _none, raw, lambda message: None)
    assert failed
    saved = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    player = saved["groups"][0]["players"][0]
    assert player["probability"]["model"] == 0.42
    assert player["available"] is False
    assert player["position"] == "L"
    assert saved["groups"][0]["hit"] == 0
    assert "p_base" in player["inputs"]["model"]
    assert "estimate" not in player["inputs"]


def test_empty_archive_leaves_model_inputs_unrecorded(tmp_path):
    raw = str(tmp_path / "raw")
    os.makedirs(raw)
    publish = str(tmp_path / "publish")
    day = {
        "date": "2026-11-14",
        "status": "pending",
        "groups": [{
            "id": 1,
            "players": [{
                "pid": 1, "name": "Low", "team": "EDM", "opp": "SJS", "home": 1,
                "position": "R", "probability": {"model": 0.2}, "pick": False,
            }],
        }],
    }
    _write_day(publish, day)
    failed = backfill_inputs(publish, _feed, raw, lambda message: None)
    assert failed
    saved = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    player = saved["groups"][0]["players"][0]
    assert player["probability"]["model"] == 0.2
    assert "model" not in player.get("inputs", {})
    assert player["inputs"]["estimate"]["cur_gp"] == 0
    assert player["position"] == "R"


def test_run_backfill_inputs_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMS_ENV", raising=False)
    raw = str(tmp_path / "raw")
    _write_raw(raw)
    publish = str(tmp_path / "publish")
    monkeypatch.setattr(features, "RAW", raw)
    day = score_groups("2026-11-14", _groups(), {"EDM": 1, "SJS": 0})
    for group in day["groups"]:
        for player in group["players"]:
            player.pop("inputs", None)
    _write_day(publish, day)
    code = run([
        "--publish", publish,
        "--raw", raw,
        "--backfill-inputs",
        "--no-refresh",
        "--no-grade",
    ], get_json=_feed)
    assert code == 0
    saved = json.load(open(os.path.join(publish, "days", "2026-11-14.json")))
    assert "p_base" in saved["groups"][0]["players"][0]["inputs"]["model"]
    assert "cur_gp" in saved["groups"][0]["players"][0]["inputs"]["estimate"]
