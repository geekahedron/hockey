"""Daily runner for the public Tims Hockey Challenge page.

    ~/tims-venv/bin/python ~/tims-hockey/job/run_daily.py \\
        --publish ~/tims-hockey/publish

Credentials, when the Tims source is used, come only from $TIMS_ENV.
Logs go to --log (default: no file). The log path must not sit in the
publish directory or under public_html. The runner never submits a pick.

Exit status is 0 on success and 1 on a refresh, groups, or publish error.
A grade that is still pending is success: the slate is published either way.
"""
import argparse
import datetime as dt
import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "model")
for _path in (_ROOT, _MODEL):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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
    parser.add_argument("--log", help="Append-only log file, outside the publish dir and the web root")
    return parser.parse_args(argv)


def _needs_grade(day):
    if day.get("status") != "graded":
        return True
    for group in day.get("groups") or []:
        if group.get("status") != "graded":
            return True
    return False


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
        if not args.no_refresh:
            added = refresh(when, raw_dir, get_json=getter, log=log)
            log("nhl refresh +%d games into %s" % (added, raw_dir))

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
            day = score_groups(when, groups, schedule_map(schedule_payload))
            publish_day(publish_dir, day, as_today=True)
            log("scored %s (%d groups)" % (when.isoformat(), len(day["groups"])))
        else:
            log("keeping graded slate %s" % when.isoformat())
            publish_day(publish_dir, existing, as_today=True)

        if not args.no_grade:
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
                    publish_dir, saved, as_today=(saved["date"] == when.isoformat())
                )
                log("graded %s -> %s" % (saved["date"], saved["status"]))
    except GroupsSourceError as exc:
        # The slate was not written. Yesterday's JSON stays on disk.
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
