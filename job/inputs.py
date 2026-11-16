"""Publish the inputs each method already computed.

The logistic probability is not recomputed here. ``model_inputs`` copies the
feature row the scorer just built, plus the log columns ``logistic_json``
already builds inside ``transform``. The scoring-rate block copies the
public-NHL season totals the estimate already reads. Nothing in this module
changes a probability, a pick, or a grade.
"""
import json
import os

# Game counts and flags. Everything else is a rate.
_COUNT_KEYS = ("home", "is_d", "cur_gp", "prev_gp", "b2b", "opp_b2b")
_ESTIMATE_SEASONS = ("cur", "prev", "prev2", "prev3")
_ESTIMATE_FIELDS = ("gp", "g", "sog", "toi", "pptoi", "ppg")
_ESTIMATE_CONTEXT = ("is_d", "home", "opp_ga_pg", "lg_ga_pg", "rest_t")
_ESTIMATE_COUNTS = ("gp", "g", "sog", "ppg", "is_d", "home", "rest_t")


def json_number(value, digits=6):
    """A JSON number, or None when the feature was missing or not finite."""
    number = _as_float(value)
    if number is None:
        return None
    if digits <= 0:
        return int(round(number))
    return round(number, digits)


def _as_float(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number == float("inf") or number == float("-inf"):
        return None
    return number


def model_inputs(feat):
    """Feature values for one player. Does not call predict_proba.

    Raw measurements keep their names. ``log_*`` and ``log1p_*`` are the
    extra columns ``logistic_json.transform`` already feeds the frozen model.
    The game-count columns in that matrix are log1p of the raw counts, so
    those two are stored under ``log1p_`` and the raw counts stay put.
    """
    import pandas as pd
    import logistic_json

    keys = list(logistic_json.FEATS) + ["p_base"]
    out = {}
    for key in keys:
        digits = 0 if key in _COUNT_KEYS else 6
        number = json_number(feat.get(key), digits)
        if number is not None:
            out[key] = number
    frame = pd.DataFrame([{key: feat.get(key) for key in keys}])
    matrix = logistic_json.transform(frame)[0]
    names = list(logistic_json.load()["features"])
    for name, value in zip(names, matrix):
        number = _as_float(value)
        if number is None:
            continue
        if name in ("cur_gp", "prev_gp"):
            out["log1p_" + name] = round(number, 6)
        elif name.startswith("log_"):
            out[name] = round(number, 6)
    return out


def estimate_inputs(row):
    """Season totals and context the scoring-rate estimate already reads.

    Shots are included because the goals-per-game figures use them. Age and
    individual expected goals are not on this row; the modal says they were
    not recorded.
    """
    out = {}
    if not isinstance(row, dict):
        return out
    for season in _ESTIMATE_SEASONS:
        for field in _ESTIMATE_FIELDS:
            key = "%s_%s" % (season, field)
            if key not in row:
                continue
            digits = 0 if field in _ESTIMATE_COUNTS else 6
            number = json_number(row.get(key), digits)
            if number is not None:
                out[key] = number
    for key in _ESTIMATE_CONTEXT:
        if key not in row:
            continue
        digits = 0 if key in _ESTIMATE_COUNTS else 6
        number = json_number(row.get(key), digits)
        if number is not None:
            out[key] = number
    return out


def _bucket(player):
    current = player.get("inputs")
    if not isinstance(current, dict):
        current = {}
        player["inputs"] = current
    return current


def _store_model(player, feat):
    _bucket(player)["model"] = model_inputs(feat)


def _store_estimate(player, row):
    from job.clone_attach import _merge

    _bucket(player)["estimate"] = estimate_inputs(_merge(player, row))


def _players(day):
    rows = []
    for group in day.get("groups") or []:
        for player in group.get("players") or []:
            if isinstance(player, dict) and player.get("pid") is not None:
                rows.append(player)
    return rows


def _fetch_list(day):
    rows = []
    seen = set()
    for player in _players(day):
        team = player.get("team")
        if not team:
            continue
        pid = int(player["pid"])
        if pid in seen:
            continue
        seen.add(pid)
        rows.append({
            "pid": pid,
            "team": team,
            "opp": player.get("opp"),
            "home": player.get("home"),
            "name": player.get("name"),
        })
    return rows


def _attach_model(day, builder, log):
    from job.refresh import season_year

    if builder is None:
        return 0
    iso = day.get("date")
    year = season_year(iso)
    stored = 0
    for player in _players(day):
        team = player.get("team")
        opponent = player.get("opp")
        if not team or not opponent or player.get("home") is None:
            continue
        hint = "D" if player.get("position") == "D" else "F"
        try:
            feat = builder.build(
                int(player["pid"]), team, opponent, int(player["home"]), iso, year, hint
            )
            _store_model(player, feat)
            stored += 1
        except Exception as exc:
            log("model inputs not recorded %s %s: %s" % (iso, player.get("pid"), exc))
    return stored


def _attach_estimate(day, rows):
    by_pid = {}
    for row in rows or []:
        if row.get("pid") is None:
            continue
        by_pid[int(row["pid"])] = row
    stored = 0
    for player in _players(day):
        pid = int(player["pid"])
        if pid not in by_pid:
            continue
        _store_estimate(player, by_pid[pid])
        stored += 1
    return stored


def _fetch_union(docs):
    rows = []
    seen = set()
    for doc in docs:
        for row in _fetch_list(doc):
            if row["pid"] in seen:
                continue
            seen.add(row["pid"])
            rows.append(row)
    return rows


def _clone_fetcher(getter, raw_dir):
    from clones import live_features
    from job.clone_attach import CloneError, cache_path, load_cache, save_cache

    path = cache_path(raw_dir)
    cache = load_cache(path)

    def fetch(url):
        payload = getter(url)
        if payload is None:
            raise CloneError("NHL feed failed")
        return payload

    def clone_fetch(date, players):
        try:
            return live_features.build(date, players, cache, fetch=fetch)
        finally:
            save_cache(path, cache)

    return clone_fetch


def backfill_inputs(publish_dir, getter, raw_dir, log):
    """Add per-player inputs to today.json and days/YYYY-MM-DD.json.

    Reads those files only. ``seasons/`` is never opened. A second run writes
    the same inputs. A stats-feed failure still saves logistic inputs when
    the box-score archive loaded, and leaves that date's scoring-rate inputs
    as they were. A change to a pick, a grade, or a probability is not written.
    """
    import features
    from job.publish import _atomic_write
    from job.snapshots import publish_start_paths, record_fingerprint

    previous_raw = features.RAW
    features.RAW = raw_dir
    failed = 0
    updated = 0
    try:
        builder = None
        try:
            skaters, teams, goalies = features.load()
        except Exception as exc:
            log("model inputs not recorded: %s" % exc)
            failed += 1
        else:
            if len(skaters) == 0:
                log("model inputs not recorded: no box scores in %s" % raw_dir)
                failed += 1
            else:
                builder = features.FeatureBuilder(skaters, teams, goalies)
        clone_fetch = _clone_fetcher(getter, raw_dir)
        by_date = {}
        for path in publish_start_paths(publish_dir):
            with open(path) as handle:
                doc = json.load(handle)
            iso = doc.get("date")
            if not iso:
                log("inputs skipped %s: no date" % path)
                continue
            by_date.setdefault(iso, []).append((path, doc))
        for iso in sorted(by_date):
            estimate_rows = None
            docs = [doc for _path, doc in by_date[iso]]
            try:
                estimate_rows = clone_fetch(iso, _fetch_union(docs))
            except Exception as exc:
                log("estimate inputs not recorded %s: %s" % (iso, exc))
                failed += 1
            for path, doc in by_date[iso]:
                before = record_fingerprint(doc)
                model_count = _attach_model(doc, builder, log)
                estimate_count = 0
                if estimate_rows is not None:
                    estimate_count = _attach_estimate(doc, estimate_rows)
                if record_fingerprint(doc) != before:
                    log("inputs refused %s: records changed" % os.path.basename(path))
                    failed += 1
                    continue
                if not model_count and not estimate_count:
                    log("inputs unchanged %s" % os.path.basename(path))
                    continue
                _atomic_write(path, doc)
                updated += 1
                log(
                    "inputs %s %s model=%d estimate=%d"
                    % (iso, os.path.basename(path), model_count, estimate_count)
                )
    finally:
        features.RAW = previous_raw
    log("inputs updated %d, failed %d" % (updated, failed))
    return failed
