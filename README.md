# Tims Hockey Challenge

Public page for [geekahedron.com/tools/hockey/](https://geekahedron.com/tools/hockey/) and the daily job that feeds it.

The goal model in `model/` is frozen. `model/logistic_json.py` plus
`model/data/logistic.json` is the numpy-only export of that logistic
pipeline. This tool does not change features, training, or the scoring math.
See `model/README.md` for how the model was built.

The page shows three methods, named for what they use:

- **Logistic model (player form + matchup)**. Shrunk goals, shots, and ice
  time, plus the opponent, home or away, and rest. This is the frozen model.
- **Scoring-rate estimate**. Even-strength and power-play scoring rates times
  expected ice time, adjusted for the opponent, home or away, and rest.
- **Goals per game**. This season's goals per game, highest first.

The second and third are inspired by methods used by other public Hockey
Challenge helper sites, including DataDrivenHockey and HockeyChallengeHelper.
They are not those sites' ratings. The public names do not use those sites'
initials.

## Page

`web/` is static HTML, CSS, and JS in the same dark theme as
[geekahedron.com/tools/solver/](https://geekahedron.com/tools/solver/). It only
reads JSON:

| File | What the page does with it |
| --- | --- |
| `data/today.json` | Today's three groups. Players sorted by the selected method, a bar per player, team, opponent, home or away, top pick highlighted. The summary lists each method's leader. |
| `data/days/index.json` | The date list. |
| `data/days/YYYY-MM-DD.json` | One slate, including who scored once the games are final. A non-empty `skipped` list is names left off the slate (no team or opponent, including a postponed game). `snapshots` lists players added, removed before their game, or dropped because the game started. `lists` is who can still be picked. Both kinds of drop are `available: false`. A scratch has `removed_at`. A game start has `start` and `game_started`. `morning` is the first picks, for reference. The recorded pick locks when that player's game starts. |
| `data/season.json` | Season tracker for every method: per-day pick, value, hit, running hit rate, top-3 hits, and the random baseline. `charts` is the year-to-date hit rate and cumulative hits for all three methods, plus the same pair of charts for each pick. |
| `data/seasons.json` | Season list. Each row is `{id, label, base, backtest?}`. The page loads `base` for the id in `?season=`, and only an id in this file. Missing file: the page stays on the single live tree. |
| `data/seasons/<id>/` | One extra season, same shapes as `data/` except there is no `today.json`. `season.json` and `days/index.json` may include `backtest`, `scope`, and `notes`. The 2025-26 backtest is dropped in here at deploy time. The daily rsync does not write or delete it. |

Views are Today, Past days, and Season. A season menu appears when `seasons.json` lists more than one season. The live season is the default. `?season=2025-26` opens the backtest. That season has no today card. Its note comes from `notes` on `season.json` and `days/index.json`. A long season collapses past days by month and scrolls the pick table. The method menu lists the three
names above. The compare table on Today has a column per method. A matchup that has `start` (the NHL `startTimeUTC`) also shows that time in Toronto, such as BOS vs TOR · 7:00 PM, on the current pick, the morning pick, each player row, and the compare table. Past days do the same when the day file has it. No start leaves the matchup without a clock. A
probability method is a number on each player at `probability.<id>` (0 to
1). The goals-per-game method is `rank.<id>` (1 is first) plus `style`. The
page does not fetch anything else. The season charts read `season.json`.

Open it from a local server (fetch does not work from `file://`):

```
cd web && python3 -m http.server 8765
```

Sample JSON for screenshots lives in `tests/fixtures/publish/`. Point the
server at a copy where that tree is named `data/`, or pass `?data=` only for
a folder of the same shape. The live site uses `data/` next to `index.html`.

## Daily job

```
~/tims-venv/bin/python job/run_daily.py --publish ~/tims-hockey/publish
```

Python 3.9. The runner does not use 3.10-only syntax. `model/features.py`,
the fetch modules, and `logistic_json.py` already parse on 3.9; the syntax
check is `tests/test_py39.py` (vermin, target 3.9 or older).

One run:

1. Refreshes finished NHL games from api-web.nhle.com and api.nhle.com into
   `model/raw/` (`fetch_boxscores.compact`, `fetch_pptoi.window`). Prior
   seasons are backfilled once. The current season is scanned from the last
   stored game up to today. Features are rebuilt from `raw/` when the slate
   is scored (`features.load`), not from a saved feature table.
2. Loads today's groups. With `--groups FILE`, the file is local JSON. Without
   it, `TimsGroupsSource` reads `$TIMS_ENV` and queries `HockeyPlayers` on
   `https://use1-prod-th-gateway.rbictg.com/graphql`. The IdToken is minted
   with Cognito `REFRESH_TOKEN_AUTH`. Each player is matched to an NHL id by
   team abbreviation and jersey number (`NJ`/`TB`/`SJ`/`LA` map to
   `NJD`/`TBL`/`SJS`/`LAK`). The old px-api host is not used.
3. Grades every published day whose games are now final, and writes those
   day files plus `season.json`. A non-shootout goal counts. A group stays
   pending until each of its teams is `OFF` or `FINAL`. This happens before
   today's lists are requested, so a missing slate cannot block yesterday.
4. Scores every available player with `logistic_json.predict_proba`. The
   joblib pipeline is not loaded. It then adds the scoring-rate estimate and
   the goals-per-game ranking from public NHL season totals
   (`clones/`, numpy only). Those totals stop at the day before the slate.
   The logistic probabilities, the model pick, and the player order are
   computed first and are not rewritten. If Tims has not posted today's
   lists, `today.json` stays on the previous slate and the process exits 75.
5. Writes `today.json` when today's lists were scored. The first lists are
   the morning picks. A later check that adds or removes players appends a
   snapshot. Anyone missing from a check is off the list. A player is also
   off the list once their team's NHL start has passed, even if Tims still
   lists them. The graded pick is whoever was the pick at the moment their
   game started. A scratch before that start moves the pick. If every
   candidate was scratched before a game, that group has no graded pick.
   Season totals use the locked pick.

The recorded pick is whoever the method ranks first on the current list
(ties share it, and the hit is the fraction who scored). The first lists
of the day are kept as the morning picks and graded only as a reference.
Season totals use the current pick. A day that is already graded is not
rewritten. Top-3 hits are how many of the first three players still on the
list scored. The random baseline is the share of those players who scored,
which is what a random pick would be expected to hit. The running hit rate
is cumulative hits over cumulative graded picks.

Normalized groups file:

```json
{
  "date": "2026-11-14",
  "groups": [
    {
      "id": 1,
      "players": [
        {
          "nhlPlayerId": 8478402,
          "fullName": "Connor McDavid",
          "team": "EDM",
          "opponent": "SJS",
          "homeAway": "HOME",
          "position": "C"
        }
      ]
    }
  ]
}
```

The Tims adapter also accepts the `pickGroups` shape in
`tests/fixtures/tims_picks.json`. Scratched players are marked unavailable
and are not scored.

Flags: `--date`, `--groups`, `--publish`, `--raw`, `--no-refresh`,
`--no-grade`, `--rescore`, `--backfill-clones`, `--backfill-starts`, `--relabel`, `--log`. A graded
day is not scored again. `--rescore` recomputes a slate that is still pending.
A still-pending day is graded if its games are final. If the available
players are unchanged, the current picks stay. If players were added or
removed, the day stores a snapshot and the current picks are scored again.

The run refreshes NHL results and grades every unfinished published day
before it asks for today's lists. Exit 0 is a full success. Exit 1 is a
refresh, publish, or other groups error. Exit 75 means today's lists are
not posted yet: past days were still graded, `today.json` was not replaced
with a new slate, and an hourly caller should retry.

## After a name or chart change

`--relabel` rewrites the public method names on days already in the publish
directory and rebuilds `season.json`, including the year-to-date charts. It
does not rescore the logistic model and it does not use the network.

```
cd ~/tims-hockey
git pull
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --relabel \
  --log ~/tims-hockey/logs/relabel.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Copy `web/index.html`, `web/app.js`, and `web/style.css` into
`~/public_html/tools/hockey/` when the page itself should change. The cron
does not copy HTML.

To add NHL start times to days already published, without changing picks
or grades, run this on the host. It reads `today.json` and
`days/YYYY-MM-DD.json` only. It does not open `data/seasons/`. Then rsync
so the page and the next cron share the same files:

```
cd ~/tims-hockey
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-starts \
  --log ~/tims-hockey/logs/backfill-starts.log
rsync -a --delete --exclude '/seasons/' ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

Running it again changes nothing. A date whose score feed fails is left
as it was.

If a day file does not yet have the scoring-rate estimate and the
goals-per-game ranking, run `--backfill-clones` first. That walks every
`days/YYYY-MM-DD.json` from 2026-11-02 onward, using public NHL totals
through the day before each slate. It does not rescore the logistic model
and it does not need Tims credentials. `--backfill-from` and `--backfill-to`
narrow the window. A failed day is left as it was; exit 1 means at least one
day failed, and rerunning is safe.

```
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-clones \
  --log ~/tims-hockey/logs/backfill.log
```

## Secrets

Credentials live only in the file named by `TIMS_ENV`, for example
`~/tims-hockey/secrets/tims.env`. That file is outside the repo and outside
`public_html`. `deploy/tims.env.example` lists `TIMS_CLIENT_ID`,
`TIMS_COGNITO_ID`, and `TIMS_REFRESH_TOKEN`. chmod 600.

The job will not use a secrets file under `public_html` or inside the
publish directory. It does not log credential values. The publisher rejects
a document that contains a secret field. The log path is refused if it sits
in the publish directory or under `public_html`.

The picks client is read-only. It sends the refresh call and the
`HockeyPlayers` query, and nothing that submits a pick. It does not start
a magic-link sign-in. If Cognito returns a new refresh token, that value is
written back to the same secrets file. If the refresh token is rejected,
the run logs the failure outside the web root and leaves yesterday's
published JSON in place.

## Server layout and cron

See `deploy/README.md`. Bluehost cron is MST and may ignore `CRON_TZ`, so
the clock lives in `job/cron_run.sh`. Install a five-minute cadence and let
the script decide. From 03:00 through 13:59 America/Toronto it retries the
morning slate once an hour (minute 00 or 05) until today is graded or
partial. Pending still runs. Exit 75 retries on the next hour. It also
checks Tims at 00:00, 03:00, 12:30, 13:00, 14:00, 15:00, 15:30, 16:00,
17:00, 18:00, 18:30, 19:00, 19:30, 20:00, 20:30, 21:00, 21:30, and 22:00
Toronto, including after the morning slate is up. Grading
still publishes, and that case is rsynced. `*/30` works in place of `*/5`;
do not install both.

```
*/5 * * * * $HOME/tims-hockey/job/cron_run.sh
```

Publish-dir layout after a run:

```
today.json
season.json
seasons.json
days/index.json
days/YYYY-MM-DD.json
```

`rsync` copies that tree to `public_html/tools/hockey/data/`. `seasons.json`
is rewritten on every publish. `data/seasons/` is not in the publish tree.
The rsync uses `--delete` and `--exclude '/seasons/'`, so a backtest dropped
into `data/seasons/` is neither deleted nor overwritten. The HTML is copied
by hand from `web/` when the page changes. Do not rsync the repo, the raw
files, or the secrets file into `public_html`.

## Tests

```
python3 -m venv .venv
.venv/bin/pip install numpy pandas scikit-learn pytest vermin
.venv/bin/python -m pytest
```

* `tests/test_parity.py` — `logistic_json` against `train_utils.X` and a
  sklearn pipeline on `tests/fixtures/feature_rows.json`.
* `tests/test_schema.py` — publish-dir schema, and the page sources.
* `tests/test_py39.py` — vermin, Python 3.9 or older, on `model/`, `job/`, and `tests/`.
* Group parsing, grading, the incremental refresh, the two extra methods,
  and a tiny end-to-end run are the other files in `tests/`.

Rebuild the screenshot fixture with `python tests/build_fixture_site.py`.
Those probabilities are hand-set sample data, not a model run.
