"""Published JSON has the fields the page reads, and no banned brands."""
import json
import os

from job.publish import PublishError, assert_public
from job.score import METHODS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
BANNED = ("datadrivenhockey", "hockeychallengehelper", "ddh", "hch")


def _words(text):
    out = []
    token = []
    for ch in text.lower():
        if ch.isalnum():
            token.append(ch)
        else:
            if token:
                out.append("".join(token))
                token = []
    if token:
        out.append("".join(token))
    return out


_METHOD_PHRASES = (
    "ddh-style estimate",
    "ddh-style",
    "ddh_style",
    "hch-style",
    "hch_style",
)


def assert_clean(text, where, allow_method_labels=False):
    low = text.lower()
    for banned in BANNED[:2]:
        assert banned not in low, where
    scrubbed = low
    if allow_method_labels:
        for phrase in _METHOD_PHRASES:
            scrubbed = scrubbed.replace(phrase, " ")
    words = set(_words(scrubbed))
    for banned in BANNED[2:]:
        assert banned not in words, where


def assert_day(day):
    assert day["schema"] == 1
    assert len(day["date"]) == 10
    assert "generated_at" in day and "season" in day
    assert day["status"] in ("pending", "partial", "graded")
    assert day["model"] == "logistic"
    labels = {method["id"]: method["label"] for method in day["methods"]}
    assert [method["id"] for method in day["methods"]] == [method["id"] for method in METHODS]
    for method in METHODS:
        assert labels[method["id"]] == method["label"]
        words = set(_words(method["label"]))
        assert "ddh" not in words and "hch" not in words
    assert "groups" in day
    for group in day["groups"]:
        for key in ("id", "status", "players", "pick", "hit", "top3_hits", "random", "n", "scorers", "method_picks"):
            assert key in group
        for method_id in ("model", "ddh_style", "hch_style"):
            assert method_id in group["method_picks"]
        probs = []
        for player in group["players"]:
            for key in ("pid", "name", "team", "opp", "home", "position", "probability", "pick", "scored", "goals"):
                assert key in player
            assert "model" in player["probability"]
            assert "ddh_style" in player["probability"]
            assert "hch_style" in player["rank"]
            assert isinstance(player["probability"]["model"], float) or isinstance(player["probability"]["model"], int)
            probs.append(player["probability"]["model"])
            assert_public(player)
        assert probs == sorted(probs, reverse=True)
    assert_public(day)


def assert_season(season):
    assert season["schema"] == 1
    assert season["method"] == "model"
    assert season["summary"] == season["by_method"]["model"]["summary"]
    for method_id in ("model", "ddh_style", "hch_style"):
        assert season["by_method"][method_id]["summary"]["picks"] > 0
    charts = season["charts"]
    assert charts["overall"]["dates"]
    assert [series["id"] for series in charts["overall"]["series"]] == ["model", "ddh_style", "hch_style"]
    assert [series["label"] for series in charts["overall"]["series"]] == [method["label"] for method in METHODS]
    assert len(charts["groups"]) == 3
    for group in charts["groups"]:
        assert group["label"].startswith("Pick ")
        assert len(group["series"]) == 3
        assert len(group["random_rate"]) == len(group["dates"])
    summary = season["summary"]
    for key in ("days", "picks", "hits", "hit_rate", "top3_hits", "top3_slots", "top3_rate", "random_baseline"):
        assert key in summary
    for day in season["days"]:
        for key in (
            "date", "picks", "hits", "hit_rate", "top3_hits", "random",
            "running_hit_rate", "running_top3_hits", "running_random", "groups",
        ):
            assert key in day
        for group in day["groups"]:
            for key in ("id", "pick", "probability", "hit", "top3_hits", "random"):
                assert key in group
    assert_public(season)


def assert_index(index):
    assert index["schema"] == 1
    assert "today" in index and "days" in index
    for row in index["days"]:
        for key in ("date", "status", "groups", "picks", "hits"):
            assert key in row
    assert_public(index)


def test_page_sources_do_not_name_other_sites():
    for name in ("app.js", "mix.js", "style.css"):
        text = open(os.path.join(WEB, name)).read()
        assert_clean(text, name)
        for host in ("nhle.com", "rbi.digital", "api."):
            assert host not in text, name
        assert 'fetch("http' not in text and "fetch('http" not in text
    html = open(os.path.join(WEB, "index.html")).read()
    # The footnote may name the other sites. Method titles stay descriptive.
    footnote = html.lower().replace("datadrivenhockey", " ").replace("hockeychallengehelper", " ")
    assert_clean(footnote, "index.html")
    assert "datadrivenhockey" in html.lower()
    assert "hockeychallengehelper" in html.lower()
    for host in ("nhle.com", "rbi.digital", "api."):
        assert host not in html
    for method in METHODS:
        words = set(_words(method["label"]))
        assert "ddh" not in words and "hch" not in words


def test_fixture_site_schema():
    publish = os.path.join(ROOT, "tests", "fixtures", "publish")
    assert os.path.isdir(publish), "run tests/build_fixture_site.py"
    today = json.load(open(os.path.join(publish, "today.json")))
    season = json.load(open(os.path.join(publish, "season.json")))
    index = json.load(open(os.path.join(publish, "days", "index.json")))
    assert_day(today)
    assert_season(season)
    assert_index(index)
    assert today["status"] == "pending"
    graded = 0
    for name in os.listdir(os.path.join(publish, "days")):
        if name == "index.json" or not name.endswith(".json"):
            continue
        day = json.load(open(os.path.join(publish, "days", name)))
        assert_day(day)
        assert_clean(json.dumps(day), name, allow_method_labels=True)
        if day["status"] == "graded":
            graded += 1
            for group in day["groups"]:
                assert group["scorers"] is not None
    assert graded >= 3
    assert_clean(json.dumps(today), "today", allow_method_labels=True)
    assert_clean(json.dumps(season), "season", allow_method_labels=True)
