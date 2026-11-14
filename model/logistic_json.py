"""Version-neutral loader for the frozen logistic goal model.

Reads model/data/logistic.json and scores with numpy only (no sklearn).
predict_proba(df) matches sklearn's Pipeline.predict_proba(X(df)), where
X is train_utils.X.
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, "data", "logistic.json")
_MODEL = None

# Same base columns as features.FEATS; train_utils.X also reads df.p_base.
FEATS = [
    "home", "is_d", "cur_gp", "prev_gp", "g60", "s60", "sh", "xg60",
    "prior_g60", "prior_s60", "toi_hat", "pp_hat", "l5_toi", "opp_ga",
    "opp_sa", "opp_sv", "tm_gf", "b2b", "opp_b2b", "lam_g", "lam_x",
]
_LOG = ["g60", "s60", "xg60", "prior_g60", "prior_s60", "lam_g", "lam_x", "sh"]


def load(path=None):
    """Load coefficients from logistic.json. Called automatically on first score."""
    global _MODEL
    with open(path or _PATH) as f:
        raw = json.load(f)
    intercept = raw["intercept_"]
    if isinstance(intercept, list):
        intercept = intercept[0]
    _MODEL = {
        "features": list(raw["features"]),
        "mean": np.asarray(raw["scaler"]["mean_"], dtype=np.float64),
        "scale": np.asarray(raw["scaler"]["scale_"], dtype=np.float64),
        "coef": np.asarray(raw["coef_"], dtype=np.float64).reshape(-1),
        "intercept": float(intercept),
        "sklearn_version": raw.get("sklearn_version"),
    }
    return _MODEL


def _get():
    return _MODEL if _MODEL is not None else load()


def transform(df):
    """Same column construction as train_utils.X, as a float64 array in pipeline order."""
    cols = {c: np.asarray(df[c], dtype=np.float64) for c in FEATS}
    p_base = np.asarray(df["p_base"], dtype=np.float64)
    for c in _LOG:
        cols["log_" + c] = np.log(np.clip(cols[c], 1e-3, None))
    cols["log_p_base"] = np.log(np.clip(p_base, 1e-3, None))
    cols["cur_gp"] = np.log1p(cols["cur_gp"])
    cols["prev_gp"] = np.log1p(cols["prev_gp"])
    order = _get()["features"]
    return np.column_stack([cols[c] for c in order])


def predict_proba(df):
    """Return an (n, 2) array of class probabilities, matching sklearn's predict_proba."""
    m = _get()
    X = transform(df)
    z = (X - m["mean"]) / m["scale"]
    logit = z @ m["coef"] + m["intercept"]
    # Stable sigmoid, matching scipy.special.expit as used by sklearn.
    p1 = np.empty_like(logit)
    pos = logit >= 0
    p1[pos] = 1.0 / (1.0 + np.exp(-logit[pos]))
    exp_x = np.exp(logit[~pos])
    p1[~pos] = exp_x / (1.0 + exp_x)
    return np.column_stack([1.0 - p1, p1])
