#!/bin/sh
# Hourly wrapper for the Tims hockey job.
#
# Bluehost cron uses the server clock (MST, UTC-7) and may ignore CRON_TZ,
# so this script decides from America/Toronto. Install as:
#
#   5 * * * * $HOME/tims-hockey/job/cron_run.sh
#
# It grades finished days and, once Tims has posted today's lists, scores
# them. It never submits a pick. One log line per invocation goes to
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
if [ -z "$hour" ]; then
  hour=0
fi
if [ "$hour" -lt 3 ] || [ "$hour" -gt 13 ]; then
  log "skip hour ${hour}"
  exit 0
fi

today=$(TZ=America/Toronto date '+%Y-%m-%d')
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

TIMS_ENV="${ROOT}/secrets/tims.env" \
  "$PY" "${ROOT}/job/run_daily.py" \
  --publish "$PUBLISH" \
  --log "${LOGDIR}/daily.log"
code=$?

if [ "$code" -eq 0 ] || [ "$code" -eq 75 ]; then
  if rsync -a --delete "${PUBLISH}/" "${WEB}/"; then
    log "exit ${code} rsync"
  else
    log "exit ${code} rsync failed"
    exit 1
  fi
else
  log "exit ${code}"
fi
exit "$code"
