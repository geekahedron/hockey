"""Daily runner for the public Tims Hockey Challenge page.

    ~/tims-venv/bin/python ~/tims-hockey/job/run_daily.py \\
        --publish ~/tims-hockey/publish

Credentials, when the Tims source is used, come only from $TIMS_ENV.
Logs go to --log (default: no file). The log path must not sit in the
publish directory or under public_html. The runner never submits a pick.

Exit status is 0 on success and 1 on a refresh, groups, or publish error.
75 means today's Tims lists are not posted yet: past days were still graded,
today.json was not replaced with a new slate, and the caller should retry.
A grade that is still pending is success: the slate is published either way.

The run refreshes NHL results and grades every unfinished published day
before it asks Tims for today. Grading math is unchanged.
"""
import argparse
import datetime as dt
import json
import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "model")
for _path in (_ROOT, _MODEL):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from job.clone_attach import (
    BACKFILL_FROM,
    CloneError,
    cache_path,
    load_cache,
    model_snapshot,
    save_cache,
)
from job.grade import apply_grade
from job.groups import FileGroupsSource, GroupsSourceError, TimsGroupsSource
from job.publish import PublishError, list_days, load_day, publish_day
from job.refresh import RefreshError, refresh
from job.score import ScoreError, schedule_map, score_groups


def today_toronto():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Toronto")).date()
    except Exception:
        return dt.date.today()


def _inside(child, parent):
    child = os.path.abspath(child)
    parent = os.path.abspath(parent)
    return child == parent or child.startswith(parent + os.sep)


def _default_get(url):
    import fetch_boxscores
    return fetch_boxscores.get(url)


class Log(object):
    def __init__(self, path, publish_dir):
        self.path = path
        if path:
            full = os.path.abspath(os.path.expanduser(path))
            if "public_html" in full.split(os.sep):
                raise SystemExit("refusing to log under public_html")
            if publish_dir and _inside(full, publish_dir):
                raise SystemExit("refusing to log inside the publish directory")
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self.path = full

    def __call__(self, msg):
        line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        print(line, file=sys.stderr)
        if self.path:
            with open(self.path, "a") as handle:
                handle.write(line + "\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Score today's Tims groups and publish JSON.")
    parser.add_argument("--date", help="Slate date YYYY-MM-DD (default: today in Toronto)")
    parser.add_argument("--groups", help="Local groups JSON. Skips the Tims source.")
    parser.add_argument("--publish", required=True, help="Directory of today.json, season.json, days/")
    parser.add_argument("--raw", help="NHL raw directory (default: model/raw)")
    parser.add_argument("--no-refresh", action="store_true", help="Do not fetch NHL feeds")
    parser.add_argument("--no-grade", action="store_true", help="Do not grade finished games")
    parser.add_argument("--rescore", action="store_true", help="Score again even if this date is already graded")
    parser.add_argument(
        "--backfill-clones",
        action="store_true",
        help=(
            "Add the two extra methods to published days from 2026-11-02. "
            "Does not rescore the logistic model and does not need Tims credentials."
        ),
    )
    parser.add_argument(
        "--backfill-from",
        default=BACKFILL_FROM,
        help="First slate date for --backfill-clones (default 2026-11-02)",
    )
    parser.add_argument(
        "--backfill-to",
        help="Last slate date for --backfill-clones (default: every later published day)",
    )
    parser.add_argument(
        "--relabel",
        action="store_true",
        help=(
            "Rewrite method labels on published days and rebuild season.json, "
            "including the year-to-date charts. Does not rescore and does not use the network."
        ),
    )
    parser.add_argument("--log", help="Append-only log file, outside the publish dir and the web root")
    return parser.parse_args(argv)


# sysexits EX_TEMPFAIL. The hourly wrapper retries this, and does not treat it as a hard failure.
NOT_READY = 75


def _slate_not_ready(exc):
    """True when Tims answered with a slate that is not today's lists yet."""
    text = str(exc)
    return (
        "HockeyPlayers slate is for" in text
        or "HockeyPlayers response had no games" in text
        or "HockeyPlayers response had no player sets" in text
    )


def _shown_date(publish_dir):
    path = os.path.join(publish_dir, "today.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            return json.load(handle).get("date")
    except (OSError, ValueError):
        return None


def _grade_published(publish_dir, getter, log):
    """Grade unfinished days. Same apply_grade path as before, run first.

    today.json is updated only when it already shows the day just graded,
    so a missing morning slate leaves yesterday's graded file on the page.
    """
    shown = _shown_date(publish_dir)
    for saved in list_days(publish_dir):
        if not _needs_grade(saved):
            continue
        payload = getter(
            "https://api-web.nhle.com/v1/score/%s" % saved["date"]
        )
        if payload is None:
            log("grade skipped %s: score feed failed" % saved["date"])
            continue
        apply_grade(saved, payload)
        publish_day(
            publish_dir, saved, as_today=(saved.get("date") == shown)
        )
        log("graded %s -> %s" % (saved["date"], saved["status"]))


def _needs_grade(day):
    if day.get("status") != "graded":
        return True
    for group in day.get("groups") or []:
        if group.get("status") != "graded":
            return True
    return False


def _clone_fetcher(getter, raw_dir):
    """Return ``fetch(date, players)`` backed by the public NHL stats API.

    Previous seasons are cached under the raw directory, which is not published.
    """
    from clones import live_features

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


def relabel_days(publish_dir, log):
    """Refresh public method names and rebuild the season charts.

    Probabilities, picks, and hits stay as they were. Days that do not yet
    have the extra methods are left without them; run --backfill-clones for that.
    """
    from job.score import METHODS

    specs = {item["id"]: item for item in METHODS}
    today_date = None
    today_path = os.path.join(publish_dir, "today.json")
    if os.path.exists(today_path):
        with open(today_path) as handle:
            today_date = json.load(handle).get("date")
    updated = 0
    for saved in list_days(publish_dir):
        before = model_snapshot(saved)
        methods = []
        for method in saved.get("methods") or []:
            spec = specs.get(method.get("id"))
            if not spec:
                methods.append(method)
                continue
            updated_method = dict(method)
            updated_method["label"] = spec["label"]
            updated_method["kind"] = spec.get("kind") or updated_method.get("kind") or "probability"
            if spec.get("description"):
                updated_method["description"] = spec["description"]
            methods.append(updated_method)
        saved["methods"] = methods
        if model_snapshot(saved) != before:
            log("relabel refused %s: model fields changed" % saved.get("date"))
            continue
        publish_day(publish_dir, saved, as_today=(saved.get("date") == today_date))
        updated += 1
        log("relabel %s" % saved.get("date"))
    log("relabel updated %d" % updated)
    return 0


def backfill_clones(publish_dir, getter, raw_dir, log, start, end):
    """Add clone columns to published days. Model probabilities and picks stay.

    Hits for the extra methods are filled from the scored flags already on a
    graded day. Pending days get the columns and a null hit.
    """
    from job.clone_attach import attach_day, players_for_fetch

    clone_fetch = _clone_fetcher(getter, raw_dir)
    today_date = None
    today_path = os.path.join(publish_dir, "today.json")
    if os.path.exists(today_path):
        with open(today_path) as handle:
            today_date = json.load(handle).get("date")
    updated = 0
    failed = 0
    for saved in list_days(publish_dir):
        iso = saved.get("date") or ""
        if iso < start:
            continue
        if end and iso > end:
            continue
        before = model_snapshot(saved)
        try:
            features = clone_fetch(iso, players_for_fetch(saved))
            attach_day(saved, features)
        except Exception as exc:
            log("backfill skipped %s: %s" % (iso, exc))
            failed += 1
            continue
        after = model_snapshot(saved)
        if before != after:
            log("backfill refused %s: model fields changed" % iso)
            failed += 1
            continue
        saved["clones_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        publish_day(publish_dir, saved, as_today=(iso == today_date))
        updated += 1
        log("backfill %s" % iso)
    log("backfill updated %d, failed %d" % (updated, failed))
    return failed


def run(argv=None, get_json=None, tims_source=None):
    args = parse_args(argv)
    publish_dir = os.path.abspath(os.path.expanduser(args.publish))
    log = Log(args.log, publish_dir)
    when = dt.date.fromisoformat(args.date) if args.date else today_toronto()
    getter = get_json or _default_get

    import features
    raw_dir = os.path.abspath(os.path.expanduser(args.raw)) if args.raw else features.RAW
    if args.raw:
        features.RAW = raw_dir

    try:
        if args.relabel:
            return relabel_days(publish_dir, log)

        if args.backfill_clones:
            failed = backfill_clones(
                publish_dir, getter, raw_dir, log, args.backfill_from, args.backfill_to
            )
            return 1 if failed else 0

        if not args.no_refresh:
            added = refresh(when, raw_dir, get_json=getter, log=log)
            log("nhl refresh +%d games into %s" % (added, raw_dir))

        if not args.no_grade:
            _grade_published(publish_dir, getter, log)

        try:
            existing = load_day(publish_dir, when.isoformat())
            rescore = existing is None or existing.get("status") == "pending" or args.rescore
            if rescore:
                if args.groups:
                    source = FileGroupsSource(args.groups)
                elif tims_source is not None:
                    source = tims_source
                else:
                    source = TimsGroupsSource(publish_dir=publish_dir)
                groups = source.fetch(when)
                log("groups %s: %d groups" % (when.isoformat(), len(groups.get("groups") or [])))
                schedule_payload = getter(
                    "https://api-web.nhle.com/v1/score/%s" % when.isoformat()
                )
                if schedule_payload is None:
                    log("schedule feed unavailable; using home/away from the groups file")
                    schedule_payload = {}
                day = score_groups(
                    when,
                    groups,
                    schedule_map(schedule_payload),
                    clone_fetch=_clone_fetcher(getter, raw_dir),
                )
                publish_day(publish_dir, day, as_today=True)
                log("scored %s (%d groups)" % (when.isoformat(), len(day["groups"])))
            else:
                log("keeping graded slate %s" % when.isoformat())
                publish_day(publish_dir, existing, as_today=True)
        except GroupsSourceError as exc:
            # Today's lists were not written. Graded days already published stay.
            if _slate_not_ready(exc):
                log("groups not ready: %s" % exc)
                log("today.json left unchanged")
                return NOT_READY
            log("groups: %s" % exc)
            log("published JSON left unchanged")
            return 1
    except (RefreshError, PublishError, ScoreError, OSError) as exc:
        log("error: %s" % exc)
        return 1
    except Exception as exc:
        log("error: %s" % exc)
        traceback.print_exc()
        return 1
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
