"""logistic_json matches train_utils.X and a sklearn pipeline on fixture rows."""
import json
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import logistic_json
from train_utils import X as train_X

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = json.load(open(os.path.join(HERE, "fixtures", "feature_rows.json")))
MODEL = json.load(open(logistic_json._PATH))


def _frame():
    return pd.DataFrame(ROWS)


def _sklearn_proba(matrix):
    n = matrix.shape[1]
    scaler = StandardScaler()
    scaler.mean_ = np.asarray(MODEL["scaler"]["mean_"], dtype=np.float64)
    scaler.scale_ = np.asarray(MODEL["scaler"]["scale_"], dtype=np.float64)
    scaler.var_ = scaler.scale_ ** 2
    scaler.n_features_in_ = n
    scaler.n_samples_seen_ = np.int64(1)
    clf = LogisticRegression()
    clf.classes_ = np.array([0, 1])
    clf.coef_ = np.asarray(MODEL["coef_"], dtype=np.float64).reshape(1, -1)
    clf.intercept_ = np.asarray(MODEL["intercept_"], dtype=np.float64).reshape(-1)
    clf.n_features_in_ = n
    pipe = Pipeline([("scaler", scaler), ("clf", clf)])
    return pipe.predict_proba(matrix)[:, 1]


def test_transform_matches_train_utils():
    frame = _frame()
    order = MODEL["features"]
    got = logistic_json.transform(frame)
    expect = train_X(frame)[order].to_numpy(dtype=np.float64)
    assert got.shape == expect.shape
    assert np.allclose(got, expect, atol=1e-15, rtol=0)


# Locked P(score) for the three fixture rows. sklearn Pipeline and logistic_json agree.
EXPECTED = np.array([
    0.3295076697216704,
    0.0623791317186453,
    0.1480693730488195,
])


def test_predict_proba_matches_sklearn_pipeline():
    frame = _frame()
    got = logistic_json.predict_proba(frame)[:, 1]
    expect = _sklearn_proba(logistic_json.transform(frame))
    assert np.allclose(got, expect, atol=1e-12, rtol=0)
    assert np.allclose(got, EXPECTED, atol=1e-12, rtol=0)
    assert np.all((got > 0) & (got < 1))
    # The star row is the first fixture and should outscore the depth defender.
    assert got[0] > got[1]


def test_predict_proba_class_columns():
    both = logistic_json.predict_proba(_frame())
    assert both.shape == (len(ROWS), 2)
    assert np.allclose(both.sum(axis=1), 1.0, atol=1e-12)
