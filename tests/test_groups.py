"""Groups source: fixture parse, GraphQL adapter, secrets stay out of errors."""
import json
import os
import stat

import pytest

from job.groups import (
    COGNITO_URL,
    GATEWAY_URL,
    FileGroupsSource,
    GroupsSourceError,
    TimsGroupsSource,
    assert_secret_location,
    load_env_file,
    parse_picks,
    unwrap_hockey_players,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "tims_picks.json")
HOCKEY = os.path.join(HERE, "fixtures", "tims_hockey_players.json")
ROSTERS = os.path.join(HERE, "fixtures", "nhl_rosters.json")
CANARY = "canary-secret-value-do-not-leak"
ID_TOKEN = "id-token-not-the-refresh"
ROTATED = "rotated-refresh-token"


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
    _env(
        path,
        "# comment\n\nTIMS_CLIENT_ID=\"app-client\"\nTIMS_REFRESH_TOKEN='%s'\n" % CANARY,
    )
    creds = load_env_file(str(path))
    assert creds["TIMS_CLIENT_ID"] == "app-client"
    assert creds["TIMS_REFRESH_TOKEN"] == CANARY


def _rosters():
    return json.load(open(ROSTERS))


def _roster_get(url):
    abbr = url.rstrip("/").split("/")[-2]
    payload = _rosters().get(abbr)
    if payload is None:
        raise AssertionError(url)
    return payload


def _env_creds(path, refresh=CANARY):
    _env(
        path,
        "\n".join([
            "# tims",
            "TIMS_CLIENT_ID=app-client",
            "TIMS_USER_POOL_ID=us-east-1_example",
            "TIMS_COGNITO_ID=us-east-1:subject",
            "TIMS_REFRESH_TOKEN=%s" % refresh,
            "TIMS_USER_AGENT=fixture-agent",
            "",
        ]),
    )


def test_hockey_players_fixture_resolves_by_team_and_jersey(tmp_path):
    env_path = tmp_path / "tims.env"
    _env_creds(env_path)
    calls = []
    hockey = json.load(open(HOCKEY))

    def transport(method, url, body, headers):
        calls.append((method, url, body, headers))
        blob = json.dumps(body)
        assert CANARY not in url
        if url == COGNITO_URL:
            assert method == "POST"
            assert body["AuthFlow"] == "REFRESH_TOKEN_AUTH"
            assert body["AuthParameters"]["REFRESH_TOKEN"] == CANARY
            return 200, {
                "AuthenticationResult": {
                    "IdToken": ID_TOKEN,
                    "ExpiresIn": 3600,
                    "RefreshToken": ROTATED,
                }
            }
        if url == GATEWAY_URL:
            assert method == "POST"
            assert body["operationName"] == "HockeyPlayers"
            assert "SubmitHockeyPicks" not in blob
            assert "UpdateHockeyUser" not in blob
            assert CANARY not in blob
            assert CANARY not in json.dumps(headers)
            assert headers["authorization"] == "Bearer " + ID_TOKEN
            assert headers["x-cognito-id"] == "us-east-1:subject"
            return 200, hockey
        raise AssertionError(url)

    source = TimsGroupsSource(
        env_path=str(env_path), transport=transport, roster_get=_roster_get
    )
    doc = source.fetch("2026-11-14")
    assert [call[1] for call in calls] == [COGNITO_URL, GATEWAY_URL]
    assert [g["id"] for g in doc["groups"]] == [1, 2, 3]
    by_name = {}
    for group in doc["groups"]:
        for player in group["players"]:
            by_name[player["fullName"]] = player
    assert by_name["Connor McDavid"]["nhlPlayerId"] == 8478402
    assert by_name["Connor McDavid"]["team"] == "EDM"
    assert by_name["Connor McDavid"]["opponent"] == "SJS"
    assert by_name["Connor McDavid"]["homeAway"] == "HOME"
    # Tims says SJ; the roster request and the published team use SJS.
    assert by_name["Mitch Marner"]["nhlPlayerId"] == 8478483
    assert by_name["Mitch Marner"]["team"] == "SJS"
    assert by_name["Mitch Marner"]["homeAway"] == "AWAY"
    assert by_name["Mitch Marner"]["position"] == "R"
    assert by_name["Jack Hughes"]["team"] == "NJD"
    assert by_name["Jack Hughes"]["opponent"] == "TBL"
    assert by_name["Victor Hedman"]["position"] == "D"
    assert by_name["Victor Hedman"]["homeAway"] == "AWAY"
    dumped = json.dumps(doc)
    assert CANARY not in dumped
    assert ROTATED not in dumped
    assert ID_TOKEN not in dumped
    assert "example.invalid" not in dumped
    saved = env_path.read_text()
    assert "TIMS_REFRESH_TOKEN=%s" % ROTATED in saved
    assert CANARY not in saved
    assert "TIMS_CLIENT_ID=app-client" in saved
    assert "# tims" in saved
    assert stat.S_IMODE(os.stat(str(env_path)).st_mode) == 0o600


def test_string_encoded_hockey_players_data():
    payload = json.load(open(HOCKEY))
    data = payload["data"]["me"]["hockeyPlayers"]["data"]
    payload["data"]["me"]["hockeyPlayers"]["data"] = json.dumps(data)
    assert unwrap_hockey_players(payload)["contestId"] == "contest-fixture"


def test_revoked_refresh_token_does_not_query_or_echo_secret(tmp_path):
    env_path = tmp_path / "tims.env"
    _env_creds(env_path)
    calls = []

    def transport(method, url, body, headers):
        calls.append(url)
        return 400, {"__type": "NotAuthorizedException", "message": "Refresh Token has been revoked"}

    source = TimsGroupsSource(
        env_path=str(env_path), transport=transport, roster_get=_roster_get
    )
    with pytest.raises(GroupsSourceError) as exc:
        source.fetch("2026-11-14")
    message = str(exc.value)
    assert "rejected" in message
    assert "left unchanged" in message
    assert CANARY not in message
    assert calls == [COGNITO_URL]
    assert CANARY in env_path.read_text()


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


def test_adapter_does_not_sign_in_or_use_the_old_host():
    path = os.path.join(os.path.dirname(HERE), "job", "groups.py")
    text = open(path).read()
    assert "px-api.rbi.digital" not in text
    assert "SignInJWT" not in text
    assert "ValidateAuthJwt" not in text
    assert "RespondToAuthChallenge" not in text
    assert "REFRESH_TOKEN_AUTH" in text
    assert "HockeyPlayers" in text
