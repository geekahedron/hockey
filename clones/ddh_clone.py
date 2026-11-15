"""DDH-style estimate (numpy only).

Closed form for a multi-season even-strength and power-play rate, times
expected ice time, with a small adjustment for opponent, home, position,
and back-to-back. It is an estimate from public NHL totals, not a
third-party site's published probability.

  es_rate = (sum_k w_k*ES goals_k + k_es*leagueES/60) / (sum_k w_k*ES minutes_k + k_es) * 60
  pp_rate = (sum_k w_k*PP goals_k + k_pp*leaguePP/60) / (sum_k w_k*PP minutes_k + k_pp) * 60
      k in {this season (w=1), last season, two seasons ago, three seasons ago}
  es_toi, pp_toi = minutes per game, this season blended with last season
  lambda = scale * (es_rate*es_toi + pp_rate*pp_toi)/60 * (opp GA per game / league GA per game)^opp_exp
           * exp(home*home + d*is_D + b2b*played_yesterday + young*max(0,25-age) + old*max(0,age-30))
  p = 1 - exp(-lambda)
"""
import numpy as np

PARAM_NAMES = [
    "log_scale", "w_prev", "w_prev2", "w_prev3", "k_es", "k_pp", "k_toi", "opp_exp",
    "home_coef", "d_coef", "b2b_coef", "young_coef", "old_coef", "mix_goal",
]
# League rates (goals per 60) from 2024-25 and 2025-26 regular-season box scores.
LG = {
    "F": {"es": 0.76, "pp": 1.78, "all": 0.86, "toi": 13.5, "pp_toi": 1.2},
    "D": {"es": 0.21, "pp": 0.76, "all": 0.23, "toi": 19.0, "pp_toi": 0.8},
}


def _a(frame, column, default=0.0):
    if column not in frame:
        return np.full(len(np.asarray(frame["pid"])), default)
    return np.nan_to_num(np.asarray(frame[column], dtype=float), nan=default)


def components(params, frame, lg=None):
    league = lg or LG
    if not isinstance(params, dict):
        params = dict(zip(PARAM_NAMES, params))
    is_defense = _a(frame, "is_d") > 0

    def baseline(key):
        return np.where(is_defense, league["D"][key], league["F"][key])

    weights = {
        "cur": 1.0,
        "prev": params["w_prev"],
        "prev2": params["w_prev2"],
        "prev3": params["w_prev3"],
    }
    es_goals = sum(weights[key] * (_a(frame, "%s_g" % key) - _a(frame, "%s_ppg" % key)) for key in weights)
    es_minutes = sum(weights[key] * (_a(frame, "%s_toi" % key) - _a(frame, "%s_pptoi" % key)) for key in weights)
    pp_goals = sum(weights[key] * _a(frame, "%s_ppg" % key) for key in weights)
    pp_minutes = sum(weights[key] * _a(frame, "%s_pptoi" % key) for key in weights)
    es_rate = (es_goals + params["k_es"] * baseline("es") / 60) / (es_minutes + params["k_es"]) * 60
    pp_rate = (pp_goals + params["k_pp"] * baseline("pp") / 60) / (pp_minutes + params["k_pp"]) * 60
    current_gp = _a(frame, "cur_gp")
    previous_gp = _a(frame, "prev_gp")

    def per_game(total, games, fallback):
        return np.where(games > 0, total / np.maximum(games, 1), fallback)

    current_es = per_game(_a(frame, "cur_toi") - _a(frame, "cur_pptoi"), current_gp, 0)
    previous_es = per_game(_a(frame, "prev_toi") - _a(frame, "prev_pptoi"), previous_gp, baseline("toi"))
    current_pp = per_game(_a(frame, "cur_pptoi"), current_gp, 0)
    previous_pp = per_game(_a(frame, "prev_pptoi"), previous_gp, baseline("pp_toi"))
    shrink = params["k_toi"]
    es_toi = (current_gp * current_es + shrink * previous_es) / (current_gp + shrink)
    pp_toi = (current_gp * current_pp + shrink * previous_pp) / (current_gp + shrink)
    opponent = _a(frame, "opp_ga_pg", 3.0) / _a(frame, "lg_ga_pg", 3.0)
    back_to_back = (_a(frame, "rest_t", 2) == 1).astype(float)
    age = _a(frame, "age", 27.0)
    multiplier = (
        np.exp(params["log_scale"])
        * opponent ** params["opp_exp"]
        * np.exp(
            params["home_coef"] * _a(frame, "home")
            + params["d_coef"] * is_defense
            + params["b2b_coef"] * back_to_back
            + params["young_coef"] * np.maximum(0, 25 - age)
            + params["old_coef"] * np.maximum(0, age - 30)
        )
    )
    # Optional shot-quality blend. The fitted mix_goal is 1, so this is idle.
    all_minutes = sum(weights[key] * _a(frame, "%s_toi" % key) for key in weights)
    goals_rate = (
        sum(weights[key] * _a(frame, "%s_g" % key) for key in weights)
        + params["k_es"] * baseline("all") / 60
    ) / (all_minutes + params["k_es"])
    expected_rate = (
        sum(weights[key] * _a(frame, "%s_ixg" % key) for key in weights)
        + params["k_es"] * baseline("all") / 60
    ) / (all_minutes + params["k_es"])
    mix = params.get("mix_goal", 1.0)
    quality = (mix * goals_rate + (1 - mix) * expected_rate) / goals_rate
    lam = (es_rate * es_toi + pp_rate * pp_toi) / 60 * multiplier * quality
    return {
        "es_rate": es_rate,
        "pp_rate": pp_rate,
        "es_toi": es_toi,
        "pp_toi": pp_toi,
        "mult": multiplier,
        "lam": lam,
    }


def lam(params, frame):
    return components(params, frame)["lam"]


def prob(params, frame):
    return 1 - np.exp(-lam(params, frame))
