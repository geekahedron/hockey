"""Pick-group sources for the daily job.

The scorer only sees a normalized document:

    {"date": "YYYY-MM-DD", "groups": [{"id": 1, "players": [...]}]}

Each player has nhlPlayerId, fullName, team, opponent, homeAway
("HOME" or "AWAY"), position, and unavailable.

TimsGroupsSource reads the three daily sets from the RBI GraphQL gateway
(query HockeyPlayers). Credentials come only from the file named by
TIMS_ENV, outside the repo and the web root. A refreshed Cognito refresh
token is written back to that same file. Players are matched to NHL ids
by team abbreviation and jersey number.

This module never submits a pick. It does not start a magic-link sign-in.
If the refresh token is rejected, fetch raises and the caller leaves the
already published JSON in place.
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request
import uuid

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9 has zoneinfo
    ZoneInfo = None

# Read-only players query. Do not add a pick-submission operation beside it.
GATEWAY_URL = "https://use1-prod-th-gateway.rbictg.com/graphql"
COGNITO_URL = "https://cognito-idp.us-east-1.amazonaws.com/"
HOCKEY_PLAYERS_QUERY = (
    "query HockeyPlayers($input: HockeyMockInput) {\n"
    "  me {\n"
    "    hockeyPlayers(input: $input) { code data }\n"
    "  }\n"
    "}"
)
_REQUIRED_KEYS = ("TIMS_CLIENT_ID", "TIMS_REFRESH_TOKEN", "TIMS_COGNITO_ID")
# Tims abbreviations that differ from the NHL scoreboard.
_TIMS_TO_NHL = {"NJ": "NJD", "TB": "TBL", "SJ": "SJS", "LA": "LAK"}
# Names that must never be the GraphQL operation. Checked before any send.
_WRITE_OPERATIONS = ("SubmitHockeyPicks", "UpdateHockeyUser", "UpdateHockeyReminders")


class GroupsSourceError(Exception):
    """A groups document could not be loaded. Messages must not contain secrets."""


class GroupsSource(object):
    """Interface. fetch(date) returns the normalized document for that date."""

    def fetch(self, date):
        raise NotImplementedError


def load_env_file(path):
    """Parse a KEY=VALUE file. Comments and blank lines are ignored.

    The returned dict is for the request builder only. Callers must not
    write it to the publish directory, the web root, or a log line.
    """
    if not path:
        raise GroupsSourceError(
            "Set TIMS_ENV to the secrets file (outside the repo and the web root)."
        )
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise GroupsSourceError("TIMS_ENV file not found at %s" % path)
    creds = {}
    with open(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                creds[key] = value
    return creds


def assert_secret_location(path, publish_dir=None):
    """Refuse a secrets file that lives where the web server could serve it."""
    if not path:
        return
    full = os.path.abspath(os.path.expanduser(path))
    parts = set(full.split(os.sep))
    if "public_html" in parts:
        raise GroupsSourceError("TIMS_ENV must not live under the web root")
    if publish_dir:
        pub = os.path.abspath(publish_dir)
        if full == pub or full.startswith(pub + os.sep):
            raise GroupsSourceError("TIMS_ENV must not live in the publish directory")


def _as_date(date):
    return date.isoformat() if hasattr(date, "isoformat") else str(date)


def _home_away(player):
    if player.get("homeAway") in ("HOME", "AWAY"):
        return player["homeAway"]
    if "home" in player:
        return "HOME" if player["home"] in (1, True, "HOME", "home") else "AWAY"
    return None


def _one_player(raw):
    if not isinstance(raw, dict):
        raise GroupsSourceError("a player entry was not an object")
    pid = raw.get("nhlPlayerId")
    if pid is None:
        pid = raw.get("nhlId")
    if pid is None:
        pid = raw.get("playerId")
    if pid is None:
        raise GroupsSourceError("a player is missing nhlPlayerId")
    first = raw.get("firstName") or ""
    last = raw.get("lastName") or ""
    name = raw.get("fullName") or raw.get("name") or (first + " " + last).strip()
    team = raw.get("team") or raw.get("teamAbbrev") or raw.get("teamAbbrevation")
    opponent = raw.get("opponent") or raw.get("opponentTeam") or raw.get("opponentAbbrev")
    unavailable = bool(raw.get("unavailable") or raw.get("scratched") or raw.get("injured"))
    return {
        "nhlPlayerId": int(pid),
        "fullName": name or ("Player %s" % pid),
        "team": team,
        "opponent": opponent,
        "homeAway": _home_away(raw),
        "position": raw.get("position") or "F",
        "unavailable": unavailable,
    }


def _one_group(raw, index):
    if not isinstance(raw, dict):
        raise GroupsSourceError("a group entry was not an object")
    gid = raw.get("id", raw.get("groupNumber", raw.get("group", index)))
    players = raw.get("players") or []
    if not isinstance(players, list):
        raise GroupsSourceError("group %s players was not a list" % gid)
    return {"id": int(gid), "players": [_one_player(p) for p in players]}


def parse_picks(payload, date):
    """Map a Tims picks body, or an already-normalized file, to the scorer's shape.

    Accepted group lists, in order: ``pickGroups`` (Tims fixture), ``groups``
    (normalized), ``playerLists`` (same player objects, local files only).

    TODO: when the live fetcher lands, confirm these field names against a
    real response and adjust only this function. Keep the normalized output.
    """
    if not isinstance(payload, dict):
        raise GroupsSourceError("picks payload was not an object")
    for key in payload:
        if str(key).lower() in ("authorization", "cookie", "token", "tims_bearer", "password", "secret"):
            raise GroupsSourceError("picks payload contained a secret field")
    raw_groups = None
    for key in ("pickGroups", "groups", "playerLists"):
        if key in payload and payload[key] is not None:
            raw_groups = payload[key]
            break
    if not isinstance(raw_groups, list):
        raise GroupsSourceError("picks payload had no group list")
    wanted = _as_date(date)
    stated = payload.get("date") or payload.get("slateDate")
    if stated:
        stated = str(stated)[:10]
        if stated != wanted:
            raise GroupsSourceError(
                "picks payload is for %s, not %s" % (stated, wanted)
            )
    groups = [_one_group(g, i + 1) for i, g in enumerate(raw_groups)]
    return {"date": wanted, "groups": groups}


class FileGroupsSource(GroupsSource):
    """Normalized JSON, or the same shape parse_picks accepts, from a local file."""

    def __init__(self, path):
        self.path = path

    def fetch(self, date):
        with open(self.path) as handle:
            payload = json.load(handle)
        return parse_picks(payload, date)


def _nhl_abbr(abbr):
    if not abbr:
        return abbr
    return _TIMS_TO_NHL.get(abbr, abbr)


def _position(raw):
    text = (raw or "").strip().upper()
    if text in ("D", "LD", "RD", "DEF", "DEFENSE"):
        return "D"
    if text in ("L", "LW"):
        return "L"
    if text in ("R", "RW"):
        return "R"
    if text == "C":
        return "C"
    if text == "G":
        return "G"
    return "F"


def _jersey(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _toronto_date(iso):
    text = str(iso).replace("Z", "+00:00")
    stamp = dt.datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    if ZoneInfo is None:
        return stamp.date()
    return stamp.astimezone(ZoneInfo("America/Toronto")).date()


def _require_creds(creds):
    missing = [key for key in _REQUIRED_KEYS if not creds.get(key)]
    if missing:
        raise GroupsSourceError(
            "TIMS_ENV must define %s" % ", ".join(missing)
        )


def _revoked(status, body):
    if isinstance(body, dict):
        kind = str(body.get("__type") or "")
        message = str(body.get("message") or "")
        if "NotAuthorized" in kind or "NotAuthorized" in message:
            return True
        lowered = message.lower()
        if "revok" in lowered or "expired" in lowered:
            return True
    return status in (401, 403)


def _leave_published(reason):
    raise GroupsSourceError(
        "%s Published JSON was left unchanged." % reason
    )


def _assert_read_only(operation, query):
    if operation != "HockeyPlayers":
        _leave_published("Refusing a Tims request that is not the players query.")
    text = query or ""
    for name in _WRITE_OPERATIONS:
        if name in text or name == operation:
            _leave_published("Refusing to submit a Tims pick.")


def unwrap_hockey_players(payload):
    """Return the hockeyPlayers.data object. It is sometimes a JSON string."""
    if not isinstance(payload, dict):
        _leave_published("HockeyPlayers response was not JSON.")
    if payload.get("errors"):
        _leave_published("HockeyPlayers query was rejected.")
    try:
        data = payload["data"]["me"]["hockeyPlayers"]["data"]
    except (KeyError, TypeError):
        _leave_published("HockeyPlayers response had no player sets.")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            _leave_published("HockeyPlayers data could not be read.")
    if not isinstance(data, dict):
        _leave_published("HockeyPlayers response had no player sets.")
    return data


def _game_index(games):
    """team id -> (nhl abbr, opponent nhl abbr, home, tims abbr)."""
    index = {}
    dates = []
    for game in games or []:
        teams = game.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        if game.get("startTime"):
            dates.append(_toronto_date(game["startTime"]))
        home_ab = _nhl_abbr(home.get("abbr"))
        away_ab = _nhl_abbr(away.get("abbr"))
        if home.get("id"):
            index[home["id"]] = (home_ab, away_ab, True, home.get("abbr"))
        if away.get("id"):
            index[away["id"]] = (away_ab, home_ab, False, away.get("abbr"))
    return index, dates


def _roster_map(tims_abbrs, roster_get):
    """(tims abbr, jersey) -> nhl player id. Fetches the NHL roster for the mapped team."""
    found = {}
    for abbr in sorted(tims_abbrs):
        nhl_abbr = _nhl_abbr(abbr)
        url = "https://api-web.nhle.com/v1/roster/%s/current" % nhl_abbr
        try:
            payload = roster_get(url)
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            continue
        for group in ("forwards", "defensemen", "goalies"):
            for player in payload.get(group) or []:
                number = _jersey(player.get("sweaterNumber"))
                pid = player.get("id")
                if number is None or pid is None:
                    continue
                found[(abbr, number)] = int(pid)
    return found


def hockey_players_to_groups(data, roster_get, date):
    """Map a HockeyPlayers data object to the scorer's normalized document."""
    wanted = _as_date(date)
    index, dates = _game_index(data.get("games"))
    if not dates:
        _leave_published("HockeyPlayers response had no games.")
    slate = sorted(set(item.isoformat() for item in dates))
    if slate != [wanted]:
        _leave_published(
            "HockeyPlayers slate is for %s, not %s." % (", ".join(slate), wanted)
        )
    tims_abbrs = set()
    for game in data.get("games") or []:
        teams = game.get("teams") or {}
        for side in ("home", "away"):
            abbr = (teams.get(side) or {}).get("abbr")
            if abbr:
                tims_abbrs.add(abbr)
    roster = _roster_map(tims_abbrs, roster_get)
    sets = data.get("sets") or []
    if not sets:
        _leave_published("HockeyPlayers response had no player sets.")
    groups = []
    missing = []
    for position, raw_set in enumerate(sets, 1):
        raw_players = raw_set.get("players") if isinstance(raw_set, dict) else raw_set
        players = []
        if not raw_players:
            missing.append("group %s is empty" % position)
        for raw in raw_players or []:
            team_id = raw.get("teamId")
            placed = index.get(team_id)
            number = _jersey(raw.get("number"))
            name = ("%s %s" % (raw.get("firstName") or "", raw.get("lastName") or "")).strip()
            if not placed or number is None:
                missing.append(name or "unknown")
                continue
            team, opponent, home, tims_abbr = placed
            pid = roster.get((tims_abbr, number))
            if pid is None:
                missing.append("%s (%s #%s)" % (name or "unknown", team, number))
                continue
            players.append({
                "nhlPlayerId": pid,
                "fullName": name or ("Player %s" % pid),
                "team": team,
                "opponent": opponent,
                "homeAway": "HOME" if home else "AWAY",
                "position": _position(raw.get("position")),
                "unavailable": False,
            })
        groups.append({"id": position, "players": players})
    if missing:
        _leave_published(
            "Could not match %s to an NHL id." % "; ".join(missing)
        )
    return {"date": wanted, "groups": groups}


def _replace_env_value(path, key, value):
    """Rewrite one key in the secrets file. Mode 0600. Value is never logged."""
    if "\n" in value or "\r" in value:
        _leave_published("Refusing to store a malformed refreshed token.")
    assert_secret_location(path)
    with open(path) as handle:
        lines = handle.readlines()
    found = False
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            current = stripped.split("=", 1)[0].strip()
            if current == key:
                out.append("%s=%s\n" % (key, value))
                found = True
                continue
        out.append(line if line.endswith("\n") else line + "\n")
    if not found:
        out.append("%s=%s\n" % (key, value))
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.writelines(out)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _default_transport(method, url, body, headers):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    if not raw:
        return status, {}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, {}


def _default_roster_get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


class TimsGroupsSource(GroupsSource):
    """Read-only HockeyPlayers adapter. Does not submit picks.

    ``transport(method, url, body, headers) -> (status, payload)`` and
    ``roster_get(url) -> roster dict`` are injected by tests. Production
    uses urllib. Credential values are never logged.
    """

    def __init__(self, env_path=None, transport=None, roster_get=None, publish_dir=None):
        if env_path is None:
            env_path = os.environ.get("TIMS_ENV")
        self.env_path = env_path
        self.transport = transport or _default_transport
        self.roster_get = roster_get or _default_roster_get
        self.publish_dir = publish_dir

    def fetch(self, date):
        assert_secret_location(self.env_path, self.publish_dir)
        creds = load_env_file(self.env_path)
        _require_creds(creds)
        id_token, rotated = self._refresh(creds)
        if rotated and rotated != creds.get("TIMS_REFRESH_TOKEN"):
            _replace_env_value(self.env_path, "TIMS_REFRESH_TOKEN", rotated)
        payload = self._query(id_token, creds["TIMS_COGNITO_ID"], creds.get("TIMS_USER_AGENT"))
        data = unwrap_hockey_players(payload)
        return hockey_players_to_groups(data, self.roster_get, date)

    def _refresh(self, creds):
        body = {
            "ClientId": creds["TIMS_CLIENT_ID"],
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "AuthParameters": {
                "REFRESH_TOKEN": creds["TIMS_REFRESH_TOKEN"],
                "DEVICE_KEY": None,
            },
        }
        headers = {
            "content-type": "application/x-amz-json-1.1",
            "x-amz-target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "x-amz-user-agent": "aws-amplify/5.0.4 js",
        }
        status, payload = self.transport("POST", COGNITO_URL, body, headers)
        if not isinstance(payload, dict) or _revoked(status, payload):
            _leave_published("Tims refresh token was rejected.")
        result = payload.get("AuthenticationResult") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(result, dict) or not result.get("IdToken"):
            _leave_published("Tims token refresh failed.")
        return result["IdToken"], result.get("RefreshToken")

    def _query(self, id_token, cognito_id, user_agent):
        _assert_read_only("HockeyPlayers", HOCKEY_PLAYERS_QUERY)
        body = {
            "operationName": "HockeyPlayers",
            "query": HOCKEY_PLAYERS_QUERY,
            "variables": {"input": None},
        }
        headers = {
            "content-type": "application/json",
            "accept": "*/*",
            "authorization": "Bearer " + id_token,
            "x-cognito-id": cognito_id,
            "apollographql-client-name": "wl-web",
            "apollographql-client-version": "0000000",
            "x-ui-platform": "web",
            "x-ui-region": "CA",
            "x-ui-language": "en",
            "x-user-datetime": dt.datetime.now().astimezone().isoformat(),
            "X-Session-Id": str(uuid.uuid4()),
            "origin": "https://hockey-challenge.rbi.digital",
            "referer": "https://hockey-challenge.rbi.digital/",
            "user-agent": user_agent or "Mozilla/5.0",
        }
        status, payload = self.transport("POST", GATEWAY_URL, body, headers)
        if status != 200 or not isinstance(payload, dict):
            if _revoked(status, payload if isinstance(payload, dict) else {}):
                _leave_published("Tims refresh token was rejected.")
            _leave_published("HockeyPlayers query failed.")
        return payload
