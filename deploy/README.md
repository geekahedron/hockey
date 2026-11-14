# Deploying the hockey page on shared hosting

Do not deploy from this README's machine. This is the layout for the
Bluehost/Justhost account. The cron job publishes JSON. The site is static
files plus that JSON. Nothing here submits a Tims pick.

The host is Python 3.9.25. The virtualenv is already at `~/tims-venv`
(numpy 2.0.2, pandas 2.3.3, and the rest of the research stack). The daily
runner only imports numpy and pandas. It scores with `model/logistic_json.py`,
not the joblib file.

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

Until the Tims GET is wired (`job/groups.py`), pass `--groups` with a
normalized JSON file instead of relying on `TIMS_ENV`. The file format is
in the root README. Do not point `--groups` at a file inside `public_html`.

Manual publish of the page itself, after a code change, is the three-file
`cp` above. The cron does not copy HTML.

## Secrets

* `TIMS_ENV` is a path. The file it names holds `TIMS_BEARER` or `TIMS_COOKIE`.
* The runner will not start if that path is under `public_html` or inside
  the publish directory.
* Credential values are not passed to the log, and the publisher rejects a
  document that contains a secret field.
* The picks client is read-only. It does not submit a pick. The live GET is
  still a TODO; see `job/groups.py`.
