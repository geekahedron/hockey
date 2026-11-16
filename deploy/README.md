# Deploying the hockey page on shared hosting

Do not deploy from this README's machine. This is the layout for the
Bluehost/Justhost account. The cron job publishes JSON. The site is static
files plus that JSON. Nothing here submits a Tims pick.

The host is Python 3.9.25. The virtualenv is already at `~/tims-venv`
(numpy 2.0.2, pandas 2.3.3, sklearn 1.6.1). The daily runner scores the
logistic model with `model/logistic_json.py` (numpy and pandas, not the
joblib file). The two extra methods use numpy only (`clones/`).

## Layout

```
~/tims-hockey/                         git checkout. NOT inside public_html
  model/raw/                           NHL box scores and TOI. Not published
  job/run_daily.py                     the daily runner
  web/                                 static page (html, css, js)
  secrets/tims.env                     chmod 600. See deploy/tims.env.example
  publish/                             job output. rsync source
  logs/daily.log                       outside the web root

~/tims-venv/                           existing Python 3.9 virtualenv

~/public_html/tools/hockey/            the page
  index.html
  app.js
  style.css
  data/                                rsync target. JSON only
    today.json
    season.json
    seasons.json                       season list, rewritten every publish
    days/index.json
    days/YYYY-MM-DD.json
    seasons/2025-26/                   backtest drop-in. rsync excludes seasons/
    seasons/2024-25/                   backtest drop-in. rsync excludes seasons/
    seasons/2023-24/                   backtest drop-in. rsync excludes seasons/
    seasons/2022-23/                   backtest drop-in. rsync excludes seasons/
    seasons/2021-22/                   backtest drop-in. rsync excludes seasons/
```

`~/tims-hockey` stays outside `public_html` so the model, the raw files, and
the secrets file are not on the web. The publish directory is JSON only, and
the job refuses to write a secret field or to put its log in that directory.

## One-time setup

```
cd ~
git clone <this repo> tims-hockey
mkdir -p ~/tims-hockey/secrets ~/tims-hockey/logs ~/tims-hockey/publish
cp ~/tims-hockey/deploy/tims.env.example ~/tims-hockey/secrets/tims.env
chmod 600 ~/tims-hockey/secrets/tims.env
mkdir -p ~/public_html/tools/hockey/data
cp ~/tims-hockey/web/index.html ~/tims-hockey/web/app.js ~/tims-hockey/web/style.css \
   ~/public_html/tools/hockey/
```

Copy the existing `model/raw/` tree (box scores and TOI for the current season
and the two before it) into `~/tims-hockey/model/raw/`. The job backfills a
missing season once, then only appends finished games. Features are rebuilt
from those files on every run.

The page copy does not include `tests/fixtures`. Those files are sample data
for local screenshots.

## Daily run

The crontab line is `job/cron.example`. Paste this; the server clock can
stay on MST. Do not rely on `CRON_TZ`.

```
*/5 * * * * $HOME/tims-hockey/job/cron_run.sh
```

`*/30 * * * *` is the other cadence that hits the same minutes. Install one
of them, not both.

`job/cron_run.sh` reads America/Toronto itself. Most firings log a skip.
Two kinds of firing run the job:

* Morning slate, once an hour from 03:00 through 13:59 (the :00 or :05
  firing, whichever comes first that hour). It refreshes NHL results,
  grades every unfinished published day, then asks Tims for today's lists.
  If those lists are not posted yet the job exits 75, leaves `today.json`
  on yesterday's graded slate, and the next hour tries again. Once today
  is graded or partial, later morning firings skip. A pending slate still
  runs, so a list posted as pending can be checked again in that window.
* List checks at 00:00, 03:00, 12:30, 13:00, 14:00, 15:00, 15:30, 16:00,
  17:00, 18:00, 18:30, 19:00, 19:30, 20:00, 20:30, 21:00, 21:30, and 22:00.
  From 12:30 through 22:00 every one of those is on the hour or the half
  hour, so `*/5` or `*/30` hits them. These run even after the morning
  slate is published. The read is still only `HockeyPlayers`. Nothing
  submits a pick.

The first lists of the day are the morning picks. When a later check adds
or removes players, the day file gains a `snapshots` entry (`time`, `added`,
`removed`, `started`) and `lists` is who can still be picked. Anyone missing
from a check is off the list, whether Tims scratched them or their game has
already started. A player still on the Tims list is also off it once
`startTimeUTC` for their team has passed; the page applies that at render
time too, so it does not wait for the next check. A scratch before the
start moves the pick to whoever remains. When the current pick's game
starts, that pick locks and later list changes do not move it. That locked
pick is what gets graded. If every candidate was scratched before a game,
the group has no graded pick. A postponed game (`gameScheduleState` `PPD`)
has not started, so a drop then is a scratch. Morning picks stay as a
labeled reference. A day that was already graded before the run is not
rewritten.

Exit 0 or 75 rsyncs `publish/` to `public_html/tools/hockey/data/`. A hard
error (exit 1) does not. `flock` keeps two runs from overlapping. Each
invocation appends one line to `~/tims-hockey/logs/cron.log`.

One-time setup for the wrapper:

```
mkdir -p ~/tims-hockey/logs ~/public_html/tools/hockey/data
chmod +x ~/tims-hockey/job/cron_run.sh
```

`TIMS_ENV` is set by the wrapper to `~/tims-hockey/secrets/tims.env`. The
job still accepts `--groups FILE` for a local JSON file instead. Do not
point `--groups` at a file inside `public_html`.

Manual publish of the page itself, after a code change, is the three-file
`cp` above. The cron does not copy HTML.

## Names and season charts

Do not deploy from a checkout of this README. After `git pull`, refresh the
public names and rebuild `season.json` (the year-to-date charts live there).
This does not rescore the logistic model, does not use the network, and does
not copy HTML.

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --relabel \
  --log ~/tims-hockey/logs/relabel.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Copy `web/index.html`, `web/app.js`, and `web/style.css` into
`~/public_html/tools/hockey/` when the page itself should show the new names
and charts.

Days published before start times were stored need a one-time fill. This
writes `start` on players, picks, morning rows, and list rows, plus a
`games` map of team to NHL `startTimeUTC`. Picks and grades stay put.
`seasons/` is not read. Run it again any time; a file that already has the
same starts is rewritten with the same values.

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-starts \
  --log ~/tims-hockey/logs/backfill-starts.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Days published before the calculation inputs were stored need a one-time
fill. This writes `inputs.model` (the logistic feature row, including the
log columns the frozen model already builds) and `inputs.estimate` (the
season totals the scoring-rate estimate already reads). Probabilities,
picks, and grades stay put. `seasons/` is not read. Logistic inputs come
from the local box-score archive. Scoring-rate inputs come from the public
NHL stats API. Run it again any time. A stats-feed failure still saves
logistic inputs when the archive loaded; rerun later for the rest. Exit 1
means at least one date was incomplete.

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-inputs \
  --log ~/tims-hockey/logs/backfill-inputs.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Copy `web/index.html`, `web/app.js`, and `web/style.css` into
`~/public_html/tools/hockey/` so the tiles show position and the dialog.

Games missed on days already published come from the local box scores.
This does not invent injury designations and does not change picks or grades.

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-absence \
  --log ~/tims-hockey/logs/backfill-absence.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

If the day files do not yet have the scoring-rate estimate and the
goals-per-game ranking, run the backfill first. It calls the public NHL stats
API for each slate from 2026-11-02, using totals through the previous day.
It does not rescore the logistic model and it does not read Tims credentials.
Exit 1 leaves failed days unchanged; run it again after fixing the feed.
`--backfill-from` and `--backfill-to` narrow the window.

```
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-clones \
  --log ~/tims-hockey/logs/backfill.log
```

## Secrets

* `TIMS_ENV` is a path. The file holds `TIMS_CLIENT_ID`, `TIMS_COGNITO_ID`,
  and `TIMS_REFRESH_TOKEN` (see `deploy/tims.env.example`).
* The runner will not start if that path is under `public_html` or inside
  the publish directory.
* Each run mints an IdToken with `REFRESH_TOKEN_AUTH`. A new refresh token
  in the Cognito response is written back to that same file, mode `0600`.
* Credential values are not passed to the log, and the publisher rejects a
  document that contains a secret field.
* The client only sends `REFRESH_TOKEN_AUTH` and the `HockeyPlayers` query.
  It does not submit a pick and it does not start a magic-link sign-in.
* If the refresh token is rejected, the run logs the failure (the cron log
  is `~/tims-hockey/logs/daily.log`, outside the web root) and leaves the
  published JSON as it was.
