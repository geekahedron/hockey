"""HCH-style ranking from public NHL season totals.

Sort each set by this season's goals per game, shown to 2 decimals, highest
first. Ties break toward the lower NHL player id. The accompanying figures
are season totals: games, goals, shots, shooting percentage, time on ice,
power-play time on ice, opponent goals against per game, and home or away.

This is not a third-party site's ranking. It is this season's goals per game.
"""


def data_points(row):
    games = row.get("cur_gp") or 0
    goals = row.get("cur_g") or 0
    shots = row.get("cur_sog") or 0
    return {
        "gp": int(games),
        "goals": int(goals),
        "goals_per_game": round(goals / games, 2) if games else 0.0,
        "shots": int(shots),
        "shots_per_game": round(shots / games, 2) if games else 0.0,
        "shooting_pct": round(100.0 * goals / shots, 1) if shots else 0.0,
        "toi_per_game": round((row.get("cur_toi") or 0) / games, 2) if games else 0.0,
        "pp_toi_per_game": round((row.get("cur_pptoi") or 0) / games, 2) if games else 0.0,
        "opp_ga_per_game": round(row.get("opp_ga_pg") or 0, 2),
        "home_away": "HOME" if row.get("home") else "AWAY",
    }


def rank(rows):
    """Return ``{pid: rank}`` with 1 as the top of the set."""
    order = sorted(rows, key=lambda row: (-data_points(row)["goals_per_game"], int(row["pid"])))
    return {int(row["pid"]): place for place, row in enumerate(order, 1)}
