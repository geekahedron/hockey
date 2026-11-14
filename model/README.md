# Tims Hockey Challenge goal model (raw NHL data)

Predicts each player's chance of scoring >=1 non-shootout goal tonight, and picks the top player in each Tims pick group.

## Files
- `fetch_boxscores.py` - regular-season boxscores from api-web.nhle.com -> `raw/box_{season}.jsonl` (goals, shots, TOI, PPG per skater; goalie saves/shots/starter).
- `fetch_pptoi.py` - per-game EV/PP/SH TOI from api.nhle.com/stats/rest -> `raw/toi_{season}.json`.
- `features.py` - pre-game features (only games strictly before the date): shrunk goals/60 and shots/60 (prior = last 2 seasons -> league average by F/D), shooting %, expected TOI and PP TOI (last 5 games blended with season and last season), opponent GA/game, shots against and team save % (shrunk to last season and league), own team goals/game, home/away, back-to-backs, and a Poisson baseline probability.
- `build_dataset.py` -> `data/skater_games_features.csv.gz` (every skater-game 2024-25, 2025-26, 2026-27 to date).
- `train.py` - validates on 2025-26 (trained on 2024-25), then fits final models on 2024-25 + 2025-26 -> `data/models.joblib`, `data/validation_2025_26.json`.
- `backtest.py` - out-of-sample test on this season's real pick groups (HCH history morning lists Oct 2 - Nov 1) -> `data/backtest_*.csv/json`. Needs the HCH history files in /workspace/tims-analysis (copies in ../analysis).
- `score_date.py DATE [--groups FILE] [--no-update]` - pulls any new finished games, scores the day's groups, writes `picks/DATE.json`, prints one pick per group. Default groups file: `../snapshots/DATE_hch.json`.

## Setup
python3 -m venv --system-site-packages .venv && .venv/bin/pip install scikit-learn lightgbm joblib pandas numpy
Example: `.venv/bin/python score_date.py 2026-11-03`

The model used for picks is the logistic regression (`models['logistic']`).

## Tracking (added Nov 2 2026)
- `python grade_date.py DATE` -> grades our #1, HCH #1 (highest goals/game, ties shared) and DDH #1 per group against
  non-shootout scorers from api-web.nhle.com/v1/score/DATE; writes/replaces DATE rows in ../tracking/results.jsonl.
  Groups whose games are not final are written as status "pending" (picks only); re-run the next morning to grade.
- Daily flow: morning `score_date.py DATE` (saves ../snapshots/DATE_hch.json from HCH /api/picks if missing, incl. line/PP unit),
  save DDH list as ../snapshots/DATE_ddh.json, next morning `grade_date.py DATE`.
- ../tracking/backtest_2026-10-02_to_2026-11-01.jsonl = out-of-sample backtest rows in the same shape (status "backtest").

## HCH data-point test (compare_features.py -> data/feature_test_hch_fields.json)
HCH per player: GP, goals, goals/GP, shots, shots/GP, S%, TOI/GP, PP TOI/GP, opponent GAA, home/away, line (F1-F3/D1-D3),
linemates, PP unit (PP1/PP2), PP linemates, unavailable/injury warnings. Only line/PP unit are not already in the model, and
HCH history lacks them, so they were tested via NHL-TOI proxies (role_pp1/pp2/l1/l2; PP1 proxy matched HCH 43/43 on Nov 2,
top line 31/43). Result: no clear gain (val AUC .7063->.7066; backtest pairwise .5746->.5762, CI of diff -.016..+.018;
#1 hits 22->25 of 93, CI -4..+10). Raw GPG/SPG/S% added nothing. Production model unchanged; role features are computed and
saved in picks for re-testing once ~30+ tracked days exist.

## Backtest v2 (Nov 10 2026) -> backtest_v2/
627 HCH morning slots (504 in 2025-26 via HCH history API, 123 in 2026-27 to Nov 9), 104,716 skater-games, PBP shot xG (xg.py,
trained on 2023-24 + 2024-25 shots). Variants: ixG, last-10 form, PP1/line role proxies, team xG / recent save %, shrinkage grid, GBM,
2-stage slot model. None beat the live logistic in both seasons (results_2026-11-10.json). Live model left unchanged.
Run with /workspace/.venv-ml/bin/python; feature code in backtest_v2/features2.py needs raw/ixg_player_game.csv.gz to deploy.
