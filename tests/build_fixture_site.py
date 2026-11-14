"""Write tests/fixtures/publish, the sample slate the page screenshots use.

Not part of the daily job. Probabilities here are illustrative so the static
page has something to render; they are not model output.
"""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from job.grade import apply_grade
from job.publish import publish_day
from job.score import METHODS, _pending_group, season_label

# name, team, opponent, home, position
POOLS = [
    [
        ("Connor McDavid", "EDM", "SJS", 1, "C"),
        ("Nathan MacKinnon", "COL", "ANA", 1, "C"),
        ("Auston Matthews", "TOR", "CBJ", 1, "C"),
        ("Kirill Kaprizov", "MIN", "NSH", 1, "L"),
        ("Nikita Kucherov", "TBL", "OTT", 0, "R"),
        ("David Pastrnak", "BOS", "PHI", 1, "R"),
        ("Jason Robertson", "DAL", "STL", 1, "L"),
        ("Sam Reinhart", "FLA", "CAR", 1, "C"),
    ],
    [
        ("Leon Draisaitl", "EDM", "SJS", 1, "C"),
        ("William Nylander", "TOR", "CBJ", 1, "R"),
        ("Mikko Rantanen", "COL", "ANA", 1, "R"),
        ("Brayden Point", "TBL", "OTT", 0, "C"),
        ("Jack Hughes", "NJD", "NYR", 1, "C"),
        ("Matthew Tkachuk", "FLA", "CAR", 1, "R"),
        ("Kyle Connor", "WPG", "VAN", 0, "L"),
        ("Mark Scheifele", "WPG", "VAN", 0, "C"),
    ],
    [
        ("Jack Eichel", "VGK", "SEA", 1, "C"),
        ("Sidney Crosby", "PIT", "BUF", 1, "C"),
        ("Aleksander Barkov", "FLA", "CAR", 1, "C"),
        ("Cale Makar", "COL", "ANA", 1, "D"),
        ("Tim Stützle", "OTT", "TBL", 1, "C"),
        ("Mitch Marner", "TOR", "CBJ", 1, "R"),
        ("Evan Bouchard", "EDM", "SJS", 1, "D"),
        ("Morgan Rielly", "TOR", "CBJ", 1, "D"),
    ],
]


def _scores(day_index, group_index, rank):
    if rank == 0:
        return (day_index * 3 + group_index) % 5 < 2
    if rank == 1:
        return (day_index * 2 + group_index) % 3 == 0
    if rank == 2:
        return (day_index + group_index) % 2 == 0
    if rank == 4:
        return (day_index + 3 * group_index) % 4 == 0
    return False


def _players(day_index, group_index, pool, pin_order=False):
    if pin_order:
        rotated = list(pool)
    else:
        shift = (day_index + group_index) % len(pool)
        rotated = pool[shift:] + pool[:shift]
    top = 0.352 - group_index * 0.035 + (day_index % 5) * 0.006
    rows = []
    for rank, (name, team, opp, home, pos) in enumerate(rotated):
        pid = 8478001 + group_index * 100 + POOLS[group_index].index((name, team, opp, home, pos))
        rows.append({
            "pid": pid,
            "name": name,
            "team": team,
            "opp": opp,
            "home": home,
            "position": pos,
            "probability": {"model": round(max(0.05, top - rank * 0.027), 4)},
            "pick": False,
            "scored": None,
            "goals": None,
        })
    rows.sort(key=lambda row: (-row["probability"]["model"], row["name"], row["pid"]))
    return rows


def _day(when, day_index, pending):
    groups = []
    flat = []
    scorers = set()
    for group_index, pool in enumerate(POOLS):
        players = _players(day_index, group_index, pool, pin_order=pending)
        if not pending:
            for rank, player in enumerate(players):
                if _scores(day_index, group_index, rank):
                    scorers.add(player["pid"])
        groups.append(_pending_group(group_index + 1, players))
        flat.extend(players)
    day = {
        "schema": 1,
        "date": when.isoformat(),
        "status": "pending",
        "generated_at": "2026-11-14T10:15:00-05:00",
        "season": season_label(when),
        "model": "logistic",
        "methods": [dict(item) for item in METHODS],
        "groups": groups,
        "skipped": [],
    }
    if pending:
        return day
    return apply_grade(day, _payload(flat, scorers))


def _payload(players, scorers):
    games = {}
    for player in players:
        if player["home"]:
            key = (player["team"], player["opp"])
        else:
            key = (player["opp"], player["team"])
        games.setdefault(key, [])
    out = []
    for home, away in games:
        goals = []
        for player in players:
            if player["pid"] in scorers and player["team"] in (home, away):
                goals.append({
                    "playerId": player["pid"],
                    "periodDescriptor": {"periodType": "REG"},
                })
        out.append({
            "gameType": 2,
            "gameState": "OFF",
            "homeTeam": {"abbrev": home},
            "awayTeam": {"abbrev": away},
            "goals": goals,
        })
    return {"games": out}


def build(dest):
    if os.path.isdir(dest):
        for root, dirs, files in os.walk(dest, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
    start = dt.date(2026, 11, 2)
    for offset in range(12):
        when = start + dt.timedelta(days=offset)
        publish_day(dest, _day(when, offset, pending=False), as_today=False)
    today = dt.date(2026, 11, 14)
    publish_day(dest, _day(today, 12, pending=True), as_today=True)


if __name__ == "__main__":
    out = os.path.join(ROOT, "tests", "fixtures", "publish")
    build(out)
    print(out)
