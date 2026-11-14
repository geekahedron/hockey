"""Groups source: fixture parse, secrets stay out of errors, GET only."""
import json
import os

import pytest

from job.groups import (
    PICKS_URL,
    FileGroupsSource,
    GroupsSourceError,
    TimsGroupsSource,
    assert_secret_location,
    build_get_request,
    load_env_file,
    parse_picks,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "tims_picks.json")
CANARY = "canary-secret-value-do-not-leak"


def _env(path, body):
    with open(path, "w") as handle:
        handle.write(body)


def test_parse_tims_fixture():
    payload = json.load(open(FIXTURE))
    doc = parse_picks(payload, "2026-11-14")
    assert doc["date"] == "2026-11-14"
    assert [g["id"] for g in doc["groups"]] == [1, 2, 3]
    first = doc["groups"][0]["players"]
    assert first[0]["fullName"] == "Connor McDavid"
    assert first[0]["team"] == "EDM"
    assert first[0]["opponent"] == "SJS"
    assert first[0]["homeAway"] == "HOME"
    assert first[0]["unavailable"] is False
    assert first[1]["fullName"] == "Leon Draisaitl"
    assert first[1]["unavailable"] is True
    assert doc["groups"][1]["players"][0]["homeAway"] == "AWAY"
    assert doc["groups"][2]["players"][0]["position"] == "D"
    assert CANARY not in json.dumps(doc)


def test_file_source_reads_fixture():
    doc = FileGroupsSource(FIXTURE).fetch("2026-11-14")
    assert len(doc["groups"]) == 3


def test_rejects_wrong_date_and_secret_field():
    payload = json.load(open(FIXTURE))
    with pytest.raises(GroupsSourceError) as bad_date:
        parse_picks(payload, "2026-11-01")
    assert CANARY not in str(bad_date.value)
    payload["token"] = CANARY
    with pytest.raises(GroupsSourceError) as secret:
        parse_picks(payload, "2026-11-14")
    assert "secret" in str(secret.value).lower()
    assert CANARY not in str(secret.value)


def test_env_file_roundtrip(tmp_path):
    path = tmp_path / "tims.env"
    _env(path, "# comment\n\nTIMS_BEARER=\"%s\"\nTIMS_COOKIE='abc'\n" % CANARY)
    creds = load_env_file(str(path))
    assert creds["TIMS_BEARER"] == CANARY
    assert creds["TIMS_COOKIE"] == "abc"


def test_tims_source_get_only_and_hides_secret(tmp_path):
    env_path = tmp_path / "tims.env"
    _env(env_path, "TIMS_BEARER=%s\n" % CANARY)
    calls = []

    def transport(method, url):
        calls.append((method, url))
        assert CANARY not in method and CANARY not in url
        return 200, json.load(open(FIXTURE))

    source = TimsGroupsSource(env_path=str(env_path), transport=transport)
    doc = source.fetch("2026-11-14")
    assert calls == [("GET", PICKS_URL)]
    assert CANARY not in json.dumps(doc)

    request = build_get_request({"TIMS_BEARER": CANARY})
    assert request.get_method() == "GET"
    assert request.get_full_url() == PICKS_URL
    assert request.data is None
    joined = " ".join("%s=%s" % pair for pair in request.header_items())
    assert "POST" not in joined
    assert CANARY not in joined


def test_unwired_fetcher_does_not_echo_secret(tmp_path):
    env_path = tmp_path / "tims.env"
    _env(env_path, "TIMS_BEARER=%s\n" % CANARY)
    source = TimsGroupsSource(env_path=str(env_path))
    with pytest.raises(GroupsSourceError) as exc:
        source.fetch("2026-11-14")
    assert "TODO" in str(exc.value)
    assert CANARY not in str(exc.value)


def test_secret_path_rejected(tmp_path):
    publish = tmp_path / "publish"
    publish.mkdir()
    env_path = publish / "tims.env"
    _env(env_path, "TIMS_BEARER=%s\n" % CANARY)
    with pytest.raises(GroupsSourceError) as exc:
        TimsGroupsSource(env_path=str(env_path), publish_dir=str(publish)).fetch("2026-11-14")
    assert CANARY not in str(exc.value)
    web = tmp_path / "public_html" / "tools" / "hockey"
    web.mkdir(parents=True)
    leaked = web / "tims.env"
    _env(leaked, "TIMS_BEARER=%s\n" % CANARY)
    with pytest.raises(GroupsSourceError) as web_exc:
        assert_secret_location(str(leaked))
    assert "web root" in str(web_exc.value)
    assert CANARY not in str(web_exc.value)


def test_groups_module_has_no_live_http_call():
    path = os.path.join(os.path.dirname(HERE), "job", "groups.py")
    text = open(path).read()
    assert "urlopen" not in text
    assert "requests." not in text
    assert "method=\"GET\"" in text or "method='GET'" in text
