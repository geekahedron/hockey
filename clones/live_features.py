"""Fetch clone features for one game day from the public NHL APIs.

Python 3.9+, standard library only. No boxscore archive is required.

Uses api.nhle.com/stats/rest (season totals filtered to gameDate <= the day
before the slate, so a past morning can be rebuilt) and api-web.nhle.com
(schedule for home, opponent, and back-to-backs).
"""
import json
import time
import urllib.parse
import urllib.request
import datetime as dt

UA = {"User-Agent": "Mozilla/5.0 (geekahedron hockey tool)"}
STATS = "https://api.nhle.com/stats/rest/en"
WEB = "https://api-web.nhle.com/v1"


class FeatureError(Exception):
    pass


def get(url, tries=3):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.loads(response.read())
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 + 2 * attempt)
    return None


def season_start_year(date):
    year, month = int(date[:4]), int(date[5:7])
    return year if month >= 8 else year - 1


def _report(kind, report, cayenne, fetch):
    query = urllib.parse.urlencode({
        "isAggregate": "true",
        "isGame": "true",
        "limit": -1,
        "start": 0,
        "cayenneExp": cayenne,
    })
    payload = fetch("%s/%s/%s?%s" % (STATS, kind, report, query))
    if not isinstance(payload, dict) or "data" not in payload:
        raise FeatureError("stats feed returned no data")
    return payload["data"]


def _range(year, end=None):
    """Regular-season window for the season that starts in ``year``.

    ``end`` caps the window (inclusive). The morning of a slate uses the
    previous calendar day so that night's games are not in the totals.
    """
    cap = end or ("%d-07-31" % (year + 1))
    return 'gameDate>="%d-08-01" and gameDate<="%s" and gameTypeId=2' % (year, cap)


def skater_totals(year, end=None, cache=None, fetch=None):
    """Map player id to gp, goals, shots, toi minutes, pp toi, pp goals, position.

    Finished seasons are cacheable. The current season is not: it is always
    read through ``end``.
    """
    fetch = fetch or get
    key = ("%d" % year) if end is None else None
    if cache is not None and key and key in cache:
        return {int(pid): row for pid, row in cache[key].items()}
    summary = _report("skater", "summary", _range(year, end), fetch)
    toi_rows = _report("skater", "timeonice", _range(year, end), fetch)
    toi = {row["playerId"]: row for row in toi_rows}
    out = {}
    for row in summary:
        ice = toi.get(row["playerId"], {})
        games = row.get("gamesPlayed") or 0
        out[row["playerId"]] = {
            "gp": games,
            "g": row.get("goals") or 0,
            "sog": row.get("shots") or 0,
            "toi": (row.get("timeOnIcePerGame") or 0) * games / 60.0,
            "pptoi": (ice.get("ppTimeOnIce") or 0) / 60.0,
            "ppg": row.get("ppGoals") or 0,
            "pos": row.get("positionCode"),
            "name": row.get("skaterFullName"),
        }
    if cache is not None and key:
        cache[key] = out
    return out


def team_ga(year, end=None, fetch=None):
    """Map team abbrev to (goals against, games) from per-game team rows.

    Each game has two rows. A team's abbrev is the other row's opponent.
    """
    fetch = fetch or get
    query = urllib.parse.urlencode({
        "isAggregate": "false",
        "isGame": "true",
        "limit": -1,
        "start": 0,
        "cayenneExp": _range(year, end),
    })
    payload = fetch("%s/team/summary?%s" % (STATS, query))
    if not isinstance(payload, dict) or "data" not in payload:
        raise FeatureError("team stats feed returned no data")
    by_game = {}
    for row in payload["data"]:
        by_game.setdefault(row["gameId"], []).append(row)
    out = {}
    for rows in by_game.values():
        if len(rows) != 2:
            continue
        for me, other in ((rows[0], rows[1]), (rows[1], rows[0])):
            abbrev = other["opponentTeamAbbrev"]
            against, games = out.get(abbrev, (0, 0))
            out[abbrev] = (against + (me.get("goalsAgainst") or 0), games + 1)
    return out


def schedule(date, fetch=None):
    """Map team abbrev to opponent, home flag, and start time for one date."""
    fetch = fetch or get
    payload = fetch("%s/score/%s" % (WEB, date))
    if not isinstance(payload, dict):
        raise FeatureError("score feed returned no document")
    out = {}
    for game in payload.get("games") or []:
        away = game["awayTeam"]["abbrev"]
        home = game["homeTeam"]["abbrev"]
        out[home] = {"opp": away, "home": 1, "start": game.get("startTimeUTC")}
        out[away] = {"opp": home, "home": 0, "start": game.get("startTimeUTC")}
    return out


def build(date, players, cache=None, fetch=None):
    """Return feature dicts for ``players`` (each needs pid and team).

    Opponent and home are taken from the player when present, otherwise from
    the NHL schedule. Pass ``fetch(url) -> dict`` to avoid the network.
    """
    fetch = fetch or get
    year = season_start_year(date)
    yesterday = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    current = skater_totals(year, yesterday, fetch=fetch)
    previous = [skater_totals(year - k, None, cache, fetch=fetch) for k in (1, 2, 3)]
    ga_current = team_ga(year, yesterday, fetch=fetch)
    ga_key = "ga%d" % (year - 1)
    if cache is not None and ga_key in cache:
        ga_previous = cache[ga_key]
    else:
        ga_previous = team_ga(year - 1, None, fetch=fetch)
        if cache is not None:
            cache[ga_key] = ga_previous
    played = sum(games for _against, games in ga_previous.values())
    if played:
        league_ga = sum(against for against, _games in ga_previous.values()) / float(played)
    else:
        league_ga = None
    slate = schedule(date, fetch=fetch)
    played_yesterday = set(schedule(yesterday, fetch=fetch))
    out = []
    for player in players:
        pid = int(player["pid"])
        team = player["team"]
        booked = slate.get(team, {})
        opponent = player.get("opp") or booked.get("opp")
        if player.get("home") is None:
            home = booked.get("home", 0)
        else:
            home = player.get("home")
        row = {
            "pid": pid,
            "date": date,
            "team": team,
            "opp": opponent,
            "home": int(home or 0),
        }
        position = None
        seasons = (("cur", current), ("prev", previous[0]), ("prev2", previous[1]), ("prev3", previous[2]))
        for key, totals in seasons:
            stats = totals.get(pid) or {}
            position = position or stats.get("pos")
            for field in ("gp", "g", "sog", "toi", "pptoi", "ppg"):
                row["%s_%s" % (key, field)] = stats.get(field, 0)
        row["is_d"] = int(position == "D")
        if opponent and opponent in ga_current and ga_current[opponent][1]:
            against, games = ga_current[opponent]
            row["opp_ga_pg"] = against / float(games)
        elif league_ga:
            row["opp_ga_pg"] = league_ga
        if league_ga:
            row["lg_ga_pg"] = league_ga
        row["rest_t"] = 1 if team in played_yesterday else 2
        named = player.get("name")
        if not named:
            named = (current.get(pid) or previous[0].get(pid) or {}).get("name")
        row["name"] = named
        out.append(row)
    return out
