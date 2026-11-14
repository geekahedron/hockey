"""Pick-group sources for the daily job.

The scorer only sees a normalized document:

    {"date": "YYYY-MM-DD", "groups": [{"id": 1, "players": [...]}]}

Each player has nhlPlayerId, fullName, team, opponent, homeAway
("HOME" or "AWAY"), position, and unavailable.

TimsGroupsSource is the read-only adapter for
https://px-api.rbi.digital/hockeyprod/picks. Credentials are read from
the file named by TIMS_ENV, which must sit outside the repo and the
web root. The authenticated GET itself is a TODO: a fetcher is being
written elsewhere. Until that lands, pass --groups to FileGroupsSource.

This module never submits a pick. The only HTTP method it will use is GET.
"""
import json
import os
import urllib.request

# Exact read-only URL. Do not add a submit endpoint beside it.
PICKS_URL = "https://px-api.rbi.digital/hockeyprod/picks"

# The live request will need one of these. Values are never logged.
_CRED_KEYS = ("TIMS_BEARER", "TIMS_COOKIE")


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


class TimsGroupsSource(GroupsSource):
    """Read-only adapter. Does not submit picks.

    ``transport``, when set, is ``transport(method, url) -> (status, payload)``
    and is how tests supply a fixture body. Production leaves it None until
    the fetcher below is filled in.
    """

    def __init__(self, env_path=None, transport=None, publish_dir=None):
        if env_path is None:
            env_path = os.environ.get("TIMS_ENV")
        self.env_path = env_path
        self.transport = transport
        self.publish_dir = publish_dir

    def fetch(self, date):
        assert_secret_location(self.env_path, self.publish_dir)
        creds = load_env_file(self.env_path)
        payload = self._request(creds)
        return parse_picks(payload, date)

    def _request(self, creds):
        """GET the day's groups. Read-only.

        TODO: the authenticated client is being written elsewhere. When it
        lands, send ``build_get_request(creds)`` and return the JSON object.
        Add the auth header from
        ``creds`` inside ``build_get_request``. Do not log ``creds``. Do not
        call any URL other than PICKS_URL. Do not POST, PUT, PATCH, or
        otherwise submit a pick.
        """
        request = build_get_request(creds)
        if request.get_method() != "GET" or request.get_full_url() != PICKS_URL:
            raise GroupsSourceError("refusing a picks request that is not a GET of the picks URL")
        if request.data:
            raise GroupsSourceError("refusing to send a pick body")
        if self.transport is None:
            raise GroupsSourceError(
                "TODO: GET the picks URL with credentials from TIMS_ENV. "
                "The fetcher is not wired yet. Use --groups FILE until it is."
            )
        # Tests inject a transport. Credential values are not passed out.
        result = self.transport(request.get_method(), request.get_full_url())
        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise GroupsSourceError("picks transport returned an unexpected result")
        status, payload = result
        if status != 200 or not isinstance(payload, dict):
            raise GroupsSourceError("Tims picks GET failed (status %s)" % status)
        return payload


def build_get_request(creds):
    """A body-less GET for the picks URL.

    TODO: set the auth header from ``creds`` (TIMS_BEARER or TIMS_COOKIE)
    once the fetcher specifies the scheme. Leave the method as GET.
    """
    if not creds or not any(creds.get(key) for key in _CRED_KEYS):
        raise GroupsSourceError("TIMS_ENV must define TIMS_BEARER or TIMS_COOKIE")
    return urllib.request.Request(
        PICKS_URL,
        data=None,
        method="GET",
        headers={"Accept": "application/json"},
    )
