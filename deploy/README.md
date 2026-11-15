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
    days/index.json
    days/YYYY-MM-DD.json
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

The crontab line is `job/cron.example`. It grades any published day that is
still pending, scores today, and syncs the JSON:

```
15 10 * * * TIMS_ENV=$HOME/tims-hockey/secrets/tims.env $HOME/tims-venv/bin/python $HOME/tims-hockey/job/run_daily.py --publish $HOME/tims-hockey/publish --log $HOME/tims-hockey/logs/daily.log && rsync -a --delete $HOME/tims-hockey/publish/ $HOME/public_html/tools/hockey/data/
```

The clock is the server's local time. 10:15 is a morning slot, after the
day's groups are usually posted and before most games. One run is enough:
the next morning grades last night and scores the new slate.

`TIMS_ENV` must be set for the live groups. `--groups FILE` still scores a
local JSON file instead. Do not point `--groups` at a file inside
`public_html`.

Manual publish of the page itself, after a code change, is the three-file
`cp` above. The cron does not copy HTML.

## Backfill the two extra methods

Do not deploy from a checkout of this README. On the host, after `git pull`,
add the DDH-style estimate and the HCH-style ranking to days already in
`~/tims-hockey/publish`. This does not rescore the logistic model, does not
read Tims credentials, and does not copy HTML. It calls the public NHL stats
API for each slate from 2026-11-02, using totals through the previous day.

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-clones \
  --log ~/tims-hockey/logs/backfill.log
```

Exit 0 means every day in that window was updated. Exit 1 means at least one
day was left unchanged; the log names it, and running the command again
retries it. `--backfill-from 2026-11-02` and `--backfill-to YYYY-MM-DD`
limit the range. When the exit code is 0, the usual rsync publishes the JSON:

```
rsync -a --delete ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Copy `web/index.html`, `web/app.js`, and `web/style.css` into
`~/public_html/tools/hockey/` when the page itself should show the new
columns. Until that copy, the previous page still reads the model fields.

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
