#!/bin/sh
# Tims lists and grades for the public hockey page.
#
# Bluehost cron uses the server clock (MST, UTC-7) and may ignore CRON_TZ,
# so this script decides from America/Toronto. Install one line:
#
#   */5 * * * * $HOME/tims-hockey/job/cron_run.sh
#
# */30 in the same position also works. Anything else is a skip.
#
# Morning slate: once an hour from 03:00 through 13:59 Toronto, on minute
# 00 or 05, until today is graded or partial. A pending slate still runs.
# Exit 75 means today's lists are not posted yet; the next hour retries.
# A stamp file stops the other minute of that same hour from running again.
#
# List checks, even after the morning slate is up (America/Toronto):
#   00:00 03:00 13:00 15:30 18:00 18:30 19:00 19:30 20:00 20:30
#
# The job grades finished days before it asks Tims for lists. It never
# submits a pick. One log line per invocation goes to
# ~/tims-hockey/logs/cron.log.

ROOT="${HOME}/tims-hockey"
PUBLISH="${ROOT}/publish"
LOGDIR="${ROOT}/logs"
LOG="${LOGDIR}/cron.log"
LOCK="${LOGDIR}/cron.lock"
PY="${HOME}/tims-venv/bin/python"
WEB="${HOME}/public_html/tools/hockey/data"

mkdir -p "$LOGDIR"

log() {
  stamp=$(TZ=America/Toronto date '+%Y-%m-%d %H:%M:%S')
  printf '%s %s\n' "$stamp" "$*" >> "$LOG"
}

exec 9>"$LOCK"
if ! flock -n 9; then
  log "skip busy"
  exit 0
fi

hour=$(TZ=America/Toronto date '+%H' | sed 's/^0*//')
minute=$(TZ=America/Toronto date '+%M' | sed 's/^0*//')
if [ -z "$hour" ]; then
  hour=0
fi
if [ -z "$minute" ]; then
  minute=0
fi
today=$(TZ=America/Toronto date '+%Y-%m-%d')
hhmm=$(printf '%02d%02d' "$hour" "$minute")

snapshot=0
case "$hhmm" in
  0000|0300|1300|1530|1800|1830|1900|1930|2000|2030) snapshot=1 ;;
esac

morning=0
if [ "$hour" -ge 3 ] && [ "$hour" -le 13 ]; then
  if [ "$minute" -eq 0 ] || [ "$minute" -eq 5 ]; then
    if [ ! -f "${LOGDIR}/morning-${today}-${hour}" ]; then
      morning=1
    fi
  fi
fi

if [ "$snapshot" -eq 0 ] && [ "$morning" -eq 0 ]; then
  log "skip time ${hour}:$(printf '%02d' "$minute")"
  exit 0
fi

if [ "$morning" -eq 1 ]; then
  touch "${LOGDIR}/morning-${today}-${hour}"
fi

if [ "$snapshot" -eq 0 ]; then
  if [ -f "${PUBLISH}/today.json" ]; then
    state=$("$PY" -c '
import json, sys
doc = json.load(open(sys.argv[1]))
print("%s %s" % (doc.get("date") or "", doc.get("status") or ""))
' "${PUBLISH}/today.json" 2>/dev/null) || state=""
    file_date=$(printf '%s' "$state" | awk '{print $1}')
    file_status=$(printf '%s' "$state" | awk '{print $2}')
    # A file dated today that is graded or partial is done for the morning.
    # Pending still runs, so a slate posted as pending can be graded later
    # in the window, and a not-yet-posted day is not this file.
    if [ "$file_date" = "$today" ] && [ "$file_status" != "pending" ]; then
      log "skip today ${file_status}"
      exit 0
    fi
  fi
fi

TIMS_ENV="${ROOT}/secrets/tims.env" \
  "$PY" "${ROOT}/job/run_daily.py" \
  --publish "$PUBLISH" \
  --log "${LOGDIR}/daily.log"
code=$?

if [ "$code" -eq 0 ] || [ "$code" -eq 75 ]; then
  # seasons.json is the page's season list. Rewrite it on every publish so
  # --delete cannot drop it. seasons/ is the backtest drop-in on the web
  # host (data/seasons/<id>/). Exclude it so this rsync neither deletes nor
  # overwrites that tree.
  JOB_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
  REPO_DIR=$(dirname "$JOB_DIR")
  if ! PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:$PYTHONPATH}" \
    "$PY" -c 'import sys
from job.publish import write_seasons_manifest
write_seasons_manifest(sys.argv[1])
' "$PUBLISH"; then
    log "exit ${code} seasons manifest failed"
    exit 1
  fi
  if rsync -a --delete --exclude '/seasons/' "${PUBLISH}/" "${WEB}/"; then
    log "exit ${code} rsync"
  else
    log "exit ${code} rsync failed"
    exit 1
  fi
else
  log "exit ${code}"
fi
exit "$code"
